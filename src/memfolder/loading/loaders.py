"""Convenient loader plugins assembled from transport + native-format adapter."""
from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from memfolder.core import ArtifactRef, ContentPart, FrozenMap, PluginSpec, RetentionPolicy, dumps, loads
from memfolder.core.values import require
from .adapters import M3Adapter, Mem0Adapter, Mem0LegacyNodesAdapter, MemOSAdapter
from .common import object_value
from .importer import Importer, normalize
from .m3_pickle import read_m3_pickle
from .qdrant_sqlite import read_qdrant_sqlite
from .readers import SourceDocument, child_path, read_json, read_local_qdrant, read_qdrant
from .types import (
    FormatAdapter, ImportObserver, LoadedLibrary, LoadOptions, NativeLibrary, NativeRecord,
)


@dataclass(frozen=True, kw_only=True)
class JsonMemoryLoader:
    paths: tuple[str | Path, ...]
    adapter: FormatAdapter
    options: LoadOptions = LoadOptions()

    @property
    def spec(self):
        return Importer(adapter=self.adapter, options=self.options).spec

    def load(self, *, observer: ImportObserver | None = None) -> LoadedLibrary:
        require(bool(self.paths), 'No JSON memory files supplied')
        return Importer(adapter=self.adapter, options=self.options).load_documents(
            (read_json(p, options=self.options, source_id=f'file:{index}:{Path(p).name}')
             for index, p in enumerate(self.paths)), observer=observer)


def load_mem0(path: str | Path, *, options: LoadOptions = LoadOptions(), observer=None) -> LoadedLibrary:
    return JsonMemoryLoader(paths=(path,), adapter=Mem0Adapter(), options=options).load(observer=observer)


def load_mem0_legacy_nodes(path: str | Path, *, options: LoadOptions = LoadOptions(), observer=None) -> LoadedLibrary:
    return JsonMemoryLoader(paths=(path,), adapter=Mem0LegacyNodesAdapter(), options=options).load(observer=observer)


def load_mem0_qdrant(path: str | Path, *, collection: str = 'mem0', options: LoadOptions = LoadOptions(),
                     observer=None, page_size: int = 256, client_factory=None,
                     metadata_path: str | Path | None = None) -> LoadedLibrary:
    doc = read_local_qdrant(path, collection, options=options, page_size=page_size,
                           client_factory=client_factory, metadata_path=metadata_path)
    return Importer(adapter=Mem0Adapter(), options=options).load_documents((doc,), observer=observer)


def load_mem0_sqlite(path: str | Path, *, options: LoadOptions = LoadOptions(), observer=None) -> LoadedLibrary:
    """Offline Qdrant points file, including split backups with no meta.json."""
    doc = read_qdrant_sqlite(path, options=options)
    return Importer(adapter=Mem0Adapter(), options=options).load_documents((doc,), observer=observer)


def load_mem0_client(client, collection: str = 'mem0', *, options: LoadOptions = LoadOptions(),
                     observer=None, page_size: int = 256, scroll_filter=None) -> LoadedLibrary:
    doc = read_qdrant(client, collection, options=options, page_size=page_size, scroll_filter=scroll_filter)
    return Importer(adapter=Mem0Adapter(), options=options).load_documents((doc,), observer=observer)


def load_memos(path: str | Path, *, options: LoadOptions = LoadOptions(), observer=None) -> LoadedLibrary:
    """Standalone textual JSON/JSONL; supply cube identity explicitly if absent in rows."""
    return JsonMemoryLoader(paths=(path,), adapter=MemOSAdapter(), options=options).load(observer=observer)


def _hash_file(path: Path, limit: int) -> str:
    require(path.is_file() and path.stat().st_size <= limit, 'Missing/oversized cube artifact')
    result, size = sha256(), 0
    with path.open('rb') as stream:
        while raw := stream.read(1024 * 1024):
            size += len(raw)
            require(size <= limit, 'Cube artifact exceeds configured size limit')
            result.update(raw)
    return result.hexdigest()


