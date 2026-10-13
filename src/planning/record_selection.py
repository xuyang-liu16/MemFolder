"""Pruning, random selection, KMeans clustering and record grouping."""

from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import math
import random
from ..component_runtime import emit, resolve, spec
from .contracts import AnchorSelection, Group
from ..core import PlanningResult, fingerprint
from ..core.values import require
from .plan_helpers import (
    Geometry,
    check_anchors,
    check_groups,
    component_nodes,
    node_targets,
    numpy,
    plan_groups,
    plan_prune,
    selection_request,
    selection_required,
    subset_request,
)


def stable_seed(seed,scope,cluster,method):
    payload=json.dumps((seed,scope,cluster,method),ensure_ascii=True,separators=(',',':'))
    return int.from_bytes(hashlib.blake2b(payload.encode(),digest_size=16).digest(),'little')


def id_keys(nodes, policy):
    require(policy in ('canonical', 'source_numeric'), 'Choose canonical or source_numeric ID order')
    if policy == 'canonical':
        return {n.node_id: n.node_id for n in nodes}
    result = {}
    for n in nodes:
        value = n.native.get('id')
        require(type(value) in (str, int) and str(value).isdigit(), 'source_numeric requires explicit numeric native IDs')
        result[n.node_id] = int(value)
    require(len(set(result.values())) == len(result), 'Numeric native IDs are ambiguous within the partition')
    return result


@dataclass(frozen=True)
class RandomSelector:
    spec = spec('random_prune.python','anchor_selector', diagnostics=('memfolder.planning.selection',))
    def select(self,request,target,context):
        nodes=component_nodes(request)
        mandatory=[n.node_id for n in selection_required(request,nodes)]
        require(target>=len(mandatory),'Prune target is below protected-node count')
        optional=[n.node_id for n in nodes if n.node_id not in mandatory]
        selected=tuple(mandatory+random.Random(request.seed).sample(optional,target-len(mandatory)))
        emit(context,self.spec.plugin_id,'memfolder.planning.selection',nodes=selected,seed=request.seed,retained=selected)
        return AnchorSelection(request.snapshot.fingerprint,selected)


@dataclass(frozen=True)
class DartSelector:
    variant: str = 'random_anchor_farthest'
    feature_name: str = 'semantic'
    anchor_fraction: float = .02
    spec = spec('dart.memory_adaptation','anchor_selector', diagnostics=('memfolder.planning.selection',))
    def select(self,request,target,context):
        np=numpy();nodes=component_nodes(request)
        require(self.variant in ('random_anchor_farthest','medoid_pivot') and 0<self.anchor_fraction<=1,'Invalid DART variant')
        mandatory=[n.node_id for n in selection_required(request,nodes)]
        require(target>=len(mandatory),'DART target is below protected-node count')
        if target==0:return AnchorSelection(request.snapshot.fingerprint,())
        geo=Geometry.of(request,nodes,self.feature_name)
        canonical=sorted(range(len(nodes)),key=lambda i:geo.node_ids[i])
        vectors=geo.vectors[canonical];cos=np.clip(vectors @ vectors.T,-1.,1.);ids=[geo.node_ids[i] for i in canonical]
        if self.variant=='medoid_pivot':
            cost=(1-cos).sum(axis=1);best=float(cost.min())
            pivot=min((i for i in range(len(ids)) if abs(float(cost[i])-best)<=1e-12*max(1,abs(best))),key=lambda i:ids[i])
            pivots=[pivot];ranked=sorted((i for i in range(len(ids)) if i!=pivot),key=lambda i:(float(cos[pivot,i]),ids[i]))
            seed=None
        else:
            scope=request.extensions.get('memfolder.seed_scope_id',fingerprint(nodes[0].scope))
            cluster=request.extensions.get('memfolder.seed_cluster_id',0)
            seed=stable_seed(request.seed,scope,cluster,'dart_random_anchor_farthest')
            rng=np.random.Generator(np.random.PCG64(seed));permutation=rng.permutation(len(ids)).tolist()
            pivots=permutation[:min(target,max(1,math.ceil(self.anchor_fraction*len(ids))))]
            ranked=sorted((i for i in range(len(ids)) if i not in set(pivots)),key=lambda i:(float(cos[i,pivots].max()),ids[i]))
        ranking=[ids[i] for i in pivots+ranked]
        selected=tuple(mandatory+[i for i in ranking if i not in mandatory][:target-len(mandatory)])
        emit(context,self.spec.plugin_id,'memfolder.planning.selection',nodes=selected,variant=self.variant,
             seed=seed,pivots=[ids[i] for i in pivots],ranking=ranking,retained=selected)
        return AnchorSelection(request.snapshot.fingerprint,selected)


