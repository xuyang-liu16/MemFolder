"""Small execution driver for Planner/Operator. Native backend IO stays outside."""
from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from pathlib import Path

from .core import (
    AlgorithmContext,
    OperatorContext,
    PlanningRequest,
    Snapshot,
    NullDiagnostics,
    FrozenMap,
    validate_composition,
    validate_features,
    validate_plan,
    validate_result,
    validate_projection,
    validate_budget,
    result_records,
    fingerprint,
)
from .core.values import require
from .component_runtime import emit, resolve as resolved


class ServiceMap:
    def __init__(self,services=None): self._services=MappingProxyType(dict(services or {}))
    def require(self,service_id):
        require(service_id in self._services,'Missing configured service: '+service_id)
        return self._services[service_id]
    def overlay(self,services):
        return ServiceMap({**self._services,**services})
    def items(self):return tuple(self._services.items())


class OriginalArchive:
    """Read-only initial records, indexed by full origin identity."""
    def __init__(self,snapshot):
        values={}
        for n in snapshot.records:
            for o in n.origins:
                require(o not in values,'Original archive has ambiguous origin identity')
                values[o]=n
        self._records=MappingProxyType(values)
    def get(self,origin):
        require(origin in self._records,'Original archive does not contain requested origin')
        return self._records[origin]


class DiagnosticCollector:
    """Detached immutable records; callbacks cannot replace algorithm results.

    This is a trusted in-process extension, not an isolation sandbox. Callback
    errors fail observation explicitly. enable_schemas=None captures all schemas.
    """
    def __init__(self,*,enable_schemas=None,callbacks=()):
        self._schemas=None if enable_schemas is None else frozenset(enable_schemas)
        self._records=[];self._callbacks=tuple(callbacks)
    def enabled(self,schema):return self._schemas is None or schema in self._schemas
    def emit(self,record):
        if not self.enabled(record.schema):return
        self._records.append(record)
        for callback in self._callbacks:callback(record)
    @property
    def records(self):return tuple(self._records)
    def write_jsonl(self,path):
        from .core import dumps
        path=Path(path)
        with path.open('x',encoding='utf-8') as stream:
            for record in self.records:stream.write(dumps(record)+'\n')


@dataclass(frozen=True)
class CompressionStep:
    request: object
    planning: object
    result: object


@dataclass(frozen=True)
class CompressionRun:
    snapshot: Snapshot
    steps: tuple[CompressionStep,...]


class NodeProjection:
    """Node-only canonical projection. Graphs require an explicit graph projector."""
    def project(self,source,plan,result,context):
        require(not source.edges,'Configure a graph projector; node-only projection cannot rewire graph edges')
        return replace(source,records=result_records(source,plan,result),revision=source.revision+1)


class PruneGraphProjection:
    """Canonical prune-only projection, preserving remaining edge IDs and assets.

    This is not an M3 native materializer: Wrapper still owns text indexes,
    character/equivalence maps and retrieval structures.
    """
    def project(self,source,plan,result,context):
        require(all(a.kind in ('keep','drop') for a in plan.actions),'Prune graph projection cannot project merges')
        records=result_records(source,plan,result);ids={n.node_id for n in records}
        return replace(source,records=records,edges=tuple(e for e in source.edges if e.source_id in ids and e.target_id in ids),revision=source.revision+1)


def realized_nodes(budget,initial,current):
    initial_nodes={n.node_id:n for n in initial.records if n.eligible}
    origin_group={}
    for target in budget.targets:
        require(set(target.group.member_ids)<=set(initial_nodes),'Budget reference differs from initial archive')
        for i in target.group.member_ids:
            for o in initial_nodes[i].origins:origin_group[o]=target.group.group_id
    counts={t.group.group_id:0 for t in budget.targets}
    for n in current.records:
        if not n.eligible:continue
        groups={origin_group[o] for o in n.origins if o in origin_group}
        require(len(groups)==1,'Compressed node crosses or escapes resolved budget groups')
        counts[next(iter(groups))]+=1
    return counts