def _cube_sources(path: Path, options: LoadOptions, index: int):
    root = path.resolve()
    config_doc = read_json(root / 'config.json', options=options, source_id=f'cube:{index}:config')
    config = object_value(config_doc.data, 'cube configuration')
    cube = config.get('cube_id') or options.namespace
    require(type(cube) is str and bool(cube), 'Cube configuration needs cube_id (or explicit namespace)')
    require(options.namespace is None or options.namespace == cube, 'Cube configuration conflicts with namespace')
    scoped_options = replace(options, namespace=cube)
    decoded = []
    filenames = set()
    for memory_type in ('text_mem', 'pref_mem', 'act_mem', 'para_mem'):
        component = config.get(memory_type)
        if component is None:
            continue
        component = object_value(component, 'cube.' + memory_type)
        backend = component.get('backend', 'uninitialized')
        if backend == 'uninitialized':
            continue
        settings = object_value(component.get('config', {}), 'cube.' + memory_type + '.config')
        default = {'text_mem': 'textual_memory.json', 'pref_mem': 'textual_memory.json',
                   'act_mem': 'activation_memory.pickle', 'para_mem': 'parametric_memory.adapter'}[memory_type]
        filename = settings.get('memory_filename', default)
        file = child_path(root, filename)
        require(file.is_file(), f'Cube {memory_type}: configured memory file is missing')
        require(file not in filenames, 'Multiple active cube components reference the same file; explicit export required')
        filenames.add(file)
        source_id = f'cube:{index}:{cube}:{memory_type}'
        # The full config may contain credentials. Only these non-secret fields are retained.
        config_summary = {'cube_id': cube, 'component': memory_type, 'backend': backend, 'filename': filename}
        if memory_type in ('text_mem', 'pref_mem'):
            doc = read_json(file, options=options, source_id=source_id)
            lib = MemOSAdapter().decode(doc.data, options=scoped_options, source_id=source_id)
            lib = replace(lib, metadata=FrozenMap({**dict(lib.metadata), 'cube_config': config_summary}))
        else:
            digest = _hash_file(file, options.max_file_bytes)
            # Keep activation/parameter memories as protected opaque artifacts, never unpickle them.
            ref = ArtifactRef(artifact_id='memos:' + cube + ':' + memory_type,
                path=file.relative_to(root).as_posix(), sha256=digest,
                media_type='application/octet-stream', schema_id='memos.' + memory_type)
            record = NativeRecord(native_id=memory_type, namespace='cube:' + cube + ':artifacts',
                sample_key=cube, partition_key='cube:' + cube + ':artifacts',
                parts=(ContentPart(modality='tensor' if memory_type == 'act_mem' else 'parameters', artifact=ref),),
                native=FrozenMap(config_summary), selectors=FrozenMap({'cube_id': cube, 'memory_type': memory_type}),
                kind=memory_type, eligible=False,
                retention=RetentionPolicy(may_drop=False, may_merge=False, may_rewrite=False))
            doc = SourceDocument(source_id=source_id, data=None, sha256=digest)
            lib = NativeLibrary(framework='memos', format_id='memos.opaque.v1', records=(record,),
                                metadata=FrozenMap(config_summary))
        decoded.append((doc, lib))
    require(bool(decoded), 'Cube contains no initialized memory components')
    return decoded


@dataclass(frozen=True, kw_only=True)
class MemOSCubeLoader:
    paths: tuple[str | Path, ...]
    options: LoadOptions = LoadOptions()
    spec = PluginSpec(plugin_id='memos.cube.v1', role='memory_loader',
        provides=('memory.snapshot', 'memory.lineage', 'memory.graph', 'memory.artifact_refs'))

    def load(self, *, observer: ImportObserver | None = None):
        sources = [s for index, path in enumerate(self.paths) for s in _cube_sources(Path(path), self.options, index)]
        return normalize(sources, options=self.options, observer=observer)


def load_memos_cube(path: str | Path, *, options: LoadOptions = LoadOptions(), observer=None) -> LoadedLibrary:
    return MemOSCubeLoader(paths=(path,), options=options).load(observer=observer)


@dataclass(frozen=True, kw_only=True)
class M3GraphLoader:
    paths: tuple[str | Path, ...]
    options: LoadOptions = LoadOptions()
    spec = PluginSpec(plugin_id='m3.graph.v1', role='memory_loader',
        provides=('memory.snapshot', 'memory.lineage', 'memory.graph', 'memory.clip_scopes', 'memory.multimodal'))

    def load(self, *, observer: ImportObserver | None = None):
        docs = []
        for index, path in enumerate(self.paths):
            path = Path(path)
            label = f'graph:{index}:{path.name}'
            if path.suffix.lower() in ('.pkl', '.pickle'):
                doc = read_m3_pickle(path, options=self.options, source_id=label)
            else:
                doc = read_json(path, options=self.options, source_id=label)
            docs.append(doc)
        return Importer(adapter=M3Adapter(), options=self.options).load_documents(docs, observer=observer)


def load_m3(path: str | Path, *, options: LoadOptions = LoadOptions(), observer=None) -> LoadedLibrary:
    return M3GraphLoader(paths=(path,), options=options).load(observer=observer)


def save_library(library: LoadedLibrary, path: str | Path) -> None:
    """Portable, strict wire envelope. Exclusive create protects prior exports."""
    text = dumps(library, indent=2) + '\n'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(text)


def load_library(path: str | Path, *, options: LoadOptions = LoadOptions(), observer=None) -> LoadedLibrary:
    """Reload the canonical bundle without changing IDs, vectors, scopes, or lineage."""
    path = Path(path)
    require(path.is_file() and path.stat().st_size <= options.max_file_bytes, 'Missing/oversized library bundle')
    raw = path.read_bytes()
    require(len(raw) <= options.max_file_bytes, 'Library bundle exceeds size limit')
    library = loads(raw.decode('utf-8-sig'), expected=LoadedLibrary)
    require(library.report.records_loaded <= options.max_records, 'Library record limit exceeded')
    require(options.allow_partial or all(s.coverage != 'partial' for s in library.report.sources), 'Partial canonical bundle')
    require(not options.selectors and not options.sample_map and options.sample_id is None
            and options.namespace is None and not options.embedding_spaces and options.visibility_field is None
            and options.naive_timezone is None and options.numeric_timestamp_clock is None and options.order_by == 'source'
            and options.timestamp_fields == ('timestamp',) and options.time_semantics == 'event_time'
            and options.missing_time_order == 'error'
            and options.dataset_id == 'imported-memory' and options.split == 'memory',
            'Canonical bundle reload preserves its identities; native remapping options are not applicable')
    if observer:
        for memory in library.inputs:
            observer.on_input(memory)
        observer.on_report(library.report)
    return library
