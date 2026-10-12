"""Algorithm features and reusable streaming state, independent of stored embeddings."""
from __future__ import annotations
from .memory import ArtifactRef, EmbeddingSpace, Snapshot
from .values import Contract, FrozenMap, digest, identifier, record, require


@record('memfolder.feature_row')
class FeatureRow(Contract):
    node_id: str
    vector: tuple[float, ...] = ()
    mass: float = 1.0
    values: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.node_id)
        require(self.mass > 0, 'Feature mass must be positive')


@record('memfolder.feature_batch')
class FeatureBatch(Contract):
    name: str
    input_fingerprint: str
    rows: tuple[FeatureRow, ...]
    space: EmbeddingSpace | None = None
    vector_semantics: str = 'encoded'  # encoded/pooled/custom algorithm features
    artifact: ArtifactRef | None = None
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.name)
        identifier(self.vector_semantics)
        digest(self.input_fingerprint)
        require(len({r.node_id for r in self.rows}) == len(self.rows), 'Duplicate feature node IDs')
        if self.space is None:
            require(not any(r.vector for r in self.rows), 'Inline vectors require a declared space')
        else:
            require(all(len(r.vector) == self.space.dimension for r in self.rows) or
                    (self.artifact is not None and not any(r.vector for r in self.rows)), 'Feature dimensions mismatch')


def validate_features(snapshot: Snapshot, features: FeatureBatch, *, required_ids: tuple[str, ...] = ()) -> None:
    require(snapshot.fingerprint == features.input_fingerprint, 'Stale feature batch')
    ids = {n.node_id for n in snapshot.records}
    row_ids = {r.node_id for r in features.rows}
    require(row_ids <= ids and set(required_ids) <= row_ids, 'Missing/unknown feature rows')


@record('memfolder.algorithm_state')
class AlgorithmState(Contract):
    schema: str  # method-owned, versioned state; core never understands its internals
    version: int
    data: FrozenMap = FrozenMap()
    artifacts: tuple[ArtifactRef, ...] = ()

    def __post_init__(self):
        super().__post_init__()
        require('.' in self.schema and self.version >= 1, 'State requires namespaced schema and positive version')