@dataclass(frozen=True)
class CompressionEngine:
    planner: object
    operator: object
    feature_providers: tuple[object,...] = ()
    available: tuple[str,...] = ()

    async def step(self,request,*,services=None,diagnostics=None,originals=None):
        services=services or ServiceMap();diagnostics=diagnostics or NullDiagnostics()
        context=AlgorithmContext(services=services,diagnostics=diagnostics)
        validate_composition(self.planner.spec,(self.operator.spec,),mode=request.mode,available=self.available)
        for b in request.budgets:
            require(b.request.unit=='nodes' or b.request.enforcement=='advisory',
                    'This driver enforces node budgets only; configure a text budget executor for exact token caps')
        features=list(request.features)
        for provider in self.feature_providers:
            require(provider.spec.role=='feature_provider','Feature provider role mismatch')
            batch=await resolved(provider.extract(request.snapshot,context));validate_features(request.snapshot,batch)
            require(batch.name not in {b.name for b in features},'Duplicate configured feature name')
            features.append(batch)
        request=replace(request,features=tuple(features))
        planning=await resolved(self.planner.plan(request,context));validate_plan(request.snapshot,planning.plan)
        emit(context,self.planner.spec.plugin_id,'memfolder.planning.plan',
             nodes=planning.plan.target_ids,actions=[a.action_id for a in planning.plan.actions],
             input_fingerprint=request.snapshot.fingerprint,plan_fingerprint=planning.plan.fingerprint,
             actions_data=[{'id':a.action_id,'kind':a.kind,'members':a.member_ids,'outputs':a.output_ids,'input_view':a.input_view} for a in planning.plan.actions])
        operator_context=OperatorContext(services=services,diagnostics=diagnostics,
                                         originals=originals or OriginalArchive(request.snapshot))
        result=await resolved(self.operator.apply(request.snapshot,planning.plan,operator_context))
        validate_result(request.snapshot,planning.plan,result)
        return CompressionStep(request,planning,result)

    async def run(self,request,*,services=None,diagnostics=None,projector=None,originals=None,max_rounds=None):
        if max_rounds is None:
            # Sequential plugins may remove just one node per step. Keep a finite
            # default large enough for an arbitrary input size; explicit caps win.
            max_rounds=max(256,sum(n.eligible for n in request.snapshot.records))
        require(type(max_rounds) is int and max_rounds>0,'max_rounds must be positive')
        initial=request.snapshot;current=initial;archive=originals or OriginalArchive(initial)
        services=services or ServiceMap();diagnostics=diagnostics or NullDiagnostics();projector=projector or NodeProjection()
        context=AlgorithmContext(services=services,diagnostics=diagnostics);state=request.state;steps=[]
        for index in range(max_rounds):
            budgets=[]
            for b in request.budgets:
                if b.request.reference=='current':
                    from .core import resolve_budget
                    require(b.request.allocation=='scope','Current custom-group budgets need an explicit runtime resolver')
                    b=resolve_budget(current,b.request)
                budgets.append(b)
            membership={}
            original_nodes={n.node_id:n for n in initial.records}
            for b in budgets:
                if b.request.unit=='nodes' and b.request.reference=='initial':
                    for t in b.targets:
                        for i in t.group.member_ids:
                            require(i in original_nodes,'Initial budget names an unknown original node')
                            for o in original_nodes[i].origins:membership[fingerprint(o)]=t.group.group_id
            local=replace(request,snapshot=current,features=request.features if index==0 else (),
                          budgets=tuple(budgets),state=state,round_index=request.round_index+index,
                          extensions=FrozenMap({**request.extensions,'memfolder.budget_membership':membership}))
            step=await self.step(local,services=services,diagnostics=diagnostics,originals=archive);steps.append(step)
            proposed=await resolved(projector.project(current,step.planning.plan,step.result,context))
            validate_projection(current,step.planning.plan,step.result,proposed)
            changed=any(a.kind!='keep' for a in step.planning.plan.actions)
            current=proposed;state=step.planning.next_state
            within=True
            for b in budgets:
                if b.request.unit!='nodes':continue
                amounts=realized_nodes(b,step.request.snapshot if b.request.reference=='current' else initial,current)
                within &= all(amounts[t.group.group_id] == t.limit if b.request.enforcement=='exact' else amounts[t.group.group_id]<=t.limit
                              for t in b.targets) if b.request.enforcement!='advisory' else True
            if request.mode!='repeat' or within:
                for b in budgets:
                    if b.request.unit=='nodes':validate_budget(b,realized_nodes(b,step.request.snapshot if b.request.reference=='current' else initial,current))
                emit(context,self.planner.spec.plugin_id,'memfolder.compression.completed',rounds=len(steps),
                    initial_fingerprint=initial.fingerprint,final_fingerprint=current.fingerprint,records=len(current.records))
                return CompressionRun(current,tuple(steps))
            require(changed,'Compression stalled before reaching the configured node budget')
        require(False,'Compression exceeded max_rounds before reaching the configured node budget')
