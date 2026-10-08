"""Read-only observation DTOs/protocols; the runtime lives outside core."""
from __future__ import annotations
from pathlib import Path
from typing import Iterator, Literal, Protocol
from .data import SampleRef
from .memory import ArtifactRef, OriginRef, ScopeRef, Snapshot
from .values import Contract, FrozenMap, identifier, record, require, to_data


@record('memfolder.diagnostic_links')
class DiagnosticLinks(Contract):
    node_ids: tuple[str, ...] = ()
    origins: tuple[OriginRef, ...] = ()
    action_ids: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()
    question_ids: tuple[str, ...] = ()


@record('memfolder.diagnostic')
class DiagnosticRecord(Contract):
    schema: str
    version: int
    component_id: str
    links: DiagnosticLinks = DiagnosticLinks()
    data: FrozenMap = FrozenMap()
    artifacts: tuple[ArtifactRef, ...] = ()

    def __post_init__(self):
        super().__post_init__()
        require('.' in self.schema and self.version >= 1, 'Diagnostic schema needs namespace and version')
        identifier(self.component_id)


@record('memfolder.event')
class EventEnvelope(Contract):
    event_id: str
    run_id: str
    sequence: int
    name: str
    stage: str
    phase: Literal['started', 'completed', 'validated', 'failed', 'diagnostic']
    span_id: str
    monotonic_ns: int
    sample: SampleRef | None = None
    scope: ScopeRef | None = None
    round_index: int | None = None
    parent_span_id: str | None = None
    action_id: str | None = None
    question_id: str | None = None
    component_id: str | None = None
    artifact_refs: tuple[ArtifactRef, ...] = ()
    summary: FrozenMap = FrozenMap()
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        for v in (self.event_id, self.run_id, self.name, self.stage, self.span_id):
            identifier(v)
        require('.' in self.name, 'Event names need a namespace')
        require(self.sequence >= 0 and self.monotonic_ns >= 0, 'Negative event sequence/time')
        require(self.round_index is None or self.round_index >= 0, 'Negative round index')
        require(all(v is None or type(v) in (str, bool, int, float) for v in self.summary.values()), 'Event summary only accepts scalar allowlisted fields')
        if self.scope is not None:
            require(self.sample is not None and (self.scope.dataset_id, self.scope.sample_id)
                    == (self.sample.dataset_id, self.sample.sample_id), 'Event scope/sample mismatch')


@record('memfolder.capture_policy')
class CapturePolicy(Contract):
    profile: Literal['off', 'summary', 'cases', 'full'] = 'off'
    sample_ids: tuple[str, ...] = ()
    scopes: tuple[ScopeRef, ...] = ()
    stages: tuple[str, ...] = ()
    diagnostic_schemas: tuple[str, ...] = ()
    text_policy: Literal['omit', 'redacted', 'selected', 'full'] = 'omit'
    vector_policy: Literal['omit', 'metadata', 'selected', 'full'] = 'metadata'
    extensions: FrozenMap = FrozenMap()


@record('memfolder.trace_coverage')
class TraceCoverage(Contract):
    capture: CapturePolicy
    complete_for_capture: bool
    events_written: int = 0
    events_dropped: int = 0
    missing_artifacts: tuple[str, ...] = ()
    missing_stages: tuple[str, ...] = ()

    def __post_init__(self):
        super().__post_init__()
        require(self.events_written >= 0 and self.events_dropped >= 0, 'Negative trace counts')
        require(not self.complete_for_capture or (self.events_dropped == 0 and not self.missing_artifacts
                    and not self.missing_stages), 'Incomplete trace cannot claim complete coverage')


@record('memfolder.case_view')
class CaseView(Contract):
    run_id: str
    sample: SampleRef
    origins: tuple[OriginRef, ...]
    coverage: TraceCoverage
    events: tuple[EventEnvelope, ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()
    status: Literal['complete_for_capture', 'partial', 'not_recorded'] = 'partial'
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.run_id)
        require(all(e.run_id == self.run_id and (e.sample is None or e.sample.identity == self.sample.identity) for e in self.events), 'Case events mix runs/samples')
        require(all((o.scope.dataset_id, o.scope.sample_id) == (self.sample.dataset_id, self.sample.sample_id)
                    for o in self.origins), 'Case origins mix samples')
        require(self.status != 'complete_for_capture' or self.coverage.complete_for_capture, 'Case coverage is incomplete')


