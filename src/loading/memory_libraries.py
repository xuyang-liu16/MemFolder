"""Normalize, load and save framework-independent memory libraries."""

from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Iterable
from .contracts import (
    FormatAdapter,
    ImportObserver,
    LoadOptions,
    LoadReport,
    LoadedLibrary,
    NativeLibrary,
    NativeRecord,
    SourceInfo,
)
from ..core import (
    ArtifactRef,
    ContentPart,
    DatasetSample,
    Embedding,
    EmbeddingSpace,
    EvaluationSet,
    FrozenMap,
    GraphEdge,
    MemoryInput,
    MemoryRecord,
    OriginRef,
    PluginSpec,
    RetentionPolicy,
    SampleRef,
    ScopeRef,
    Snapshot,
    dumps,
    fingerprint,
    loads,
    to_data,
)
from ..core.values import require
from .memory_adapters import M3Adapter, Mem0Adapter, Mem0NodeExportAdapter, MemOSAdapter
from .source_readers import (
    SourceDocument,
    child_path,
    read_json,
    read_local_qdrant,
    read_m3_pickle,
    read_qdrant,
    read_qdrant_sqlite,
)
from .validation import issue, object_value


def _selected(row: NativeRecord, selectors: FrozenMap) -> bool:
    return all(row.selectors.get(k) in v if isinstance(v, tuple) else row.selectors.get(k) == v
               for k, v in selectors.items())


def _sample_key(row: NativeRecord, options: LoadOptions) -> str:
    return options.sample_id or options.sample_map.get(row.sample_key, row.sample_key)


