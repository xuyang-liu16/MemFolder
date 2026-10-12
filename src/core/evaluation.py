"""Retrieval, prediction and metrics link through public memory identities."""
from __future__ import annotations
from .data import SampleRef
from .memory import ArtifactRef, ContentPart, OriginRef
from .values import Contract, FrozenMap, identifier, record, require


@record('memfolder.retrieval_hit')
class RetrievalHit(Contract):
    node_id: str
    rank: int
    origins: tuple[OriginRef, ...]
    score: float | None = None
    backend_id: str | None = None
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.node_id)
        require(self.rank >= 1, 'Retrieval rank is one-based')


@record('memfolder.prediction')
class Prediction(Contract):
    question_id: str
    sample: SampleRef
    answer: tuple[ContentPart, ...]
    retrieval: tuple[RetrievalHit, ...] = ()
    reader_context: ArtifactRef | None = None
    usage: FrozenMap = FrozenMap()
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.question_id)
        require(len({h.rank for h in self.retrieval}) == len(self.retrieval), 'Duplicate retrieval ranks')
        require(all((o.scope.dataset_id, o.scope.sample_id) == (self.sample.dataset_id, self.sample.sample_id)
                    for h in self.retrieval for o in h.origins), 'Retrieval origins mix samples')


@record('memfolder.metric_result')
class MetricResult(Contract):
    name: str
    version: str
    value: float | None
    status: str = 'measured'  # measured/not_run/failed; distinguish absent quality from zero
    unit: str | None = None
    question_id: str | None = None
    details: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.name)
        identifier(self.version)
        require(self.status in {'measured', 'not_run', 'failed'}, 'Unknown metric status')
        require((self.status == 'measured') == (self.value is not None), 'Metric value/status mismatch')


@record('memfolder.evaluation_report')
class EvaluationReport(Contract):
    sample: SampleRef
    protocol_id: str
    predictions: tuple[Prediction, ...]
    metrics: tuple[MetricResult, ...]
    artifacts: tuple[ArtifactRef, ...] = ()
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.protocol_id)
        require(all(p.sample.identity == self.sample.identity for p in self.predictions), 'Prediction sample mismatch')
        require(len({p.question_id for p in self.predictions}) == len(self.predictions), 'Duplicate predictions')
