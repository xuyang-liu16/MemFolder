"""Public memory-import contracts; benchmark labels are a separate input."""

from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Literal, Protocol
from ..core import (
    ContentPart,
    Contract,
    EmbeddingSpace,
    FrozenMap,
    MemoryInput,
    PluginSpec,
    RetentionPolicy,
    TimePoint,
    TimeRange,
    record,
)
from ..core.values import digest, identifier, require


@dataclass(frozen=True, kw_only=True)
class LoadOptions:
    dataset_id: str = 'imported-memory'
    split: str = 'memory'
    # Explicitly group an already selected library as one benchmark sample.
    # Without this override, native user/cube/video identities stay separate.
    sample_id: str | None = None
    namespace: str | None = None  # required for unscoped text dumps
    selectors: FrozenMap = field(default_factory=FrozenMap)
    sample_map: FrozenMap = field(default_factory=FrozenMap)
    embedding_spaces: Mapping[str, EmbeddingSpace] = field(default_factory=dict)
    # Slots: "default" for Mem0; "embedding" / "embedding_1024" for MemOS;
    # "episodic" / "semantic" / "img" / "voice" for M3.
    naive_timezone: str | None = None
    numeric_timestamp_clock: str | None = None  # e.g. unix_seconds, declared by the caller
    # Explicit planning clock source; defaults retain the original import behavior.
    timestamp_fields: tuple[str, ...] = ('timestamp',)
    time_semantics: str = 'event_time'
    missing_time_order: Literal['error', 'first'] = 'error'
    visibility_field: str | None = None
    order_by: Literal['source', 'native_id', 'numeric_native_id', 'time_id'] = 'source'
    allow_partial: bool = False
    max_records: int = 1_000_000
    max_file_bytes: int = 2 * 1024**3

    def __post_init__(self):
        for v in (self.dataset_id, self.split):
            identifier(v)
        for v in (self.sample_id, self.namespace, self.naive_timezone, self.visibility_field, self.numeric_timestamp_clock):
            require(v is None or type(v) is str and bool(v.strip()), 'Invalid optional import identifier')
        require(self.order_by in ('source', 'native_id', 'numeric_native_id', 'time_id'), 'Unknown import ordering')
        require(isinstance(self.timestamp_fields, (tuple, list)) and bool(self.timestamp_fields)
                and all(type(v) is str and v and all(v.split('.')) for v in self.timestamp_fields),
                'timestamp_fields must be a nonempty list of field paths')
        require(len(set(self.timestamp_fields)) == len(self.timestamp_fields), 'Repeated timestamp field')
        object.__setattr__(self, 'timestamp_fields', tuple(self.timestamp_fields))
        identifier(self.time_semantics)
        require(self.missing_time_order in ('error', 'first'), 'Unknown missing-time ordering')
        require(type(self.allow_partial) is bool, 'allow_partial must be boolean')
        require(type(self.max_records) is int and self.max_records > 0, 'Invalid record limit')
        require(type(self.max_file_bytes) is int and self.max_file_bytes > 0, 'Invalid file-size limit')
        object.__setattr__(self, 'selectors', FrozenMap(self.selectors))
        object.__setattr__(self, 'sample_map', FrozenMap(self.sample_map))
        require(all(type(v) is str and bool(v.strip()) for v in self.sample_map.values()), 'Invalid sample mapping')
        spaces = dict(self.embedding_spaces)
        require(all(type(k) is str and type(v) is EmbeddingSpace for k, v in spaces.items()), 'Invalid embedding declarations')
        object.__setattr__(self, 'embedding_spaces', MappingProxyType(spaces))


@record('memfolder.loading.issue')
class ImportIssue(Contract):
    code: str
    source_id: str
    location: str
    severity: Literal['info', 'warning'] = 'warning'
    # Never include memory text, vectors, credentials, or raw configuration here.
    message: str = ''


@record('memfolder.loading.source')
class SourceInfo(Contract):
    source_id: str
    framework: str
    format_id: str
    sha256: str
    records_read: int
    edges_read: int
    # Scope completeness is independent of exhausting the supplied file/pages.
    coverage: Literal['declared_complete', 'partial', 'unknown'] = 'unknown'
    consistency: Literal['file', 'best_effort', 'caller_snapshot'] = 'file'

    def __post_init__(self):
        super().__post_init__()
        digest(self.sha256)
        for v in (self.source_id, self.framework, self.format_id):
            identifier(v)
        require(self.records_read >= 0 and self.edges_read >= 0, 'Negative import counts')


@record('memfolder.loading.report')
class LoadReport(Contract):
    sources: tuple[SourceInfo, ...]
    samples_loaded: int
    records_loaded: int
    edges_loaded: int
    eligible_records: int
    records_filtered: int = 0
    edges_filtered: int = 0
    issues: tuple[ImportIssue, ...] = ()

    def __post_init__(self):
        super().__post_init__()
        require(len({s.source_id for s in self.sources}) == len(self.sources), 'Duplicate import source labels')
        require(all(v >= 0 for v in (self.samples_loaded, self.records_loaded, self.edges_loaded,
                    self.eligible_records, self.records_filtered, self.edges_filtered)), 'Negative report counts')
        require(self.eligible_records <= self.records_loaded, 'Invalid eligible count')
        require(sum(s.records_read for s in self.sources) == self.records_loaded + self.records_filtered,
                'Import node counts do not reconcile')
        require(sum(s.edges_read for s in self.sources) == self.edges_loaded + self.edges_filtered,
                'Import edge counts do not reconcile')


