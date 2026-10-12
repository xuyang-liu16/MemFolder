"""Framework-independent normalization, grouping, integrity checks, and analysis hooks."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from memfolder.core import (
    DatasetSample, Embedding, EmbeddingSpace, EvaluationSet, FrozenMap, GraphEdge,
    MemoryInput, MemoryRecord, OriginRef, PluginSpec, SampleRef, ScopeRef, Snapshot,
    fingerprint, to_data,
)
from memfolder.core.values import require
from .common import issue
from .readers import SourceDocument
from .types import (
    FormatAdapter, ImportObserver, LoadedLibrary, LoadOptions, LoadReport,
    NativeLibrary, NativeRecord, SourceInfo,
)


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
    from memfolder.core import from_data
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
