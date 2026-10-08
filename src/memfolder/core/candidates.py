"""Optional fine-grained planner contracts; whole planners need not use them."""
from __future__ import annotations
from typing import Literal
from .memory import Snapshot
from .values import Contract, FrozenMap, digest, fingerprint, identifier, record, require


@record('memfolder.candidate')
class Candidate(Contract):
    candidate_id: str
    source_id: str
    target_id: str
    directed: bool = True
    values: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        for v in (self.candidate_id, self.source_id, self.target_id):
            identifier(v)


@record('memfolder.candidate_batch')
class CandidateBatch(Contract):
    input_fingerprint: str
    candidates: tuple[Candidate, ...]
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        digest(self.input_fingerprint)
        require(len({c.candidate_id for c in self.candidates}) == len(self.candidates), 'Duplicate candidate IDs')


@record('memfolder.candidate_score')
class CandidateScore(Contract):
    candidate_id: str
    value: float
    components: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.candidate_id)


@record('memfolder.score_batch')
class ScoreBatch(Contract):
    candidate_fingerprint: str
    scores: tuple[CandidateScore, ...]
    preference: Literal['maximize', 'minimize'] = 'maximize'
    complete: bool = True
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        digest(self.candidate_fingerprint)
        require(len({s.candidate_id for s in self.scores}) == len(self.scores), 'Duplicate candidate scores')


@record('memfolder.gate_decision')
class GateDecision(Contract):
    candidate_id: str
    accepted: bool
    reason_codes: tuple[str, ...]
    thresholds: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.candidate_id)
        require(bool(self.reason_codes), 'Gate decision needs an explicit reason')


@record('memfolder.gate_batch')
class GateBatch(Contract):
    score_fingerprint: str
    decisions: tuple[GateDecision, ...]
    complete: bool = True
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        digest(self.score_fingerprint)
        require(len({d.candidate_id for d in self.decisions}) == len(self.decisions), 'Duplicate gate decisions')


@record('memfolder.candidate_selection')
class CandidateSelection(Contract):
    candidate_fingerprint: str
    selected_ids: tuple[str, ...]
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        digest(self.candidate_fingerprint)
        require(len(set(self.selected_ids)) == len(self.selected_ids), 'Duplicate selected candidates')


def validate_candidates(snapshot: Snapshot, batch: CandidateBatch) -> None:
    require(snapshot.fingerprint == batch.input_fingerprint, 'Stale candidate batch')
    nodes = {n.node_id for n in snapshot.records}
    require(all(c.source_id in nodes and c.target_id in nodes for c in batch.candidates), 'Unknown candidate endpoints')


def validate_scores(candidates: CandidateBatch, scores: ScoreBatch) -> None:
    require(scores.candidate_fingerprint == fingerprint(candidates), 'Scores use different candidates')
    expected = {c.candidate_id for c in candidates.candidates}
    ids = {s.candidate_id for s in scores.scores}
    require(ids <= expected and (not scores.complete or ids == expected), 'Missing/unknown candidate scores')


def validate_gates(scores: ScoreBatch, gates: GateBatch) -> None:
    require(gates.score_fingerprint == fingerprint(scores), 'Gates use different scores')
    expected = {s.candidate_id for s in scores.scores}
    ids = {d.candidate_id for d in gates.decisions}
    require(ids <= expected and (not gates.complete or ids == expected), 'Missing/unknown gate decisions')


def validate_selection(candidates: CandidateBatch, selection: CandidateSelection) -> None:
    require(selection.candidate_fingerprint == fingerprint(candidates), 'Selection uses different candidates')
    require(set(selection.selected_ids) <= {c.candidate_id for c in candidates.candidates}, 'Unknown selected candidates')
