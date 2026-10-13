"""Builtin factories. New contributions use entry points/module:factory, not this list."""

from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass, fields
from hashlib import sha256
from importlib import metadata
import importlib
import inspect
import json
from pathlib import Path
from typing import get_type_hints
from .core import (
    API_VERSION,
    ContractError,
    EmbeddingSpace,
    FrozenMap,
    PluginBinding,
    PluginSpec,
    fingerprint,
    from_data,
    to_data,
    validate_capabilities,
)
from .core.values import identifier, require


ENTRY_POINT_GROUP = 'memfolder.plugins'


@dataclass(frozen=True, kw_only=True)
class PluginRequest:
    plugin: str  # registered/installed name, or an explicit module:factory
    parameters: FrozenMap = FrozenMap()

    def __post_init__(self):
        identifier(self.plugin)
        require(self.plugin == self.plugin.strip(), 'Plugin reference has surrounding whitespace')
        require(isinstance(self.parameters, Mapping), 'Plugin parameters must be an object')
        object.__setattr__(self, 'parameters', FrozenMap(self.parameters))

    @classmethod
    def from_mapping(cls, value: Mapping):
        require(isinstance(value, Mapping) and set(value) <= {'plugin', 'parameters'}
                and 'plugin' in value, 'Plugin config needs plugin and optional parameters only')
        return cls(plugin=value['plugin'], parameters=value.get('parameters', {}))


@dataclass(frozen=True, kw_only=True)
class BuildContext:
    """Configuration-relative paths; providers resolve their own assets explicitly."""
    base_path: Path
    registry: object | None = None  # application-owned; nested factories reuse this catalog
    available: tuple[str, ...] = ()
    binding_sink: object | None = None

    def __post_init__(self):
        object.__setattr__(self, 'base_path', Path(self.base_path).resolve())

    def path(self, value: str) -> Path:
        require(type(value) is str and bool(value), 'Plugin data path must be a nonempty string')
        path = Path(value)
        return (path if path.is_absolute() else self.base_path / path).resolve()


@dataclass(frozen=True, kw_only=True)
class BuiltPlugin:
    instance: object
    binding: PluginBinding
    reference: str


def read_plugin_request(path: str | Path) -> tuple[PluginRequest, BuildContext]:
    path = Path(path).resolve()
    require(path.is_file() and path.stat().st_size <= 1024 * 1024, 'Missing/oversized plugin config')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate plugin config field')
            result[key] = value
        return result
    def constant(value):
        raise ContractError('Nonfinite plugin config number')
    try:
        raw = path.read_bytes()
        require(len(raw) <= 1024 * 1024, 'Oversized plugin config')
        values = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs, parse_constant=constant)
    except (json.JSONDecodeError, UnicodeError):
        raise ContractError('Invalid plugin config JSON') from None
    return PluginRequest.from_mapping(values), BuildContext(base_path=path.parent)


def _import_factory(target):
    module, separator, name = target.partition(':')
    require(separator and module and name and ':' not in name
            and all(part.isidentifier() for part in module.split('.')) and name.isidentifier(),
            'Plugin target must be module:factory')
    try:
        return getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError):
        raise ContractError('Plugin factory unavailable; check installation and optional dependencies') from None


