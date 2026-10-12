"""MemForest text variant: joint clustering, MST pair routing, per-round refresh."""
from __future__ import annotations
from .common import resolve

from dataclasses import dataclass
from collections import defaultdict
from fractions import Fraction
import math
from ..core import AlgorithmState, FrozenMap, PlanningResult, fingerprint
from ..core.values import require
from .common import (Group,Geometry,component_nodes,emit,feature,node_targets,plan_groups,spec,subset_request)


def times(request,nodes,mode):
    if mode=='order':return {n.node_id:n.order for n in nodes}
    require(mode=='event_time','MemForest time_order must be event_time or order')
    rows={r.node_id:r.values for r in feature(request,'temporal',[n.node_id for n in nodes]).rows}
    require(all(type(rows[n.node_id].get('event_time')) in (int,float) for n in nodes),'MemForest requires parsed temporal features')
    require(len({rows[n.node_id].get('clock') for n in nodes})==1 and all(rows[n.node_id].get('clock') for n in nodes),'MemForest time clocks disagree')
    return {n.node_id:rows[n.node_id]['event_time'] for n in nodes}


@dataclass(frozen=True)
class JointClusters:
    cluster_ratio: float = .05
    semantic_time_alpha: float = .8
    time_window_size: int = 5
    feature_name: str = 'semantic'
    time_order: str = 'event_time'
    seed: int = 42
    spec = spec('memforest.joint_clusters','partitioner', diagnostics=('memfolder.planning.memforest_clusters',))
    def partition(self,request,target,context):
        from ._memforest import build_joint_clusters
        require(0<self.cluster_ratio<=1 and 0<=self.semantic_time_alpha<=1 and self.time_window_size>=0,'Invalid joint clustering configuration')
        nodes=component_nodes(request);geo=Geometry.of(request,nodes,self.feature_name,dtype='float32');time=times(request,nodes,self.time_order)
        @dataclass(frozen=True)
        class Item:
            point_id: str
            vector: object
            created_at: float
        items=[Item(n.node_id,geo.vectors[i],time[n.node_id]) for i,n in enumerate(nodes)]
        clusters=build_joint_clusters(items,self.cluster_ratio,self.semantic_time_alpha,self.time_window_size,self.seed)
        groups=tuple(Group(rows[0].point_id,tuple(n.point_id for n in rows)) for _,rows in sorted(clusters.items()))
        emit(context,self.spec.plugin_id,'memfolder.planning.memforest_clusters',nodes=geo.node_ids,
             groups=[{'center':g.anchor_id,'members':g.member_ids} for g in groups])
        return groups


@dataclass(frozen=True)
class CapacityAllocator:
    spec = spec('budgets.capacity_allocator','budget_allocator')
    def allocate(self,groups,target,context):
        require(len(groups)<=target<=sum(len(g.member_ids) for g in groups),'Target below nonempty cluster count')
        amounts={g.anchor_id:1 for g in groups};remaining=target-len(groups)
        capacity=sum(len(g.member_ids)-1 for g in groups);remainders=[]
        if remaining:
            for g in groups:
                quota=Fraction(remaining*(len(g.member_ids)-1),capacity);extra=quota.numerator//quota.denominator
                amounts[g.anchor_id]+=extra;remainders.append((quota-extra,g.anchor_id))
            for _,i in sorted(remainders,key=lambda r:(-r[0],r[1]))[:target-sum(amounts.values())]:amounts[i]+=1
        return FrozenMap(amounts)


@dataclass(frozen=True)
class LegacyClusterCeil:
    keep_ratio: float = .7
    spec = spec('memforest.legacy_cluster_ceil','budget_allocator')
    def allocate(self,groups,target,context):
        require(0<self.keep_ratio<=1,'Invalid MemForest cluster keep ratio')
        result={g.anchor_id:max(1,math.ceil(len(g.member_ids)*self.keep_ratio)) for g in groups}
        require(sum(result.values())==target,
                'Legacy per-cluster ceil differs from requested scope K; resolve explicit cluster budgets or select capacity allocation')
        return FrozenMap(result)


@dataclass(frozen=True)
class MstPairRouter:
    feature_name: str = 'semantic'
    time_order: str = 'event_time'
    spec = spec('memforest.mst_pair','pair_router', diagnostics=('memfolder.planning.mst_pair',))
    def pair(self,request,nodes,context):
        from ._memforest import best_merge_pair_via_mst
        geo=Geometry.of(request,nodes,self.feature_name,dtype='float32')
        @dataclass(frozen=True)
        class Item:
            vector: object
        pair=best_merge_pair_via_mst([Item(v) for v in geo.vectors])
        require(pair is not None,'MST has no feasible merge pair')
        a,b=(nodes[i] for i in pair);time=times(request,(a,b),self.time_order)
        older,newer=(a,b) if time[a.node_id]<=time[b.node_id] else (b,a)
        emit(context,self.spec.plugin_id,'memfolder.planning.mst_pair',nodes=(older.node_id,newer.node_id),
             older=older.node_id,newer=newer.node_id,edge_rule='0.90*cosine - 0.10*normalized_degree_sum')
        return Group(newer.node_id,(older.node_id,newer.node_id))


