"""Backend-neutral text, multimodal memory, graph topology, and lineage."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from functools import cached_property
from typing import Literal
from .values import Contract, FrozenMap, digest, fingerprint, identifier, record, require


@record('memfolder.scope')
class ScopeRef(Contract):
    dataset_id: str
    sample_id: str
    partition_id: str

    def __post_init__(self):
        super().__post_init__()
        for value in (self.dataset_id, self.sample_id, self.partition_id):
            identifier(value, 'scope identity')


@record('memfolder.artifact_ref')
class ArtifactRef(Contract):
    artifact_id: str
    path: str
    sha256: str
    media_type: str
    schema_id: str
    record_count: int | None = None

    def __post_init__(self):
        super().__post_init__()
        for v in (self.artifact_id, self.media_type, self.schema_id):
            identifier(v)
        digest(self.sha256)
        p = PurePosixPath(self.path)
        require(bool(self.path) and not any(ord(c) < 32 for c in self.path)
                and '\\' not in self.path and ':' not in self.path and not p.is_absolute()
                and '..' not in p.parts and self.path == p.as_posix() and self.path != '.',
                'Artifact path must be canonical and relative to its artifact root')
        require(self.record_count is None or self.record_count >= 0, 'Negative record_count')

    def resolve(self, root: Path) -> Path:
        """Resolve existing symlinks too; readers separately verify file content."""
        base = root.resolve()
        result = (base / self.path).resolve()
        require(result.is_relative_to(base), 'Artifact escaped its root')
        return result


@record('memfolder.time_point')
class TimePoint(Contract):
    value: float
    clock: str  # unix_seconds, video:<id>:seconds, or an adapter-declared clock

    def __post_init__(self):
        super().__post_init__()
        identifier(self.clock, 'clock')


@record('memfolder.time_range')
class TimeRange(Contract):
    start: TimePoint
    end: TimePoint

    def __post_init__(self):
        super().__post_init__()
        require(self.start.clock == self.end.clock, 'Time range mixes clocks')
        require(self.start.value <= self.end.value, 'Time range is reversed')


@record('memfolder.content_part')
class ContentPart(Contract):
    modality: str  # open vocabulary: text/image/audio/video/tensor/structured/...
    text: str | None = None
    artifact: ArtifactRef | None = None
    data: FrozenMap = FrozenMap()
    time_range: TimeRange | None = None

    def __post_init__(self):
        super().__post_init__()
        identifier(self.modality, 'modality')
        require(self.text is not None or self.artifact is not None or bool(self.data), 'Empty content part')


@record('memfolder.origin')
class OriginRef(Contract):
    scope: ScopeRef
    source_id: str
    revision: str = '0'

    def __post_init__(self):
        super().__post_init__()
        identifier(self.source_id, 'source_id')
        identifier(self.revision, 'source revision')


@record('memfolder.retention')
class RetentionPolicy(Contract):
    may_drop: bool = True
    may_merge: bool = True
    may_rewrite: bool = True


@record('memfolder.embedding_space')
class EmbeddingSpace(Contract):
    provider: str
    model: str
    revision: str
    dimension: int
    metric: str = 'cosine'

    def __post_init__(self):
        super().__post_init__()
        for v in (self.provider, self.model, self.revision, self.metric):
            identifier(v)
        require(self.dimension > 0, 'Embedding dimension must be positive')


@record('memfolder.embedding')
class Embedding(Contract):
    space: EmbeddingSpace
    source_fingerprint: str  # the actual stored content, not pooled planner features
    values: tuple[float, ...] = ()
    artifact: ArtifactRef | None = None

    def __post_init__(self):
        super().__post_init__()
        digest(self.source_fingerprint, 'embedding source fingerprint')
        require(bool(self.values) != (self.artifact is not None), 'Choose inline vector or artifact')
        require(not self.values or len(self.values) == self.space.dimension, 'Embedding dimension mismatch')


@record('memfolder.memory_record')
class MemoryRecord(Contract):
    node_id: str  # unique in a snapshot, while origin identity includes dataset/sample/scope
    scope: ScopeRef
    order: int
    origins: tuple[OriginRef, ...]
    parts: tuple[ContentPart, ...] = ()
    kind: str = 'memory'
    eligible: bool = True
    retention: RetentionPolicy = RetentionPolicy()
    time_ranges: tuple[TimeRange, ...] = ()
    available_at: TimePoint | None = None
    expires_at: TimePoint | None = None
    embeddings: tuple[Embedding, ...] = ()
    native: FrozenMap = FrozenMap()  # detached payload/IDs; no handles or pickle objects
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.node_id, 'node_id')
        identifier(self.kind, 'node kind')
        require(bool(self.origins) and len(set(self.origins)) == len(self.origins), 'Origins must be nonempty and unique')
        require(all(o.scope.dataset_id == self.scope.dataset_id and o.scope.sample_id == self.scope.sample_id
                    for o in self.origins), 'Origins cannot cross dataset/sample boundaries')
        require(len({e.space for e in self.embeddings}) == len(self.embeddings), 'Duplicate embedding spaces')
        require(all(e.source_fingerprint == self.content_fingerprint for e in self.embeddings), 'Stale content embedding')
        if self.available_at is not None and self.expires_at is not None:
            require(self.available_at.clock == self.expires_at.clock, 'Visibility mixes clocks')
            require(self.available_at.value <= self.expires_at.value, 'Invalid visibility interval')

    @cached_property
    def content_fingerprint(self) -> str:
        return fingerprint(self.parts)

    @property
    def text(self) -> str:
        return '\n'.join(p.text for p in self.parts if p.text is not None)

    def visible_at(self, time: TimePoint) -> bool:
        for bound in (self.available_at, self.expires_at):
            require(bound is None or bound.clock == time.clock, 'Cannot compare different clocks')
        return ((self.available_at is None or time.value >= self.available_at.value)
                and (self.expires_at is None or time.value < self.expires_at.value))


@record('memfolder.graph_edge')
class GraphEdge(Contract):
    edge_id: str
    source_id: str
    target_id: str
    relation: str
    weight: float = 1.0
    directed: bool = True
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        for v in (self.edge_id, self.source_id, self.target_id, self.relation):
            identifier(v)


@record('memfolder.snapshot')
class Snapshot(Contract):
    snapshot_id: str
    records: tuple[MemoryRecord, ...]
    edges: tuple[GraphEdge, ...] = ()
    assets: tuple[ArtifactRef, ...] = ()
    revision: int = 0
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.snapshot_id)
        require(self.revision >= 0, 'Negative snapshot revision')
        ids = {n.node_id for n in self.records}
        require(len(ids) == len(self.records), 'Duplicate node IDs')
        require(len({e.edge_id for e in self.edges}) == len(self.edges), 'Duplicate edge IDs')
        require(all(e.source_id in ids and e.target_id in ids for e in self.edges), 'Dangling graph edge')
        require(len({a.artifact_id for a in self.assets}) == len(self.assets), 'Duplicate asset IDs')

    @cached_property
    def fingerprint(self) -> str:
        return fingerprint(self)


@record('memfolder.memory_delta')
class MemoryDelta(Contract):
    """Atomic stream/backend change. Edge deletion/rewiring is explicit."""
    delta_id: str
    base_fingerprint: str
    upserts: tuple[MemoryRecord, ...] = ()
    removed_ids: tuple[str, ...] = ()
    edge_upserts: tuple[GraphEdge, ...] = ()
    removed_edge_ids: tuple[str, ...] = ()
    watermark: TimePoint | None = None

    def __post_init__(self):
        super().__post_init__()
        identifier(self.delta_id)
        digest(self.base_fingerprint)
        require(len({n.node_id for n in self.upserts}) == len(self.upserts), 'Duplicate delta upserts')
        require(len(set(self.removed_ids)) == len(self.removed_ids), 'Duplicate delta removals')
        require(not set(self.removed_ids) & {n.node_id for n in self.upserts}, 'Conflicting node operations')
        require(len({e.edge_id for e in self.edge_upserts}) == len(self.edge_upserts), 'Duplicate edge upserts')
        require(len(set(self.removed_edge_ids)) == len(self.removed_edge_ids), 'Duplicate edge removals')
        require(not set(self.removed_edge_ids) & {e.edge_id for e in self.edge_upserts}, 'Conflicting edge operations')


def apply_delta(snapshot: Snapshot, delta: MemoryDelta) -> Snapshot:
    require(snapshot.fingerprint == delta.base_fingerprint, 'Stale memory delta')
    nodes = {n.node_id: n for n in snapshot.records}
    edges = {e.edge_id: e for e in snapshot.edges}
    require(set(delta.removed_ids) <= set(nodes), 'Removing unknown nodes')
    require(set(delta.removed_edge_ids) <= set(edges), 'Removing unknown edges')
    for nid in delta.removed_ids:
        del nodes[nid]
    for eid in delta.removed_edge_ids:
        del edges[eid]
    nodes.update({n.node_id: n for n in delta.upserts})
    edges.update({e.edge_id: e for e in delta.edge_upserts})
    return Snapshot(snapshot_id=snapshot.snapshot_id, revision=snapshot.revision + 1,
                    records=tuple(nodes.values()), edges=tuple(edges.values()),
                    assets=snapshot.assets, extensions=snapshot.extensions)
