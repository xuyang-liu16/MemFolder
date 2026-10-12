"""Contributor example: a new gate module uses public contracts only."""
from memfolder.core import (AlgorithmContext, Contract, DiagnosticLinks, DiagnosticRecord,
    FrozenMap, GateBatch, GateDecision, PlanningRequest, PluginSpec, ScoreBatch,
    fingerprint, record)


@record('example.threshold_parameters')
class Parameters(Contract):
    threshold: float


class ThresholdGate:
    spec = PluginSpec(plugin_id='example.threshold', role='gate',
                      execution_modes=('once', 'repeat', 'stream'),
                      diagnostic_schemas=('example.threshold_decision',))

    def __init__(self, threshold: float = .7):
        self.parameters = Parameters(threshold=threshold)

    def decide(self, request: PlanningRequest, scores: ScoreBatch,
               context: AlgorithmContext) -> GateBatch:
        decisions = tuple(GateDecision(candidate_id=s.candidate_id,
            accepted=(s.value >= self.parameters.threshold if scores.preference == 'maximize'
                      else s.value <= self.parameters.threshold),
            reason_codes=('threshold_comparison',),
            thresholds=FrozenMap({'threshold': self.parameters.threshold})) for s in scores.scores)
        result = GateBatch(score_fingerprint=fingerprint(scores), decisions=decisions)
        if context.diagnostics.enabled('example.threshold_decision'):
            context.diagnostics.emit(DiagnosticRecord(schema='example.threshold_decision', version=1,
                component_id=self.spec.plugin_id,
                links=DiagnosticLinks(candidate_ids=tuple(d.candidate_id for d in decisions)),
                data=FrozenMap({'accepted': [d.candidate_id for d in decisions if d.accepted]})))
        return result
