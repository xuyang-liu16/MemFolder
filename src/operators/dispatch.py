"""Configurable per-action routing; useful for mixing prune, merge and rewrite writers."""
from dataclasses import dataclass
from ..core import ActionPlan,OperatorResult,PluginSpec,FrozenMap,validate_plan,validate_result
from ..core.values import require


@dataclass(frozen=True)
class DispatchOperator:
    routes: object
    spec = PluginSpec(plugin_id='memfolder.operator.dispatch',role='operator',
        action_kinds=('keep','drop','merge','rewrite'),execution_modes=('once','repeat','stream'))
    async def apply(self,snapshot,plan,context):
        from ..compression import resolved
        validate_plan(snapshot,plan);outcomes={}
        for kind in dict.fromkeys(a.kind for a in plan.actions):
            require(kind in self.routes,'Operator dispatch has no route for action kind')
            operator=self.routes[kind];require(kind in operator.spec.action_kinds,'Dispatch route cannot execute this action kind')
            actions=tuple(a for a in plan.actions if a.kind==kind)
            subplan=ActionPlan(plan_id=plan.plan_id+'.'+kind,input_fingerprint=plan.input_fingerprint,
                target_ids=tuple(i for a in actions for i in a.member_ids),actions=actions,boundary=plan.boundary)
            result=await resolved(operator.apply(snapshot,subplan,context));validate_result(snapshot,subplan,result)
            outcomes.update({o.action_id:o for o in result.outcomes})
        result=OperatorResult(plan_fingerprint=plan.fingerprint,outcomes=tuple(outcomes[a.action_id] for a in plan.actions))
        validate_result(snapshot,plan,result);return result


def build(parameters,*,context):
    from ..plugins import PluginRequest
    from types import MappingProxyType
    require(set(parameters)=={'routes'} and set(parameters['routes'])==set(build.spec.action_kinds),
            'Dispatch routes must explicitly define keep/drop/merge/rewrite')
    routes={kind:context.registry.create(PluginRequest.from_mapping(value),role='operator',context=context,
        available=context.available).instance for kind,value in parameters['routes'].items()}
    return DispatchOperator(MappingProxyType(routes))
build.spec=DispatchOperator.spec
