"""Meeting-defined memory ToMe: temporal halves with live pairwise contraction."""

from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, replace
from ..component_runtime import emit, spec
from .contracts import Group
from ..core import AlgorithmState, FrozenMap, PlanningResult
from ..core.values import require
from .plan_helpers import Geometry, component_nodes, feature, node_targets, numpy, plan_groups
from .record_selection import id_keys


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


def temporal_key(node):
    clocks = {r.start.clock for r in node.time_ranges}
    require(len(clocks) <= 1, 'Temporal ToMe cannot compare multiple clocks')
    # An explicitly ordered dataset without event times may use its ordinal clock.
    value = max((r.start.value for r in node.time_ranges), default=node.order)
    return value, node.order, node.node_id


@dataclass(frozen=True)
class TemporalTomePlanner:
    feature_name: str = 'semantic'
    spec = spec('tome.temporal_half.dynamic_pair.v1', 'planner',
        actions=('keep', 'merge'), modes=('repeat',),
        diagnostics=('memfolder.planning.tome_temporal_pair', 'memfolder.planning.plan',
                     'memfolder.compression.completed'))

    async def plan(self, request, context):
        previous = {}
        if request.state is not None:
            require(request.state.schema == 'memfolder.tome.temporal_half'
                    and request.state.version == 1, 'Wrong temporal ToMe state')
            previous = request.state.data['groups']
        groups, states, selected = [], {}, {}
        np = numpy()
        for key, nodes, target in node_targets(request):
            require(len({n.scope for n in nodes}) <= 1, 'ToMe cannot merge across scopes')
            locked = [n for n in nodes if not n.retention.may_merge]
            active = sorted((n for n in nodes if n.retention.may_merge), key=temporal_key)
            clocks = {r.start.clock for n in active for r in n.time_ranges}
            require(len(clocks) <= 1 and (not clocks or all(n.time_ranges for n in active)),
                    'Temporal ToMe needs comparable event times or all-ordinal ordering')
            keep = target - len(locked)
            require(keep >= (1 if active else 0), 'Protected nodes make ToMe budget unreachable')
            groups.extend(Group(n.node_id, (n.node_id,)) for n in locked)
            ids = {n.node_id for n in active}
            prior = previous.get(key)
            if prior is not None:
                require(set(prior['sources']) | set(prior['destinations']) == ids
                        and len(prior['sources']) + len(prior['destinations']) == len(ids),
                        'Stale temporal ToMe state')
            if len(active) <= keep:
                groups.extend(Group(n.node_id, (n.node_id,)) for n in active)
                continue
            if prior is None or not prior['sources']:
                split = len(active) // 2
                sources = [n.node_id for n in active[:split]]
                destinations = [n.node_id for n in active[split:]]
                pass_index = 0 if prior is None else prior['pass_index'] + 1
            else:
                sources, destinations = list(prior['sources']), list(prior['destinations'])
                pass_index = prior['pass_index']
            by_id = {n.node_id: n for n in active}
            source = by_id[sources[0]]
            targets = [by_id[i] for i in destinations]
            geometry = Geometry.of(request, [source, *targets], self.feature_name, dtype='float32')
            require(bool((np.linalg.norm(geometry.vectors, axis=1) > 0).all()),
                    'Temporal ToMe cannot match zero embeddings')
            scores = geometry.vectors[1:] @ geometry.vectors[0]
            # Destinations remain in chronological order: ties choose the first one.
            best = int(np.argmax(scores))
            destination = targets[best]
            require(temporal_key(source) <= temporal_key(destination),
                    'Temporal ToMe destination must be at least as recent as source')
            for n in active:
                if n.node_id == source.node_id:
                    continue
                members = (source.node_id, destination.node_id) if n.node_id == destination.node_id else (n.node_id,)
                groups.append(Group(n.node_id, members))
            states[key] = {'sources': sources[1:], 'destinations': destinations,
                           'pass_index': pass_index}
            selected[destination.node_id] = {'timestamp_policy': 'latest',
                'output_order': destination.order, 'source_id': source.node_id,
                'destination_id': destination.node_id, 'half_pass': pass_index,
                'selected_similarity': float(scores[best])}
            emit(context, self.spec.plugin_id, 'memfolder.planning.tome_temporal_pair',
                nodes=(source.node_id, destination.node_id), pass_index=pass_index,
                source_id=source.node_id, destination_id=destination.node_id,
                remaining_sources=len(sources)-1, destination_count=len(destinations),
                similarity=float(scores[best]), input_view='current', timestamp_policy='latest',
                source_content_fingerprint=source.content_fingerprint,
                destination_content_fingerprint=destination.content_fingerprint)
        plan = plan_groups(request, tuple(groups), method=self.spec.plugin_id, input_view='current')
        plan = replace(plan, actions=tuple(replace(a,
            parameters=FrozenMap({**a.parameters, **selected[a.output_ids[0]]}))
            if a.kind == 'merge' else a for a in plan.actions))
        return PlanningResult(plan=plan, next_state=AlgorithmState(
            schema='memfolder.tome.temporal_half', version=1,
            data=FrozenMap({'groups': states})))
