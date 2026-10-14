"""Structural plugin interfaces and capability negotiation, with no plugin loader."""
from __future__ import annotations
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Iterator, Protocol
from .budgets import ResolvedBudget
from .candidates import CandidateBatch, CandidateSelection, GateBatch, ScoreBatch
from .data import DatasetSample, EvaluationSet, MemoryInput, QuestionSet
from .evaluation import EvaluationReport, Prediction
from .features import AlgorithmState, FeatureBatch
from .memory import ArtifactRef, MemoryDelta, MemoryRecord, OriginRef, Snapshot
from .observation import Diagnostics
from .plans import ActionPlan, OperatorResult
from .values import Contract, FrozenMap, identifier, record, require


@record('memfolder.plugin_spec')
class PluginSpec(Contract):
    plugin_id: str
    role: str  # open role names for future components
    api_version: int = 1
    requires: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    action_kinds: tuple[str, ...] = ()
    execution_modes: tuple[str, ...] = ()
    diagnostic_schemas: tuple[str, ...] = ()
    parameters: FrozenMap = FrozenMap()
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.plugin_id)
        identifier(self.role)
        require(self.api_version >= 1, 'Invalid plugin API version')
        for items in (self.requires, self.provides, self.action_kinds, self.execution_modes, self.diagnostic_schemas):
            require(len(set(items)) == len(items), 'Duplicate plugin declarations')
            for item in items:
                identifier(item)


def validate_capabilities(spec: PluginSpec, available: tuple[str, ...], *, api_version: int = 1) -> None:
    require(spec.api_version == api_version, 'Incompatible plugin API version')
    require(set(spec.requires) <= set(available), f'Missing capabilities: {set(spec.requires) - set(available)}')


def validate_composition(planner: PluginSpec, operators: tuple[PluginSpec, ...], *, mode: str, available: tuple[str, ...]) -> None:
    require(planner.role == 'planner' and all(o.role == 'operator' for o in operators), 'Wrong composition roles')
    require(bool(operators), 'Composition needs operators')
    for spec in (planner, *operators):
        validate_capabilities(spec, available)
        require(mode in spec.execution_modes, f'{spec.plugin_id} does not support {mode}')
    supported = {kind for o in operators for kind in o.action_kinds}
    require(set(planner.action_kinds) <= supported, 'Planner produces unsupported actions')


@record('memfolder.planning_request')
class PlanningRequest(Contract):
    """Serializable algorithm input. No benchmark questions or answers."""
    run_id: str
    snapshot: Snapshot
    budgets: tuple[ResolvedBudget, ...] = ()
    features: tuple[FeatureBatch, ...] = ()
    round_index: int = 0
    seed: int = 0
    mode: str = 'once'
    state: AlgorithmState | None = None
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.run_id)
        require(self.round_index >= 0 and self.mode in {'once', 'repeat', 'stream'}, 'Invalid execution context')
        from .features import validate_features
        for feature in self.features:
            validate_features(self.snapshot, feature)
        # Initial budgets intentionally survive successive snapshot revisions.
        for budget in self.budgets:
            if budget.request.reference == 'current':
                require(budget.reference_fingerprint == self.snapshot.fingerprint, 'Stale current-state budget')


class Services(Protocol):
    def require(self, service_id: str) -> object: ...


@dataclass(frozen=True, kw_only=True)
class AlgorithmContext:
    """Live services are never serialized or forwarded into observer context."""
    services: Services
    diagnostics: Diagnostics


class OriginalMemoryReader(Protocol):
    def get(self, origin: OriginRef) -> MemoryRecord: ...


@dataclass(frozen=True, kw_only=True)
class OperatorContext:
    services: Services
    diagnostics: Diagnostics
    originals: OriginalMemoryReader


@record('memfolder.planning_result')
class PlanningResult(Contract):
    plan: ActionPlan
    next_state: AlgorithmState | None = None
    diagnostics: tuple[ArtifactRef, ...] = ()


@record('memfolder.materialized_view')
class MaterializedView(Contract):
    framework_id: str
    snapshot: Snapshot
    artifact: ArtifactRef
    node_id_map: FrozenMap
    reader_capabilities: tuple[str, ...] = ()
    timestamp_policy: str | None = None

    def __post_init__(self):
        super().__post_init__()
        identifier(self.framework_id)
        require(self.timestamp_policy in (None, 'anchor', 'earliest', 'latest'), 'Unknown materialized timestamp policy')
        require(set(self.node_id_map) == {n.node_id for n in self.snapshot.records}, 'Backend node map must cover all records')


