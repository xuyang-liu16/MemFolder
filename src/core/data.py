"""Benchmark inputs and evaluator-only questions are separate value types."""
from __future__ import annotations
from .memory import ArtifactRef, ContentPart, OriginRef, ScopeRef, Snapshot, TimePoint
from .values import Contract, FrozenMap, digest, identifier, record, require


@record('memfolder.sample_ref')
class SampleRef(Contract):
    dataset_id: str
    sample_id: str
    split: str
    dataset_fingerprint: str
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        for v in (self.dataset_id, self.sample_id, self.split):
            identifier(v)
        digest(self.dataset_fingerprint)

    @property
    def identity(self):
        return (self.dataset_id, self.sample_id, self.split, self.dataset_fingerprint)


@record('memfolder.history_event')
class HistoryEvent(Contract):
    event_id: str
    scope: ScopeRef
    sequence: int
    parts: tuple[ContentPart, ...]
    occurred_at: TimePoint | None = None
    speaker: str | None = None
    native: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.event_id)
        require(self.sequence >= 0 and bool(self.parts), 'Invalid history event')


@record('memfolder.memory_input')
class MemoryInput(Contract):
    sample: SampleRef
    history: tuple[HistoryEvent, ...] = ()
    history_artifact: ArtifactRef | None = None
    initial_snapshot: Snapshot | None = None
    assets: tuple[ArtifactRef, ...] = ()

    def __post_init__(self):
        super().__post_init__()
        require(not (self.history and self.history_artifact), 'Choose inline or external history')
        require(len({e.event_id for e in self.history}) == len(self.history), 'Duplicate history IDs')
        identities = [(e.scope.dataset_id, e.scope.sample_id) for e in self.history]
        if self.initial_snapshot:
            identities += [(n.scope.dataset_id, n.scope.sample_id) for n in self.initial_snapshot.records]
        require(all(i == (self.sample.dataset_id, self.sample.sample_id) for i in identities), 'Memory input mixes samples')


@record('memfolder.evaluation_case')
class EvaluationCase(Contract):
    question_id: str
    sample: SampleRef
    question: tuple[ContentPart, ...]
    ground_truth: FrozenMap  # free shape for QA, MC, abstention, evidence, categories
    options: FrozenMap = FrozenMap()  # public answer choices, separate from labels
    as_of: TimePoint | None = None
    evidence: tuple[OriginRef, ...] = ()
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.question_id)
        require(bool(self.question), 'Question cannot be empty')
        require(all((o.scope.dataset_id, o.scope.sample_id) == (self.sample.dataset_id, self.sample.sample_id)
                    for o in self.evidence), 'Evidence mixes samples')


@record('memfolder.evaluation_set')
class EvaluationSet(Contract):
    sample: SampleRef
    cases: tuple[EvaluationCase, ...]
    protocol_id: str
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.protocol_id)
        require(len({q.question_id for q in self.cases}) == len(self.cases), 'Duplicate question IDs')
        require(all(q.sample.identity == self.sample.identity for q in self.cases), 'Evaluation set mixes samples')

    def reader_input(self) -> QuestionSet:
        return QuestionSet(sample=self.sample, protocol_id=self.protocol_id,
            questions=tuple(Question(question_id=q.question_id, sample=q.sample,
                                     parts=q.question, options=q.options, as_of=q.as_of) for q in self.cases))


@record('memfolder.question')
class Question(Contract):
    question_id: str
    sample: SampleRef
    parts: tuple[ContentPart, ...]
    options: FrozenMap = FrozenMap()
    as_of: TimePoint | None = None

    def __post_init__(self):
        super().__post_init__()
        identifier(self.question_id)
        require(bool(self.parts), 'Empty reader question')


@record('memfolder.question_set')
class QuestionSet(Contract):
    sample: SampleRef
    questions: tuple[Question, ...]
    protocol_id: str

    def __post_init__(self):
        super().__post_init__()
        identifier(self.protocol_id)
        require(all(q.sample.identity == self.sample.identity for q in self.questions), 'Reader questions mix samples')
        require(len({q.question_id for q in self.questions}) == len(self.questions), 'Duplicate reader question IDs')


@record('memfolder.dataset_sample')
class DatasetSample(Contract):
    memory: MemoryInput
    evaluation: EvaluationSet

    def __post_init__(self):
        super().__post_init__()
        require(self.memory.sample.identity == self.evaluation.sample.identity, 'Memory/evaluation sample mismatch')
