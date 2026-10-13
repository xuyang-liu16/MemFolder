"""Builtin memory-loader factories. The generic registry never names a framework."""

from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from .contracts import LoadOptions
from ..core import EmbeddingSpace, FrozenMap, PluginSpec, from_data, to_data
from ..core.values import require
from .memory_libraries import (
    load_library,
    load_m3,
    load_mem0,
    load_mem0_legacy_nodes,
    load_mem0_qdrant,
    load_mem0_sqlite,
    load_memos,
    load_memos_cube,
)
from ..plugins import BuildContext, PluginRegistry


def options_from_mapping(values: Mapping) -> LoadOptions:
    require(isinstance(values, Mapping) and set(values) <= {f.name for f in fields(LoadOptions)},
            'Unknown/invalid memory loading options')
    values = to_data(FrozenMap(values))
    spaces = values.get('embedding_spaces', {})
    require(type(spaces) is dict, 'embedding_spaces must be an object')
    values['embedding_spaces'] = {k: from_data(EmbeddingSpace, v) for k,v in spaces.items()}
    return LoadOptions(**values)


@dataclass(frozen=True, kw_only=True)
class _ConfiguredMemoryLoader:
    spec: PluginSpec
    function: object
    path: Path
    options: LoadOptions
    extra: FrozenMap
    source_paths: tuple[Path, ...]

    def load(self, *, observer=None):
        return self.function(self.path, options=self.options, observer=observer, **dict(self.extra))


def _factory(name, function, *, qdrant=False, graph=False):
    spec = PluginSpec(plugin_id='memfolder.memory.' + name.replace('-', '.'), role='memory_loader',
        provides=('memory.snapshot', 'memory.lineage') + (('memory.graph',) if graph else ()))
    def build(parameters: FrozenMap, *, context: BuildContext):
        allowed = {'path', 'options'} | ({'collection', 'page_size', 'metadata_path'} if qdrant else set())
        require(set(parameters) <= allowed and 'path' in parameters, 'Unknown/missing memory loader parameters')
        path = context.path(parameters['path'])
        options = options_from_mapping(parameters.get('options', FrozenMap()))
        extra, sources = {}, [path]
        if qdrant:
            collection, page_size = parameters.get('collection','mem0'), parameters.get('page_size',256)
            require(type(collection) is str and bool(collection), 'Invalid collection')
            require(type(page_size) is int and page_size > 0, 'Invalid page_size')
            extra.update(collection=collection, page_size=page_size)
            if 'metadata_path' in parameters:
                meta = context.path(parameters['metadata_path'])
                extra['metadata_path'] = str(meta)
                sources.append(meta)
        return _ConfiguredMemoryLoader(spec=spec, function=function, path=path, options=options,
                                       extra=FrozenMap(extra), source_paths=tuple(sources))
    build.spec = spec
    return build


mem0 = _factory('mem0', load_mem0)


mem0_legacy = _factory('mem0-legacy', load_mem0_legacy_nodes)


mem0_qdrant = _factory('mem0-qdrant', load_mem0_qdrant, qdrant=True)


mem0_sqlite = _factory('mem0-sqlite', load_mem0_sqlite)


memos = _factory('memos', load_memos, graph=True)


memos_cube = _factory('memos-cube', load_memos_cube, graph=True)


m3 = _factory('m3', load_m3, graph=True)


canonical = _factory('canonical', load_library, graph=True)


def register_memory_loaders(registry: PluginRegistry) -> None:
    # A provider-owned catalog, not a core dispatch switch. External providers
    # register themselves or publish entry points without editing this list.
    for name, factory in {'mem0':mem0, 'mem0-legacy':mem0_legacy, 'mem0-qdrant':mem0_qdrant,
                         'mem0-sqlite':mem0_sqlite, 'memos':memos, 'memos-cube':memos_cube,
                         'm3':m3, 'canonical':canonical}.items():
        registry.register(name, factory)
