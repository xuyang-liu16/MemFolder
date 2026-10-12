"""Backend-neutral baseline stages, with explicit historical variants."""
from __future__ import annotations
from .common import resolve

from dataclasses import dataclass
from collections import defaultdict
import hashlib
import json
import math
import random

from ..core import AlgorithmState, FrozenMap, PlanningResult, fingerprint
from ..core.values import require
from .common import (Group,AnchorSelection,check_anchors,Geometry, check_groups, component_nodes, emit, node_targets,
    numpy, plan_groups, plan_prune, spec, subset_request, feature, selection_request, selection_required)


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
class TomePooledGroups:
    feature_name: str = 'semantic'
    id_order: str = 'canonical'
    spec = spec('tome.pooled_m3','partitioner')
    def partition(self,request,target,context):
        np=numpy();nodes=component_nodes(request);geo=Geometry.of(request,nodes,self.feature_name)
        rows={r.node_id:r for r in feature(request,self.feature_name,geo.node_ids).rows};keys=id_keys(nodes,self.id_order)
        groups=[[n.node_id] for n in nodes];vectors=geo.vectors.copy();sizes=np.asarray([rows[n.node_id].mass for n in nodes],dtype=np.float64)
        while len(groups)>target:
            a=np.arange(0,len(groups),2);b=np.arange(1,len(groups),2)
            sim=vectors[a] @ vectors[b].T;best=np.argmax(sim,axis=1)
            # Source M3 implementation permits ceil(n/2) A sources in odd layers.
            r=min(len(groups)-target,len(a));score=sim[np.arange(len(a)),best]
            chosen=sorted(range(len(a)),key=lambda i:(-float(score[i]),min(keys[j] for j in groups[int(a[i])])) )[:r]
            into=defaultdict(list)
            for i in chosen:into[int(b[best[i]])].append(int(a[i]))
            absorbed={i for ids in into.values() for i in ids};new_groups=[];new_vectors=[];new_sizes=[]
            for j in range(len(groups)):
                if j in absorbed:continue
                rows=[j]+into.get(j,[]);weight=sizes[rows];vector=(vectors[rows]*weight[:,None]).sum(axis=0);norm=np.linalg.norm(vector)
                new_groups.append([m for row in rows for m in groups[row]])
                new_vectors.append(vector/norm if norm>0 else vectors[j]);new_sizes.append(float(weight.sum()))
            groups=new_groups;vectors=np.asarray(new_vectors);sizes=np.asarray(new_sizes)
        return tuple(Group(min(ids,key=keys.__getitem__),tuple(sorted(ids,key=keys.__getitem__))) for ids in groups)


@dataclass(frozen=True)
class AverageLinkageGroups:
    feature_name: str = 'semantic'
    id_order: str = 'canonical'
    spec = spec('memforest.average_linkage_proxy','partitioner')
    def partition(self,request,target,context):
        np=numpy();nodes=component_nodes(request);geo=Geometry.of(request,nodes,self.feature_name);keys=id_keys(nodes,self.id_order)
        groups=[[n.node_id] for n in nodes];sums=[v.copy() for v in geo.vectors];sizes=[1.]*len(nodes)
        while len(groups)>target:
            pairs=[(i,j,float(sums[i] @ sums[j])/(sizes[i]*sizes[j])) for i in range(len(groups)) for j in range(i+1,len(groups))]
            best=max(w for _,_,w in pairs)
            i,j,_=min((p for p in pairs if abs(p[2]-best)<=1e-12),key=lambda p:tuple(sorted((min(keys[k] for k in groups[p[0]]),min(keys[k] for k in groups[p[1]])))))
            groups[i]+=groups[j];sums[i]+=sums[j];sizes[i]+=sizes[j]
            for array in (groups,sums,sizes):array.pop(j)
        return tuple(Group(min(ids,key=keys.__getitem__),tuple(sorted(ids,key=keys.__getitem__))) for ids in groups)


@dataclass(frozen=True)
class TomeRoundPlanner:
    feature_name: str = 'semantic'
    random_pairs: bool = False
    spec = spec('tome.text_round','planner',actions=('keep','merge'),modes=('repeat',), diagnostics=('memfolder.compression.completed', 'memfolder.planning.plan', 'memfolder.planning.tome_round'))
    async def plan(self,request,context):
        np=numpy();groups=[];sequences={};previous={}
        if request.state is not None:
            require(request.state.schema=='memfolder.tome.sequence' and request.state.version==1,'Wrong ToMe state schema/version')
            previous=request.state.data['sequences']
        for key,nodes,target in node_targets(request):
            if not nodes:continue
            require(len({n.scope for n in nodes})==1,'ToMe merge budget group must remain within one scope')
            locked=[n for n in nodes if not n.retention.may_merge];active=[n for n in nodes if n.retention.may_merge]
            k=target-len(locked);require(k>=1 if active else k==0,'ToMe cannot reach protected-node target')
            if key in previous:
                ids=previous[key];by_id={n.node_id:n for n in active}
                require(set(ids)==set(by_id) and len(ids)==len(by_id),'Stale ToMe sequence state')
                active=[by_id[i] for i in ids]
            groups.extend(Group(n.node_id,(n.node_id,)) for n in locked)
            if len(active)<=k:
                groups.extend(Group(n.node_id,(n.node_id,)) for n in active);sequences[key]=[n.node_id for n in active];continue
            reduction=min(len(active)-k,len(active)//2);into=defaultdict(list)
            if self.random_pairs:
                rng=np.random.Generator(np.random.PCG64(request.seed+request.round_index));permutation=rng.permutation(len(active))
                pairs=permutation[:2*reduction].reshape(reduction,2).tolist()
                for a,b in pairs:into[b].append(a)
                chosen={a for a,b in pairs};destinations=[b for a,b in pairs];paired=chosen|set(destinations)
                unmerged=[i for i in range(len(active)) if i not in paired]
            else:
                geo=Geometry.of(request,active,self.feature_name,dtype='float32')
                a=np.arange(0,len(active),2);b=np.arange(1,len(active),2);sim=geo.vectors[a] @ geo.vectors[b].T
                best=np.argmax(sim,axis=1);score=sim[np.arange(len(a)),best];rank=np.argsort(-score,kind='mergesort')
                for i in rank[:reduction]:into[int(b[best[i]])].append(int(a[i]))
                chosen={int(a[i]) for i in rank[:reduction]};destinations=b.tolist();unmerged=[int(a[i]) for i in rank[reduction:]]
            next_ids=[]
            for j in unmerged+destinations:
                members=tuple(active[i].node_id for i in [j]+into.get(j,[]));groups.append(Group(active[j].node_id,members));next_ids.append(active[j].node_id)
            sequences[key]=next_ids
            emit(context,self.spec.plugin_id,'memfolder.planning.tome_round',nodes=[n.node_id for n in active],reduction=reduction,
                 next_sequence=next_ids,pairs=[{'source':active[a].node_id,'target':active[b].node_id} for b,aa in into.items() for a in aa])
        plan=plan_groups(request,tuple(groups),method='memfolder.random_merge.round' if self.random_pairs else self.spec.plugin_id,input_view='current')
        return PlanningResult(plan=plan,next_state=AlgorithmState(schema='memfolder.tome.sequence',version=1,data=FrozenMap({'sequences':sequences})))