class DataLoader(Protocol):
    spec: PluginSpec
    def samples(self) -> Iterator[DatasetSample] | AsyncIterator[DatasetSample]: ...


class MemoryInitializer(Protocol):
    spec: PluginSpec
    def initialize(self, source: MemoryInput, context: AlgorithmContext) -> MemoryInput | Awaitable[MemoryInput]: ...


class Retriever(Protocol):
    spec: PluginSpec
    def retrieve(self, question, view: MaterializedView, context: AlgorithmContext): ...


class ContextBuilder(Protocol):
    spec: PluginSpec
    def build(self, question, view: MaterializedView, retrieval, context: AlgorithmContext): ...


class Answerer(Protocol):
    spec: PluginSpec
    def answer(self, question, memory_context, context: AlgorithmContext): ...


class Metric(Protocol):
    spec: PluginSpec
    def score(self, case, prediction, context: AlgorithmContext): ...


class MemoryWrapper(Protocol):
    spec: PluginSpec
    def export(self, source: MemoryInput, context: AlgorithmContext) -> Snapshot | Awaitable[Snapshot]: ...
    def project(self, source: Snapshot, plan: ActionPlan, result: OperatorResult,
                context: AlgorithmContext) -> Snapshot | Awaitable[Snapshot]: ...
    def materialize(self, snapshot: Snapshot, context: AlgorithmContext) -> MaterializedView | Awaitable[MaterializedView]: ...


class StreamingMemoryWrapper(MemoryWrapper, Protocol):
    def ingest(self, source: MemoryInput, snapshot: Snapshot,
               context: AlgorithmContext) -> MemoryDelta | Awaitable[MemoryDelta]: ...


class Planner(Protocol):
    spec: PluginSpec
    def plan(self, request: PlanningRequest, context: AlgorithmContext) -> PlanningResult | Awaitable[PlanningResult]: ...


class Operator(Protocol):
    spec: PluginSpec
    def apply(self, snapshot: Snapshot, plan: ActionPlan, context: OperatorContext) -> OperatorResult | Awaitable[OperatorResult]: ...


class FeatureProvider(Protocol):
    spec: PluginSpec
    def extract(self, snapshot: Snapshot, context: AlgorithmContext) -> FeatureBatch | Awaitable[FeatureBatch]: ...


class CandidateGenerator(Protocol):
    spec: PluginSpec
    def generate(self, request: PlanningRequest, context: AlgorithmContext) -> CandidateBatch | Awaitable[CandidateBatch]: ...


class AffinityScorer(Protocol):
    spec: PluginSpec
    def score(self, request: PlanningRequest, candidates: CandidateBatch, context: AlgorithmContext) -> ScoreBatch | Awaitable[ScoreBatch]: ...


class GatePolicy(Protocol):
    spec: PluginSpec
    def decide(self, request: PlanningRequest, scores: ScoreBatch, context: AlgorithmContext) -> GateBatch | Awaitable[GateBatch]: ...


class Matcher(Protocol):
    spec: PluginSpec
    def match(self, request: PlanningRequest, candidates: CandidateBatch, scores: ScoreBatch,
              gates: GateBatch, context: AlgorithmContext) -> CandidateSelection | Awaitable[CandidateSelection]: ...


class EmbeddingProvider(Protocol):
    spec: PluginSpec
    def refresh(self, snapshot: Snapshot, context: AlgorithmContext) -> Snapshot | Awaitable[Snapshot]: ...


class Reader(Protocol):
    spec: PluginSpec
    def predict(self, questions: QuestionSet, memory: MaterializedView,
                context: AlgorithmContext) -> tuple[Prediction, ...] | Awaitable[tuple[Prediction, ...]]: ...


class Evaluator(Protocol):
    spec: PluginSpec
    def evaluate(self, questions: EvaluationSet, predictions: tuple[Prediction, ...],
                 context: AlgorithmContext) -> EvaluationReport | Awaitable[EvaluationReport]: ...
