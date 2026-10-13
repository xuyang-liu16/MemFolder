"""Extend planning with a recency selector and a score-threshold gate."""
from dataclasses import dataclass
from memfolder.core import (AlgorithmContext, Contract, ContractError, DiagnosticLinks,
    DiagnosticRecord, FrozenMap, GateBatch, GateDecision, PlanningRequest,
    PluginSpec, ScoreBatch, fingerprint, record)
from memfolder.planning import AnchorSelection, component_nodes, selection_required


@dataclass(frozen=True)
class RecencySelector:
    newest_first: bool = True
    spec = PluginSpec(plugin_id='example.recency', role='anchor_selector', api_version=1)

    async def select(self, request, target, context):
        nodes = component_nodes(request)
        required = tuple(n.node_id for n in selection_required(request, nodes))
        if not len(required) <= target <= len(nodes):
            raise ContractError('Recency target cannot preserve protected records')
        optional = sorted((n for n in nodes if n.node_id not in required),
            key=lambda n: (n.order, n.node_id), reverse=self.newest_first)
        return AnchorSelection(request.snapshot.fingerprint,
            required + tuple(n.node_id for n in optional[:target - len(required)]))


def build_recency_selector(parameters, *, context):
    if set(parameters) - {'newest_first'}:
        raise ContractError('Unknown recency parameter')
    value = parameters.get('newest_first', True)
    if type(value) is not bool:
        raise ContractError('newest_first must be boolean')
    return RecencySelector(value)


build_recency_selector.spec = RecencySelector.spec


@record('example.threshold_parameters')
class ThresholdParameters(Contract):
    threshold: float


class ThresholdGate:
    spec = PluginSpec(plugin_id='example.threshold', role='gate_policy',
                      execution_modes=('once', 'repeat', 'stream'),
                      diagnostic_schemas=('example.threshold_decision',))

    def __init__(self, threshold: float = .7):
        self.parameters = ThresholdParameters(threshold=threshold)

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


def build_threshold_gate(parameters, *, context):
    if set(parameters) - {'threshold'}:
        raise ContractError('Unknown threshold gate parameter')
    return ThresholdGate(**parameters)


build_threshold_gate.spec = ThresholdGate.spec