def normalize(sources: Iterable[tuple[SourceDocument, NativeLibrary]], *, options: LoadOptions,
              observer: ImportObserver | None = None) -> LoadedLibrary:
    sources = tuple(sources)
    require(bool(sources), 'No memory sources supplied')
    require(len({s.source_id for s, _ in sources}) == len(sources), 'Duplicate source labels')
    source_info, issues = [], []
    groups, indexes, origins, source_metadata = defaultdict(list), {}, set(), defaultdict(dict)
    records_filtered, edges_filtered = 0, 0
    total = sum(len(lib.records) for _, lib in sources)
    require(total <= options.max_records, 'Import record limit exceeded')
    selector_keys = {k for _, lib in sources for n in lib.records for k in n.selectors}
    require(set(options.selectors) <= selector_keys or not total, 'Unknown selector for the supplied format')
    for doc, lib in sources:
        coverage = lib.coverage
        if coverage != 'partial' and doc.coverage is not None:
            coverage = doc.coverage
        require(options.allow_partial or coverage != 'partial', f'{doc.source_id}: incomplete export; supply all pages')
        info = SourceInfo(source_id=doc.source_id, framework=lib.framework, format_id=lib.format_id,
            sha256=doc.sha256, records_read=len(lib.records), edges_read=len(lib.edges),
            coverage=coverage, consistency=doc.consistency)
        source_info.append(info)
        issues.extend(lib.issues)
        if coverage == 'partial':
            issues.append(issue('partial_export', doc.source_id, 'source', 'Partial source explicitly accepted.'))
        if not lib.records:
            issues.append(issue('empty_source', doc.source_id, 'source', 'Source contains no memory records.', severity='info'))
        seen = set()
        for index, row in enumerate(lib.records):
            key = (lib.framework, row.namespace, row.native_id)
            require(key not in seen, f'{doc.source_id}: duplicate native memory identity')
            seen.add(key)
            # This index covers filtered nodes too, so truly dangling edges still fail.
            require(key not in indexes, 'Repeated native memory identity across sources; no record was overwritten')
            indexes[key] = None
            if not _selected(row, options.selectors):
                records_filtered += 1
                continue
            sample_id = _sample_key(row, options)
            scope = ScopeRef(dataset_id=options.dataset_id, sample_id=sample_id, partition_id=row.partition_key)
            origin = OriginRef(scope=scope, source_id=row.native_id, revision=row.revision)
            require(origin not in origins, 'Native origins collide after scope mapping')
            origins.add(origin)
            nid = lib.framework + ':' + fingerprint((scope, row.namespace, row.native_id))
            vectors = row.vectors
            embeddings, bound_spaces = [], set()
            declarations = {}
            if not any(vectors.values()):
                issues.append(issue('embedding_absent', doc.source_id, f'records[{index}]',
                                    'No dense vectors were supplied for this record.', severity='info'))
            for slot, values in vectors.items():
                if not values:
                    continue
                space = options.embedding_spaces.get(slot)
                if space is None:
                    issues.append(issue('embedding_space_undeclared', doc.source_id, f'records[{index}]',
                                        'All vectors retained; model/space identity was not inferred from dimensions.'))
                    continue
                require(all(len(v) == space.dimension for v in values), f'{doc.source_id}: declared embedding dimension mismatch')
                declarations[slot] = to_data(space)
                if len(values) != 1:
                    issues.append(issue('multiple_vectors_preserved', doc.source_id, f'records[{index}]',
                                        'Multiple vectors retained for explicit downstream pooling; no representative was chosen.'))
                    continue
                require(space not in bound_spaces, f'{doc.source_id}: multiple slots declare the same content embedding space')
                bound_spaces.add(space)
                embeddings.append(Embedding(space=space, source_fingerprint=fingerprint(row.parts), values=values[0]))
            native = FrozenMap({'framework': lib.framework, 'namespace': row.namespace, 'id': row.native_id,
                'record': to_data(row.native), 'vectors': to_data(vectors), 'embedding_spaces': declarations,
                **({'user_id':str(row.selectors['user_id'])} if row.selectors.get('user_id') is not None else {}),
                'embedding_binding': 'source_declared_unverified' if embeddings else 'unbound'})
            record = MemoryRecord(node_id=nid, scope=scope, order=len(groups[sample_id]), origins=(origin,),
                parts=row.parts, kind=row.kind, eligible=row.eligible, retention=row.retention,
                time_ranges=row.time_ranges, available_at=row.available_at, expires_at=row.expires_at,
                embeddings=tuple(embeddings), native=native,
                extensions=FrozenMap({**row.extensions,
                    'memfolder.import': {'source_id': doc.source_id, 'source_index': index}}))
            groups[sample_id].append(record)
            indexes[key] = record
            source_metadata[sample_id][doc.source_id] = {'source': to_data(info), 'metadata': to_data(lib.metadata)}
    graph_groups = defaultdict(list)
    for doc, lib in sources:
        for index, edge in enumerate(lib.edges):
            start_key = (lib.framework, edge.source_namespace, edge.source_id)
            end_key = (lib.framework, edge.target_namespace, edge.target_id)
            require(start_key in indexes and end_key in indexes, f'{doc.source_id}: dangling native edge')
            start, end = indexes[start_key], indexes[end_key]
            if start is None or end is None:
                edges_filtered += 1
                continue
            require(start.scope.sample_id == end.scope.sample_id, 'Graph edge crosses sample boundaries')
            eid = lib.framework + ':edge:' + fingerprint((start.node_id, end.node_id, edge.relation,
                edge.native_id, index))
            graph_groups[start.scope.sample_id].append(GraphEdge(edge_id=eid,
                source_id=start.node_id, target_id=end.node_id, relation=edge.relation,
                weight=edge.weight, directed=edge.directed,
                extensions=FrozenMap({'memfolder.import': {'native': to_data(edge.native),
                                                          'source_id': doc.source_id, 'native_id': edge.native_id}})))
    # The full source manifest establishes the identity of this imported dataset version.
    dataset_digest = fingerprint(tuple(sorted((s.framework, s.format_id, s.sha256, s.coverage) for s in source_info)))
    inputs = []
    from dataclasses import replace
    for sample_id in sorted(groups):
        nodes = groups[sample_id]
        if options.order_by == 'native_id':
            nodes.sort(key=lambda n: (n.scope.partition_id, n.native['id']))
        elif options.order_by == 'numeric_native_id':
            import re
            require(all(re.fullmatch(r'[0-9]+', n.native['id']) for n in nodes),
                    'numeric_native_id ordering requires nonnegative integer IDs')
            keys = {(n.scope.partition_id, int(n.native['id'])) for n in nodes}
            require(len(keys) == len(nodes), 'Numeric native IDs collide within a partition')
            nodes.sort(key=lambda n: (n.scope.partition_id, int(n.native['id'])))
        elif options.order_by == 'time_id':
            require(options.missing_time_order == 'first' or all(n.time_ranges for n in nodes),
                    'time_id ordering requires parsed timestamps; declare missing_time_order=first for unknowns')
            require(len({n.time_ranges[0].start.clock for n in nodes if n.time_ranges}) <= 1, 'Ordering mixes time clocks')
            nodes.sort(key=lambda n: (bool(n.time_ranges),
                n.time_ranges[0].start.value if n.time_ranges else 0, n.native['id']))
        nodes = tuple(replace(n, order=i) for i, n in enumerate(nodes))
        assets = {}
        for n in nodes:
            for p in n.parts:
                if p.artifact:
                    previous = assets.get(p.artifact.artifact_id)
                    require(previous is None or previous == p.artifact, 'Conflicting asset identity')
                    assets[p.artifact.artifact_id] = p.artifact
        policy = {}
        if options.order_by == 'numeric_native_id' or options.timestamp_fields != ('timestamp',) \
                or options.time_semantics != 'event_time' or options.missing_time_order != 'error':
            policy['temporal_policy'] = {'timestamp_fields': options.timestamp_fields,
                'time_semantics': options.time_semantics, 'order_by': options.order_by,
                'missing_time_order': options.missing_time_order}
        snapshot = Snapshot(snapshot_id='import:' + fingerprint((options.dataset_id, sample_id, dataset_digest)),
            records=nodes, edges=tuple(graph_groups[sample_id]), assets=tuple(assets.values()),
            extensions=FrozenMap({'memfolder.import': {'sources': source_metadata[sample_id], **policy}}))
        sample = SampleRef(dataset_id=options.dataset_id, sample_id=sample_id, split=options.split,
                           dataset_fingerprint=dataset_digest)
        inputs.append(MemoryInput(sample=sample, initial_snapshot=snapshot, assets=snapshot.assets))
    report = LoadReport(sources=tuple(source_info), samples_loaded=len(inputs),
        records_loaded=sum(len(i.initial_snapshot.records) for i in inputs),
        edges_loaded=sum(len(i.initial_snapshot.edges) for i in inputs),
        eligible_records=sum(n.eligible for i in inputs for n in i.initial_snapshot.records),
        records_filtered=records_filtered, edges_filtered=edges_filtered, issues=tuple(issues))
    library = LoadedLibrary(inputs=tuple(inputs), report=report)
    # Hooks see only immutable contracts, never the adapter, client, source objects, or evaluation labels.
    if observer:
        for memory in library.inputs:
            observer.on_input(memory)
        observer.on_report(report)
    return library


