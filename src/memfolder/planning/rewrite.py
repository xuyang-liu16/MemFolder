"""Rewrite each current record once, independently of its record grouping method."""
from dataclasses import dataclass
from ..core import PlanningResult
from .common import Group, plan_groups, spec


@dataclass(frozen=True)
class CurrentRecordRewritePlanner:
    spec = spec('context.current_record_rewrite.v1', 'planner',
                actions=('keep', 'rewrite'), modes=('once',))

    def plan(self, request, context):
        groups = tuple(Group(n.node_id, (n.node_id,))
                       for n in request.snapshot.records if n.eligible)
        return PlanningResult(plan=plan_groups(request, groups,
            method=self.spec.plugin_id, rewrite_singletons=True, input_view='current'))