@dataclass(frozen=True)
class MemForestPlanner:
    clusterer: object = JointClusters()
    allocator: object = CapacityAllocator()
    router: object = MstPairRouter()
    spec = spec('memforest.mst','planner',actions=('keep','merge'),modes=('repeat',), diagnostics=('memfolder.compression.completed', 'memfolder.planning.plan'))
    async def plan(self,request,context):
        previous={}
        if request.state is not None:
            require(request.state.schema=='memfolder.memforest.clusters' and request.state.version==1,'Wrong MemForest state schema/version')
            previous=request.state.data['scopes']
        state={};groups=[]
        for key,nodes,target in node_targets(request):
            if not nodes:continue
            require(len({n.scope for n in nodes})==1,'MemForest merge budget group must remain within one scope')
            locked=tuple(n for n in nodes if not n.retention.may_merge);active=tuple(n for n in nodes if n.retention.may_merge)
            groups.extend(Group(n.node_id,(n.node_id,)) for n in locked);k=target-len(locked)
            require(k>=1 if active else k==0,'MemForest target cannot preserve protected nodes')
            if not active:continue
            local=subset_request(request,active)
            if key not in previous:
                # Group budgets were produced by the upstream joint clusterer.
                # Re-clustering these groups would silently change the legacy method.
                node_budget=next(b for b in request.budgets if b.request.unit=='nodes')
                initial=(Group(active[0].node_id,tuple(n.node_id for n in active)),) if node_budget.request.allocation=='group' else await resolve(self.clusterer.partition(local,k,context))
                from .common import check_groups
                check_groups(active,initial)
                limits=await resolve(self.allocator.allocate(initial,k,context))
                require(set(limits)=={g.anchor_id for g in initial} and sum(limits.values())==k,'Cluster allocation must equal scope target')
                assignment={i:g.anchor_id for g in initial for i in g.member_ids}
            else:
                assignment=dict(previous[key]['assignment']);limits=previous[key]['limits']
                require(set(assignment)=={n.node_id for n in active} and sum(limits.values())==k,'Stale MemForest cluster state')
            clustered=defaultdict(list)
            for n in active:clustered[assignment[n.node_id]].append(n)
            next_assignment=dict(assignment)
            time=times(request,active,getattr(self.router,'time_order','event_time'))
            for cluster,rows in clustered.items():
                rows=tuple(sorted(rows,key=lambda n:time[n.node_id]))
                if len(rows)>limits[cluster]:
                    pair=await resolve(self.router.pair(local,rows,context));require(len(pair.member_ids)==2,'MST router must select one pair')
                    require(set(pair.member_ids)<={n.node_id for n in rows} and pair.anchor_id in pair.member_ids,'Invalid MST pair')
                    groups.append(pair)
                    for i in pair.member_ids:next_assignment.pop(i)
                    next_assignment[pair.anchor_id]=cluster
                    groups.extend(Group(n.node_id,(n.node_id,)) for n in rows if n.node_id not in pair.member_ids)
                else:groups.extend(Group(n.node_id,(n.node_id,)) for n in rows)
            state[key]={'assignment':next_assignment,'limits':dict(limits)}
        plan=plan_groups(request,tuple(groups),method=self.spec.plugin_id,input_view='current')
        from dataclasses import replace
        plan=replace(plan,actions=tuple(replace(a,parameters=FrozenMap({**a.parameters,'timestamp_policy':'latest'})) for a in plan.actions),
            extensions=FrozenMap({**plan.extensions,'memfolder.budget_allocator':self.allocator.spec.plugin_id}))
        return PlanningResult(plan=plan,next_state=AlgorithmState(schema='memfolder.memforest.clusters',version=1,data=FrozenMap({'scopes':state})))


async def resolve_memforest_budget(request,context,*,clusterer=None,keep_ratio=.7):
    """Original per-cluster ceil recipe, resolved before any text merge."""
    from ..core import BudgetGroup,BudgetRequest,resolve_budget
    clusterer=clusterer or JointClusters();by_scope=defaultdict(list)
    for n in request.snapshot.records:
        if n.eligible:by_scope[n.scope].append(n)
    groups=[]
    for scope,nodes in by_scope.items():
        require(all(n.retention.may_merge for n in nodes),'Legacy MemForest clustering requires mergeable nodes; use capacity adaptation for protected inputs')
        local=subset_request(request,tuple(nodes));clusters=await resolve(clusterer.partition(local,len(nodes),context))
        from .common import check_groups
        check_groups(nodes,clusters)
        for g in clusters:groups.append(BudgetGroup(group_id=fingerprint((scope,g.anchor_id)),member_ids=g.member_ids))
    return resolve_budget(request.snapshot,BudgetRequest(unit='nodes',ratio=keep_ratio,allocation='group',rounding='ceil',minimum=1),groups=tuple(groups))