@record('memfolder.loading.library')
class LoadedLibrary(Contract):
    inputs: tuple[MemoryInput, ...]
    report: LoadReport

    def __post_init__(self):
        super().__post_init__()
        require(all(i.initial_snapshot is not None for i in self.inputs), 'Imported input needs a snapshot')
        require(len({i.sample.identity for i in self.inputs}) == len(self.inputs), 'Duplicate imported samples')
        snapshots = [i.initial_snapshot for i in self.inputs]
        require(len(snapshots) == self.report.samples_loaded, 'Report sample count mismatch')
        require(sum(len(s.records) for s in snapshots) == self.report.records_loaded, 'Report record count mismatch')
        require(sum(len(s.edges) for s in snapshots) == self.report.edges_loaded, 'Report edge count mismatch')
        require(sum(n.eligible for s in snapshots for n in s.records) == self.report.eligible_records,
                'Report eligible count mismatch')


class ImportObserver(Protocol):
    """Read-only, immutable, memory-only analysis hooks after complete validation."""
    def on_input(self, memory: MemoryInput) -> None: ...
    def on_report(self, report: LoadReport) -> None: ...


class MemoryLibraryLoader(Protocol):
    spec: PluginSpec
    def load(self, *, observer: ImportObserver | None = None) -> LoadedLibrary: ...


@dataclass(frozen=True, kw_only=True)
class NativeRecord:
    """Adapter output; transports do not depend on memory-framework semantics."""
    native_id: str
    namespace: str
    sample_key: str
    partition_key: str
    parts: tuple[ContentPart, ...]
    native: FrozenMap
    selectors: FrozenMap = field(default_factory=FrozenMap)
    vectors: FrozenMap = field(default_factory=FrozenMap)
    kind: str = 'memory'
    eligible: bool = True
    retention: RetentionPolicy = RetentionPolicy()
    time_ranges: tuple[TimeRange, ...] = ()
    available_at: TimePoint | None = None
    expires_at: TimePoint | None = None
    revision: str = '0'
    extensions: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self):
        for v in (self.native_id, self.namespace, self.sample_key, self.partition_key, self.kind, self.revision):
            identifier(v)
        require(type(self.eligible) is bool and type(self.retention) is RetentionPolicy, 'Invalid native retention')
        require(isinstance(self.parts, (tuple, list)) and all(type(p) is ContentPart for p in self.parts), 'Invalid native content')
        require(isinstance(self.time_ranges, (tuple, list)) and all(type(t) is TimeRange for t in self.time_ranges), 'Invalid native times')
        require(all(t is None or type(t) is TimePoint for t in (self.available_at, self.expires_at)), 'Invalid native visibility')
        object.__setattr__(self, 'parts', tuple(self.parts))
        object.__setattr__(self, 'time_ranges', tuple(self.time_ranges))
        for name in ('native', 'selectors', 'vectors', 'extensions'):
            object.__setattr__(self, name, FrozenMap(getattr(self, name)))
        for vectors in self.vectors.values():
            require(isinstance(vectors, tuple), 'Native vector set must be an array of vectors')
            for vector in vectors:
                require(isinstance(vector, tuple) and bool(vector), 'Invalid native vector')
                for n in vector:
                    require(type(n) in (int, float), 'Invalid native vector number')
                    try:
                        finite = math.isfinite(n)
                    except OverflowError:
                        finite = False
                    require(finite, 'Nonfinite native vector')
            require(len({len(v) for v in vectors}) <= 1, 'Mixed dimensions within native vector slot')


@dataclass(frozen=True, kw_only=True)
class NativeEdge:
    source_namespace: str
    source_id: str
    target_namespace: str
    target_id: str
    relation: str
    weight: float = 1.0
    directed: bool = True
    native_id: str | None = None
    native: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self):
        for v in (self.source_namespace, self.source_id, self.target_namespace, self.target_id, self.relation):
            identifier(v)
        require(type(self.directed) is bool, 'Invalid edge direction')
        require(type(self.weight) in (int, float), 'Invalid edge weight')
        require(math.isfinite(self.weight), 'Nonfinite edge weight')
        require(self.native_id is None or type(self.native_id) is str and bool(self.native_id), 'Invalid native edge ID')
        object.__setattr__(self, 'native', FrozenMap(self.native))


@dataclass(frozen=True, kw_only=True)
class NativeLibrary:
    framework: str
    format_id: str
    records: tuple[NativeRecord, ...]
    edges: tuple[NativeEdge, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    coverage: Literal['declared_complete', 'partial', 'unknown'] = 'unknown'
    issues: tuple[ImportIssue, ...] = ()

    def __post_init__(self):
        identifier(self.framework)
        identifier(self.format_id)
        require(self.coverage in ('declared_complete', 'partial', 'unknown'), 'Invalid native coverage')
        for name, cls in (('records', NativeRecord), ('edges', NativeEdge), ('issues', ImportIssue)):
            value = getattr(self, name)
            require(isinstance(value, (tuple, list)) and all(type(v) is cls for v in value), 'Invalid native library values')
            object.__setattr__(self, name, tuple(value))
        object.__setattr__(self, 'metadata', FrozenMap(self.metadata))


class FormatAdapter(Protocol):
    framework: str
    format_id: str
    def decode(self, data: object, *, options: LoadOptions, source_id: str) -> NativeLibrary: ...