@dataclass(frozen=True, kw_only=True)
class Importer:
    adapter: FormatAdapter
    options: LoadOptions = LoadOptions()

    @property
    def spec(self) -> PluginSpec:
        return PluginSpec(plugin_id=self.adapter.format_id, role='memory_loader',
            provides=('memory.snapshot', 'memory.lineage', 'memory.native_metadata'))

    def load_documents(self, documents: Iterable[SourceDocument], *, observer: ImportObserver | None = None) -> LoadedLibrary:
        decoded = ((doc, self.adapter.decode(doc.data, options=self.options, source_id=doc.source_id)) for doc in documents)
        return normalize(decoded, options=self.options, observer=observer)


@dataclass(frozen=True, kw_only=True)
class NativeVectorSet:
    slot: str
    vectors: tuple[tuple[float, ...], ...]
    space: EmbeddingSpace | None
    content_verified: bool = False


def native_vector_sets(record: MemoryRecord) -> tuple[NativeVectorSet, ...]:
    """Inspect every imported vector, including unnamed and multiple-vector sets."""
    from ..core import from_data
    declarations = record.native.get('embedding_spaces', FrozenMap())
    return tuple(NativeVectorSet(slot=k, vectors=tuple(tuple(v) for v in values),
        space=from_data(EmbeddingSpace, to_data(declarations[k])) if k in declarations else None)
        for k, values in record.native.get('vectors', FrozenMap()).items() if values)


def attach_evaluation(library: LoadedLibrary, evaluations: Iterable[EvaluationSet]):
    """Compose memory imports with separately supplied benchmark labels, without inventing empty evaluations."""
    values = tuple(evaluations)
    indexed = {e.sample.identity: e for e in values}
    require(len(indexed) == len(values), 'Duplicate evaluation sample')
    require(set(indexed) == {i.sample.identity for i in library.inputs}, 'Evaluation samples do not match imported inputs')
    return tuple(DatasetSample(memory=i, evaluation=indexed[i.sample.identity]) for i in library.inputs)


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


def load_mem0_node_export(path: str | Path, *, options: LoadOptions = LoadOptions(), observer=None) -> LoadedLibrary:
    return JsonMemoryLoader(paths=(path,), adapter=Mem0NodeExportAdapter(), options=options).load(observer=observer)


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
