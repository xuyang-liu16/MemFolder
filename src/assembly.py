"""Config-only Planner/Operator assembly, with independently installed subplugins."""
from dataclasses import dataclass
from pathlib import Path
from dataclasses import fields,is_dataclass
from hashlib import sha256
import inspect
from .core import FrozenMap, fingerprint
from .core.values import require
from .plugins import BuildContext, PluginRequest
from .catalog import default_registry
from .compression import CompressionEngine


@dataclass(frozen=True)
class Assembly:
    engine: CompressionEngine
    bindings: tuple
    config_fingerprint: str
    source_manifest: FrozenMap
    wrapper: object | None = None

    async def run(self, source, **kwargs):
        require(self.wrapper is not None, 'Configure a wrapper before running a memory bank')
        from .wrappers import run_wrapped
        return await run_wrapped(self.engine, self.wrapper, source, **kwargs)


def binding_parameters(value):
    """Stable default parameters, including containers of child plugins.

    Children have their own implementation bindings; their process-local object
    addresses must never become part of a resumable experiment fingerprint.
    """
    def stable(item):
        if hasattr(item,'spec'):return {'plugin_id':item.spec.plugin_id}
        if isinstance(item,(tuple,list)):return [stable(v) for v in item]
        if isinstance(item,dict):return {k:stable(v) for k,v in item.items()}
        if inspect.isfunction(item) or inspect.isclass(item):return {'callable':item.__module__+'.'+item.__qualname__}
        return repr(item)
    return fingerprint({f.name:stable(getattr(value,f.name)) for f in fields(value)}) if is_dataclass(value) else fingerprint({})


def assemble(configuration,*,registry=None,base_path=None,available=()):
    require(set(configuration)<= {'planner','operator','features','wrapper'} and 'planner' in configuration and 'operator' in configuration,
            'Assembly config needs planner, operator and optional features/wrapper')
    registry=registry or default_registry();bindings=[]
    context=BuildContext(base_path=Path(base_path or Path.cwd()),registry=registry,available=tuple(available),binding_sink=bindings.append)
    def create(value,role):
        return registry.create(PluginRequest.from_mapping(value),role=role,context=context,available=tuple(available)).instance
    planner=create(configuration['planner'],'planner');operator=create(configuration['operator'],'operator')
    providers=tuple(create(value,'feature_provider') for value in configuration.get('features',()))
    wrapper=create(configuration['wrapper'],'wrapper') if 'wrapper' in configuration else None
    # Capture default children too. This covers algorithm modules, rather than just
    # the generic factory source. External factories retain their registry binding.
    from .core import PluginBinding
    def walk(value):
        component_spec=getattr(value,'spec',None)
        file=inspect.getsourcefile(type(value)) if component_spec else None
        if file:
            bindings.append(PluginBinding(plugin_id=component_spec.plugin_id,role=component_spec.role,
                api_version=component_spec.api_version,implementation_revision='sha256:'+sha256(Path(file).read_bytes()).hexdigest(),
                parameters_fingerprint=binding_parameters(value)))
        if is_dataclass(value):
            for f in fields(value):
                child=getattr(value,f.name)
                if hasattr(child,'spec') or isinstance(child,(tuple,list)):walk(child)
        elif isinstance(value,(tuple,list)):
            for child in value:walk(child)
    for value in (planner,operator,*providers,wrapper):
        if value is not None:walk(value)
    root=Path(__file__).parent
    source_manifest=FrozenMap({p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*.py'))})
    return Assembly(CompressionEngine(planner,operator,providers,tuple(available)),tuple(dict.fromkeys(bindings)),
                    fingerprint(FrozenMap(configuration)),source_manifest,wrapper)