class PluginRegistry:
    """Per-application registry; registration never initializes plugin code.

    Factories expose .spec (PluginSpec) and accept (parameters, *, context).
    Discovery collects entry-point metadata only. Only create() loads a provider.
    """

    def __init__(self):
        self._factories = {}

    def register(self, name: str, factory) -> None:
        identifier(name)
        require(':' not in name and name not in self._factories, 'Duplicate/invalid plugin registration')
        require(type(factory) is str or callable(factory), 'Plugin registration needs a target or callable factory')
        self._factories[name] = factory

    def discover(self, *, entry_points=None) -> None:
        entries = metadata.entry_points(group=ENTRY_POINT_GROUP) if entry_points is None else entry_points
        pending = {}
        for entry in entries:
            require(entry.group == ENTRY_POINT_GROUP and ':' not in entry.name
                    and entry.name not in self._factories and entry.name not in pending,
                    'Duplicate/invalid installed plugin name')
            identifier(entry.name)
            pending[entry.name] = entry
        self._factories.update(pending)  # transactional: collisions leave registry unchanged

    @property
    def references(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def create(self, request: PluginRequest, *, role: str, context: BuildContext | None = None,
               available: tuple[str, ...] = (), api_version: int = API_VERSION) -> BuiltPlugin:
        require(type(request) is PluginRequest, 'Expected PluginRequest')
        identifier(role)
        factory = self._factories.get(request.plugin)
        entry = None
        if factory is None:
            require(':' in request.plugin, 'Unknown plugin; register it, install its package, or use module:factory')
            factory = _import_factory(request.plugin)
        elif type(factory) is str:
            factory = _import_factory(factory)
        elif not callable(factory):
            entry = factory
            try:
                factory = entry.load()
            except (ImportError, AttributeError):
                raise ContractError('Installed plugin unavailable; check its optional dependencies') from None
        require(callable(factory), 'Plugin factory is not callable')
        spec = getattr(factory, 'spec', None)
        require(type(spec) is PluginSpec, 'Plugin factory must advertise a PluginSpec as .spec')
        require(spec.role == role, 'Plugin role mismatch')
        validate_capabilities(spec, available, api_version=api_version)
        context = context or BuildContext(base_path=Path.cwd())
        require(type(context) is BuildContext, 'Expected BuildContext')
        if context.registry is None:
            from dataclasses import replace
            context = replace(context, registry=self)
        if not context.available and available:
            from dataclasses import replace
            context = replace(context, available=tuple(available))
        try:
            instance = factory(request.parameters, context=context)
        except Exception:
            # Factory parameters or exception messages can contain secrets/source content.
            raise ContractError('Plugin factory rejected configuration; check its documented parameters') from None
        require(getattr(instance, 'spec', None) == spec, 'Constructed plugin changed its advertised spec')
        method = {'data_loader': 'samples', 'memory_loader': 'load', 'planner': 'plan',
            'operator': 'apply', 'feature_provider': 'extract', 'candidate_generator': 'generate',
            'affinity_scorer': 'score', 'gate_policy': 'decide', 'matcher': 'match',
            'anchor_selector': 'select', 'group_router': 'route', 'partitioner': 'partition',
            'text_writer': 'write', 'record_builder': 'build', 'fact_planner': 'extract',
            'compiler': 'compile', 'verifier': 'verify', 'triage_policy': 'required',
            'feedback_builder': 'feedback', 'round_selector': 'choose', 'budget_allocator':'allocate',
            'pair_router':'pair', 'graph_classifier':'classify', 'graph_selector':'select','member_resolver':'resolve',
            'group_assigner':'assign','wrapper':'export','native_codec':'encode','native_writer':'write',
            'graph_projector':'project','embedding_provider':'refresh','asset_copier':'copy',
            'initializer':'initialize','reader':'predict','evaluator':'evaluate','retriever':'retrieve',
            'context_builder':'build','answerer':'answer','metric':'score','observer':'on_event',
            'redactor':'redact','judge_prompt':'build','reader_prompt':'build'}.get(role)
        require(method is None or callable(getattr(instance, method, None)), 'Plugin lacks its role method')
        if role == 'wrapper':
            require(all(callable(getattr(instance,m,None)) for m in ('export','project','materialize')), 'Wrapper lacks export/project/materialize')
        if role == 'observer':
            require(all(callable(getattr(instance,m,None)) for m in ('open','on_event','close')),'Observer lacks its lifecycle')
        try:
            subject = factory if inspect.isfunction(factory) or inspect.isclass(factory) else type(factory)
            file = inspect.getsourcefile(subject)
            revision = 'sha256:' + sha256(Path(file).read_bytes()).hexdigest() if file else None
        except (OSError, TypeError):
            revision = None
        if revision is None:
            module = inspect.getmodule(subject)
            loader = getattr(module, '__loader__', None)
            if callable(getattr(loader, 'get_source', None)):
                source = loader.get_source(module.__name__)
                if source is not None:
                    revision = 'sha256:' + sha256(source.encode('utf-8')).hexdigest()
        if revision is None and entry is not None and getattr(entry, 'dist', None) is not None:
            revision = 'distribution:' + entry.dist.metadata['Name'] + '@' + entry.dist.version
        require(revision is not None, 'Plugin implementation needs inspectable source or distribution metadata')
        binding = PluginBinding(plugin_id=spec.plugin_id, role=spec.role, api_version=spec.api_version,
            implementation_revision=revision, parameters_fingerprint=fingerprint(request.parameters))
        if context.binding_sink is not None:
            context.binding_sink(binding)
        return BuiltPlugin(instance=instance, binding=binding, reference=request.plugin)


class Factory:
    """Explicit role map keeps each stage independently configurable."""
    def __init__(self,cls,*,roles=None,defaults=None):
        self.cls=cls;self.spec=cls.spec;self.roles=roles or {};self.defaults=defaults or {}
    def __call__(self,parameters,*,context):
        values={**self.defaults,**parameters};allowed={f.name for f in fields(self.cls)}
        require(set(values)<=allowed,'Unknown component parameter')
        hints=get_type_hints(self.cls)
        for key,value in list(values.items()):
            if key in self.roles:
                request=PluginRequest.from_mapping(value)
                values[key]=context.registry.create(request,role=self.roles[key],context=context,
                                                     available=context.available).instance
            elif key=='space':
                values[key]=from_data(EmbeddingSpace,to_data(value))
            elif key=='grounding' and type(value) is str:
                path=context.path(value);require(path.is_file() and path.stat().st_size<=256*1024*1024,'Missing/oversized grounding file')
                values[key]=FrozenMap(json.loads(path.read_text(encoding='utf-8-sig')))
            elif hints.get(key) is bool:require(type(value) is bool,'Expected boolean parameter: '+key)
            elif hints.get(key) is int:require(type(value) is int,'Expected integer parameter: '+key)
            elif hints.get(key) is float:require(type(value) in (int,float),'Expected numeric parameter: '+key)
            elif hints.get(key) is str:require(type(value) is str,'Expected text parameter: '+key)
            elif hints.get(key) is FrozenMap:values[key]=FrozenMap(value)
            elif key in ('participants','text_kinds','media_kinds'):
                require(isinstance(value,(list,tuple)) and all(type(v) is str for v in value),'Expected list of strings')
                values[key]=tuple(value)
        return self.cls(**values)