@dataclass(frozen=True)
class PrunePlanner:
    selector: object = RandomSelector()
    spec = spec('prune.planner','planner',actions=('keep','drop'), diagnostics=('memfolder.compression.completed', 'memfolder.planning.plan'))
    async def plan(self,request,context):
        retained=[]
        for _,nodes,target in node_targets(request):
            if not nodes:continue
            local=selection_request(subset_request(request,nodes),'drop')
            selection=await resolve(self.selector.select(local,target,context))
            check_anchors(request,nodes,selection,target)
            require({n.node_id for n in selection_required(local,nodes)} <= set(selection.selected_ids), 'Selector omitted drop-protected nodes')
            retained.extend(selection.selected_ids)
        return PlanningResult(plan=plan_prune(request,retained,method=self.selector.spec.plugin_id))


@dataclass(frozen=True)
class RandomGroups:
    variant: str = 'global_pair'
    seed_template: str = '{seed}:{scope}:{count}:{target}'
    spec = spec('random_merge.global_pair','partitioner', diagnostics=('memfolder.planning.partition',))
    def partition(self,request,target,context):
        nodes=component_nodes(request)
        require(self.variant=='global_pair','Use random_merge.round for disjoint layer pairing')
        require(1<=target<=len(nodes),'Random merge needs a positive target')
        locked=[Group(n.node_id,(n.node_id,)) for n in nodes if not n.retention.may_merge]
        active=[[n.node_id] for n in nodes if n.retention.may_merge];k=target-len(locked)
        require(k>0 or not active,'Random merge cannot reach the requested protected-node target')
        seed=self.seed_template.format(seed=request.seed,scope=fingerprint(nodes[0].scope),count=len(active),target=k)
        rng=random.Random(seed)
        while len(active)>k:
            i,j=rng.sample(range(len(active)),2);combined=active[i]+active[j]
            for index in sorted((i,j),reverse=True):active.pop(index)
            active.append(combined)
        rank={n.node_id:p for p,n in enumerate(nodes)}
        result=tuple(locked+[Group(min(ids,key=rank.__getitem__),tuple(sorted(ids,key=rank.__getitem__))) for ids in active])
        emit(context,self.spec.plugin_id,'memfolder.planning.partition',seed=seed,groups=[g.member_ids for g in result])
        return result