@record('memfolder.run_comparison')
class RunComparison(Contract):
    left: CaseView
    right: CaseView
    alignment: Literal['matched', 'incomparable', 'partial']
    protocol_differences: tuple[str, ...] = ()
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        if self.alignment == 'matched':
            require(self.left.sample.identity == self.right.sample.identity and set(self.left.origins) == set(self.right.origins), 'Matched cases must share original data identity')


class ArtifactReader(Protocol):
    def read_json(self, ref: ArtifactRef) -> FrozenMap: ...
    def iter_rows(self, ref: ArtifactRef) -> Iterator[FrozenMap]: ...
    def verify(self, ref: ArtifactRef) -> bool: ...


class ReportWriter(Protocol):
    def write_json(self, name: str, value: FrozenMap) -> Path: ...


class ObservationContext(Protocol):
    @property
    def run_id(self) -> str: ...
    @property
    def artifacts(self) -> ArtifactReader: ...
    @property
    def reports(self) -> ReportWriter: ...


class Observer(Protocol):
    def open(self, context: ObservationContext) -> None: ...
    def on_event(self, event: EventEnvelope, context: ObservationContext) -> None: ...
    def close(self, context: ObservationContext) -> None: ...


class Diagnostics(Protocol):
    def enabled(self, schema: str) -> bool: ...
    def emit(self, record: DiagnosticRecord) -> None: ...


class NullDiagnostics:
    """Avoid formatting diagnostics when disabled; never skip algorithm work."""
    def enabled(self, schema: str) -> bool:
        return False

    def emit(self, record: DiagnosticRecord) -> None:
        return None


class RunReader(Protocol):
    def by_origin(self, origin: OriginRef) -> CaseView: ...
    def by_action(self, sample: SampleRef, action_id: str) -> CaseView: ...
    def by_question(self, sample: SampleRef, question_id: str) -> CaseView: ...
    def compare(self, other: RunReader, origins: tuple[OriginRef, ...]) -> RunComparison: ...


def project_snapshot(snapshot: Snapshot, *, include_text: bool = False) -> FrozenMap:
    """An explicit observation projection, never a dump of native payload/config.

    This is a trusted in-process API, not a sandbox or a redaction engine.
    Richer content exports require an explicit capture policy in the runtime.
    """
    return FrozenMap({'snapshot_id': snapshot.snapshot_id, 'revision': snapshot.revision,
        'fingerprint': snapshot.fingerprint,
        'nodes': [{'node_id': n.node_id, 'scope': to_data(n.scope), 'kind': n.kind,
                   'origins': to_data(n.origins), 'content_fingerprint': n.content_fingerprint,
                   'text': n.text if include_text else None,
                   'embedding_spaces': [to_data(e.space) for e in n.embeddings]} for n in snapshot.records],
        'edges': [{'edge_id': e.edge_id, 'source_id': e.source_id, 'target_id': e.target_id,
                   'relation': e.relation, 'weight': e.weight, 'directed': e.directed} for e in snapshot.edges]})


@record('memfolder.plugin_binding')
class PluginBinding(Contract):
    plugin_id: str
    role: str
    api_version: int
    implementation_revision: str
    parameters_fingerprint: str  # only fingerprint, no raw configuration in manifest

    def __post_init__(self):
        super().__post_init__()
        from .values import digest
        for v in (self.plugin_id, self.role, self.implementation_revision):
            identifier(v)
        require(self.api_version >= 1, 'Invalid binding API version')
        digest(self.parameters_fingerprint)


@record('memfolder.run_manifest')
class RunManifest(Contract):
    run_id: str
    config_fingerprint: str
    samples: tuple[SampleRef, ...]
    bindings: tuple[PluginBinding, ...]
    seed: int
    mode: Literal['once', 'repeat', 'stream']
    compression_status: Literal['pending', 'running', 'completed', 'failed']
    evaluation_status: Literal['pending', 'running', 'completed', 'not_run', 'failed']
    observation_status: Literal['off', 'recording', 'complete', 'incomplete', 'failed']
    coverage: TraceCoverage | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        from .values import digest
        identifier(self.run_id)
        digest(self.config_fingerprint)
        require(self.observation_status != 'complete' or
                (self.coverage is not None and self.coverage.complete_for_capture), 'Complete observation requires coverage evidence')