@dataclass(frozen=True)
class KmeansClusters:
    feature_name: str = 'semantic'
    n_init: int = 10
    max_iter: int = 300
    spec = spec('kmeans.clusters','partitioner', diagnostics=('memfolder.planning.clusters',))
    def partition(self,request,target,context):
        nodes=component_nodes(request);np=numpy()
        require(1<=target<=len(nodes),'KMeans needs a positive cluster count')
        if target==len(nodes):return tuple(Group(n.node_id,(n.node_id,)) for n in nodes)
        try:
            from sklearn.cluster import KMeans
        except ImportError:
            from ..core import ContractError
            raise ContractError('KMeans requires memfolder[algorithms]') from None
        geo=Geometry.of(request,nodes,self.feature_name)
        model=KMeans(n_clusters=target,n_init=self.n_init,max_iter=self.max_iter,random_state=request.seed)
        labels=model.fit_predict(geo.vectors.copy())
        # Identical vectors can produce fewer nonempty clusters. Repair by splitting
        # a largest cluster, with stable ID ties, to preserve the user's exact K.
        repaired=[]
        for c in range(target):
            if np.any(labels==c):continue
            sizes={int(k):int((labels==k).sum()) for k in set(labels.tolist())}
            donor=min((k for k in sizes if sizes[k]>1),key=lambda k:(-sizes[k],k))
            rows=np.flatnonzero(labels==donor);center=geo.vectors[rows].mean(axis=0)
            distance=((geo.vectors[rows]-center)**2).sum(axis=1);maximum=float(distance.max())
            chosen=min((int(r) for r,d in zip(rows,distance) if abs(float(d)-maximum)<=1e-12),key=lambda i:geo.node_ids[i])
            labels[chosen]=c;repaired.append(geo.node_ids[chosen])
        groups=[]
        for c in range(target):
            rows=np.flatnonzero(labels==c);center=geo.vectors[rows].mean(axis=0)
            distance=((geo.vectors[rows]-center)**2).sum(axis=1);best=float(distance.min())
            anchor=min((int(r) for r,d in zip(rows,distance) if abs(float(d)-best)<=1e-12),key=lambda i:geo.node_ids[i])
            groups.append(Group(geo.node_ids[anchor],tuple(geo.node_ids[int(i)] for i in rows)))
        emit(context,self.spec.plugin_id,'memfolder.planning.clusters',nodes=geo.node_ids,
            labels=[int(v) for v in labels],centers=[geo.vectors[np.flatnonzero(labels==c)].mean(axis=0).tolist() for c in range(target)],
            repaired_empty_clusters=repaired,groups=[{'anchor':g.anchor_id,'members':g.member_ids} for g in groups])
        return tuple(groups)


@dataclass(frozen=True)
class ClusterRepresentatives:
    clusterer: object = KmeansClusters()
    spec = spec('kmeans.nearest_representative','anchor_selector')
    async def select(self,request,target,context):
        nodes=component_nodes(request);mandatory=[n.node_id for n in selection_required(request,nodes)]
        require(target>=len(mandatory),'KMeans prune cannot drop protected nodes')
        remaining=tuple(n for n in nodes if n.node_id not in mandatory);count=target-len(mandatory)
        if count==0:return AnchorSelection(request.snapshot.fingerprint,tuple(mandatory))
        groups=await resolve(self.clusterer.partition(subset_request(request,remaining),count,context));check_groups(remaining,groups,target=count)
        return AnchorSelection(request.snapshot.fingerprint,tuple(mandatory+[g.anchor_id for g in groups]))


@dataclass(frozen=True)
class PartitionPlanner:
    partitioner: object = RandomGroups()
    rewrite_singletons: bool = False
    input_view: str = 'original'
    spec = spec('partition.planner','planner',actions=('keep','merge','rewrite'), diagnostics=('memfolder.compression.completed', 'memfolder.planning.plan'))
    async def plan(self,request,context):
        groups=[]
        for _,nodes,target in node_targets(request):
            if not nodes:continue
            require(len({n.scope for n in nodes})==1,'Merge partition budget group must remain within one scope')
            locked=tuple(n for n in nodes if not n.retention.may_merge)
            active=tuple(n for n in nodes if n.retention.may_merge);k=target-len(locked)
            require(k>=1 if active else k==0,'Partition target cannot preserve protected nodes')
            groups.extend(Group(n.node_id,(n.node_id,)) for n in locked)
            if active:
                local=await resolve(self.partitioner.partition(subset_request(request,active),k,context));check_groups(active,local,target=k);groups.extend(local)
        return PlanningResult(plan=plan_groups(request,tuple(groups),method=self.partitioner.spec.plugin_id,
            rewrite_singletons=self.rewrite_singletons,input_view=self.input_view))


@dataclass(frozen=True)
class CurrentRecordRewritePlanner:
    spec = spec('context.current_record_rewrite.v1', 'planner',
                actions=('keep', 'rewrite'), modes=('once',))

    def plan(self, request, context):
        groups = tuple(Group(n.node_id, (n.node_id,))
                       for n in request.snapshot.records if n.eligible)
        return PlanningResult(plan=plan_groups(request, groups,
            method=self.spec.plugin_id, rewrite_singletons=True, input_view='current'))
