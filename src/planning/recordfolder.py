"""RecordFolder: independently replaceable planning stages."""
from __future__ import annotations
from .common import resolve

from dataclasses import dataclass, replace
from collections import defaultdict

from ..core import (Candidate, CandidateBatch, CandidateScore, ScoreBatch, GateBatch,
    GateDecision, CandidateSelection, FrozenMap, PlanningResult, fingerprint,
    validate_candidates, validate_scores, validate_gates, validate_selection)
from ..core.values import require
from .common import (Group, AnchorSelection,check_anchors,Geometry, check_groups, component_nodes, emit, feature,
    node_targets, numpy, plan_groups, spec, subset_request, selection_request, selection_required)
from ._density import cosine_distance, density_peaks, baseline_partition


@dataclass(frozen=True)
class DensityPeakAnchors:
    neighbor_k: int = 5
    feature_name: str = 'semantic'
    spec = spec('recordfolder.density_peaks', 'anchor_selector', diagnostics=('memfolder.planning.anchors',))

    def select(self, request, target, context):
        nodes = component_nodes(request)
        require(type(self.neighbor_k) is int and self.neighbor_k > 0, 'neighbor_k must be positive')
        operation = request.extensions.get('memfolder.selection', {}).get('operation', 'merge')
        require(0 <= target <= len(nodes), 'Selection target is outside node count')
        locked = selection_required(request, nodes, default='merge')
        locked_ids = {n.node_id for n in locked}
        active = tuple(n for n in nodes if n.node_id not in locked_ids)
        selected = [n.node_id for n in locked]
        count = target - len(locked)
        require(count >= (1 if active and operation == 'merge' else 0), 'Target cannot preserve protected nodes')
        if not active or count == 0:
            return AnchorSelection(request.snapshot.fingerprint,tuple(selected))
        if count == len(active):
            selected.extend(n.node_id for n in active)
        else:
            geometry = Geometry.of(request, active, self.feature_name)
            distance = cosine_distance(geometry.cosine)
            anchors = density_peaks(node_ids=geometry.node_ids, distance=distance, target=count, neighbor_k=self.neighbor_k)
            selected.extend(geometry.node_ids[a] for a in sorted(anchors))
        emit(context, self.spec.plugin_id, 'memfolder.planning.anchors', nodes=[n.node_id for n in nodes],
             selected_ids=selected)
        return AnchorSelection(request.snapshot.fingerprint,tuple(selected))


@dataclass(frozen=True)
class NearestAnchorAssignment:
    feature_name: str = 'semantic'
    spec = spec('recordfolder.nearest_anchor_assignment','group_assigner', diagnostics=('memfolder.planning.assignment',))
    def assign(self,request,selection,context):
        nodes=component_nodes(request);selected=set(selection.selected_ids)
        locked=tuple(n for n in nodes if not n.retention.may_merge)
        require(all(n.node_id in selected for n in locked),'Non-mergeable nodes must be selected anchors')
        groups=[Group(n.node_id,(n.node_id,)) for n in locked]
        active=tuple(n for n in nodes if n.retention.may_merge)
        if all(n.node_id in selected for n in active):
            return tuple(groups + [Group(n.node_id, (n.node_id,)) for n in active])
        if active:
            geometry=Geometry.of(request,active,self.feature_name)
            anchors=[i for i,n in enumerate(active) if n.node_id in selected]
            require(bool(anchors),'Mergeable nodes require an anchor')
            pi0=baseline_partition(node_ids=geometry.node_ids,distance=cosine_distance(geometry.cosine),anchors=anchors)
            groups.extend(Group(geometry.node_ids[a],tuple(geometry.node_ids[i] for i in ids)) for a,ids in sorted(pi0.items()))
        emit(context,self.spec.plugin_id,'memfolder.planning.assignment',nodes=[n.node_id for n in nodes],
             groups=[{'anchor_id':g.anchor_id,'member_ids':g.member_ids} for g in groups])
        return tuple(groups)


@dataclass(frozen=True)
class TemporalCandidates:
    window: int = 50
    feature_name: str = 'semantic'
    entity_feature: str = 'entities'
    temporal_feature: str = 'entities'  # row.values.event_time, or explicit canonical order
    temporal_order: str = 'event_time'
    use_entities: bool = True
    spec = spec('recordfolder.temporal_candidates', 'candidate_generator', diagnostics=('memfolder.planning.candidates',))

    def generate(self, request, context):
        np = numpy()
        require(type(self.window) is int and self.window > 0, 'window must be positive')
        require(self.temporal_order in ('event_time', 'order'), 'Choose event_time or order explicitly')
        nodes = tuple(n for n in component_nodes(request) if n.retention.may_merge)
        if len(nodes) < 2:
            return CandidateBatch(input_fingerprint=request.snapshot.fingerprint, candidates=())
        geometry = Geometry.of(request, nodes, self.feature_name)
        index = {i:p for p,i in enumerate(geometry.node_ids)}
        rows = {}
        if self.use_entities:
            rows = {r.node_id:r for r in feature(request, self.entity_feature, geometry.node_ids).rows}
            require(all('entities' in rows[i].values for i in geometry.node_ids), 'Entity features require explicit sets, including empty sets')
            require(all(isinstance(rows[i].values['entities'],(tuple,list)) for i in geometry.node_ids),'Entity sets must be arrays of keys')
        sets = {i: frozenset(rows[i].values['entities']) if rows else frozenset() for i in geometry.node_ids}
        require(all(all(type(x) is str for x in s) for s in sets.values()), 'Entity keys must be strings')
        frequency = defaultdict(int)
        for values in sets.values():
            for value in values:
                frequency[value] += 1
        weights = {e: float(np.log(len(nodes)/n)) for e,n in frequency.items()}
        if self.temporal_order == 'event_time':
            time_rows = {r.node_id:r for r in feature(request, self.temporal_feature, geometry.node_ids).rows}
            require(all(type(time_rows[i].values.get('event_time')) in (int,float) for i in geometry.node_ids),
                    'Provide parsed event_time features, or explicitly select temporal_order=order')
            clocks = {time_rows[i].values.get('clock') for i in geometry.node_ids}
            require(len(clocks) == 1 and None not in clocks, 'Temporal features must declare a common clock')
            order = sorted(geometry.node_ids, key=lambda i:(time_rows[i].values['event_time'], i))
        else:
            order = [n.node_id for n in sorted(nodes,key=lambda n:(n.order,n.node_id))]
        candidates = []
        for pos, successor in enumerate(order):
            for predecessor in order[max(0,pos-self.window):pos]:
                shared = sum(weights[e] for e in sorted(sets[predecessor] & sets[successor]))
                union = sum(weights[e] for e in sorted(sets[predecessor] | sets[successor]))
                cosine = float(np.dot(geometry.vectors[index[predecessor]], geometry.vectors[index[successor]]))
                candidates.append(Candidate(candidate_id='candidate.' + fingerprint((predecessor,successor))[:24],
                    source_id=predecessor, target_id=successor, values=FrozenMap({'shared_mass':shared,
                    'entity_similarity':shared/union if union>0 else 0., 'cosine':cosine})))
        batch = CandidateBatch(input_fingerprint=request.snapshot.fingerprint, candidates=tuple(candidates),
            extensions=FrozenMap({'memfolder.temporal_order':order}))
        emit(context,self.spec.plugin_id,'memfolder.planning.candidates',candidates=[c.candidate_id for c in candidates],
             rows=[{'candidate_id':c.candidate_id,'source':c.source_id,'target':c.target_id,**c.values} for c in candidates])
        return batch


@dataclass(frozen=True)
class FusedAffinity:
    mode: str = 'full'
    epsilon: float = 1e-6
    spec = spec('recordfolder.fused_affinity', 'affinity_scorer', diagnostics=('memfolder.planning.scores',))

    def score(self, request, candidates, context):
        np = numpy()
        require(self.mode in ('full','no_entity','no_semantic') and self.epsilon > 0, 'Invalid affinity configuration')
        rows = candidates.candidates
        e2 = max(float(np.var([c.values['entity_similarity'] for c in rows])),self.epsilon) if rows else self.epsilon
        s2 = max(float(np.var([c.values['cosine'] for c in rows])),self.epsilon) if rows else self.epsilon
        scores=[]
        for c in rows:
            mass,ent,cos = (c.values[k] for k in ('shared_mass','entity_similarity','cosine'))
            alpha = mass*s2/(mass*s2+e2)
            value = cos if self.mode=='no_entity' else (ent if mass>0 else 0.) if self.mode=='no_semantic' else alpha*ent+(1-alpha)*cos
            scores.append(CandidateScore(candidate_id=c.candidate_id,value=value,
                components=FrozenMap({'alpha':alpha,'entity_similarity':ent,'cosine':cos,'shared_mass':mass})))
        batch=ScoreBatch(candidate_fingerprint=fingerprint(candidates),scores=tuple(scores),
                         extensions=FrozenMap({'memfolder.variances':{'entity':e2,'semantic':s2}}))
        emit(context,self.spec.plugin_id,'memfolder.planning.scores',candidates=[s.candidate_id for s in scores],
            sigma_e2=e2,sigma_s2=s2,rows=[{'candidate_id':s.candidate_id,'value':s.value,**s.components} for s in scores])
        return batch


@dataclass(frozen=True)
class AnchorGate:
    mode: str = 'anchor'
    topk: int = 8
    spec = spec('recordfolder.anchor_gate', 'gate_policy', diagnostics=('memfolder.planning.gates',))

    def decide(self, request, scores, context):
        require(self.mode in ('anchor','none') and type(self.topk) is int and self.topk>0,'Invalid gate configuration')
        info=request.extensions['memfolder.recordfolder']
        anchors=set(info['anchors']); endpoints=info['endpoints']; baseline=info['baseline']
        eligible=defaultdict(list); gains={}
        for s in scores.scores:
            pred,succ=endpoints[s.candidate_id]
            gain=s.value-(baseline[succ] if self.mode=='anchor' else 0.)
            gains[s.candidate_id]=gain
            if succ not in anchors and gain>0:
                eligible[succ].append((s.candidate_id,pred,gain))
        accepted=set()
        for values in eligible.values():
            accepted.update(i for i,_,_ in sorted(values,key=lambda r:(-r[2],r[1]))[:self.topk])
        decisions=[]
        for s in scores.scores:
            succ=endpoints[s.candidate_id][1]
            reason='anchor_locked' if succ in anchors else 'nonpositive_gain' if gains[s.candidate_id]<=0 else 'accepted' if s.candidate_id in accepted else 'outside_topk'
            decisions.append(GateDecision(candidate_id=s.candidate_id,accepted=s.candidate_id in accepted,
                reason_codes=(reason,),thresholds=FrozenMap({'gain':gains[s.candidate_id],'baseline':baseline[succ]})))
        batch=GateBatch(score_fingerprint=fingerprint(scores),decisions=tuple(decisions))
        emit(context,self.spec.plugin_id,'memfolder.planning.gates',candidates=[d.candidate_id for d in decisions],
            rows=[{'candidate_id':d.candidate_id,'accepted':d.accepted,'reasons':d.reason_codes,**d.thresholds} for d in decisions])
        return batch


@dataclass(frozen=True)
class ChainMatcher:
    mode: str = 'hungarian'
    spec = spec('recordfolder.chain_matcher', 'matcher', diagnostics=('memfolder.planning.matching',))

    def match(self, request, candidates, scores, gates, context):
        require(self.mode in ('hungarian','greedy'),'Unknown matching mode')
        by_id={c.candidate_id:c for c in candidates.candidates}
        score={s.candidate_id:s.value for s in scores.scores}
        # Gate gain is the weight, never raw affinity when anchor gating is used.
        edges=[(by_id[d.candidate_id],d.thresholds.get('gain',score[d.candidate_id])) for d in gates.decisions if d.accepted]
        selected=[]
        if self.mode=='greedy':
            pred=set(); succ=set()
            for c,w in sorted(edges,key=lambda cw:(-cw[1],cw[0].source_id,cw[0].target_id)):
                if c.source_id not in pred and c.target_id not in succ:
                    pred.add(c.source_id);succ.add(c.target_id);selected.append(c.candidate_id)
        elif edges:
            try:
                from scipy.optimize import linear_sum_assignment
            except ImportError:
                from ..core import ContractError
                raise ContractError('Hungarian matching requires memfolder[algorithms]; greedy is a separate ablation') from None
            np=numpy(); order=candidates.extensions['memfolder.temporal_order']
            successors=[i for i in order if i not in request.extensions['memfolder.recordfolder']['anchors']]
            ri={i:p for p,i in enumerate(successors)}; ci={i:p for p,i in enumerate(order)}
            matrix=np.zeros((len(successors),len(order)),dtype=np.float64);lookup={}
            for c,w in edges:
                matrix[ri[c.target_id],ci[c.source_id]]=w;lookup[(ri[c.target_id],ci[c.source_id])]=c.candidate_id
            rows,cols=linear_sum_assignment(matrix,maximize=True)
            selected=[lookup[(int(r),int(c))] for r,c in zip(rows,cols) if matrix[r,c]>0 and (int(r),int(c)) in lookup]
        result=CandidateSelection(candidate_fingerprint=fingerprint(candidates),selected_ids=tuple(selected))
        emit(context,self.spec.plugin_id,'memfolder.planning.matching',candidates=selected,method=self.mode,
             total_gain=sum(w for c,w in edges if c.candidate_id in set(selected)))
        return result


@dataclass(frozen=True)
class ChainHosting:
    feature_name: str = 'semantic'
    spec = spec('recordfolder.chain_hosting', 'group_router', diagnostics=('memfolder.planning.hosting',))

    def route(self, request, base, candidates, selection, context):
        active=tuple(n for n in component_nodes(request) if n.retention.may_merge)
        if not selection.selected_ids:
            return base
        geometry=Geometry.of(request,active,self.feature_name); ix={i:p for p,i in enumerate(geometry.node_ids)}
        order=candidates.extensions['memfolder.temporal_order'];rank={i:p for p,i in enumerate(order)}
        anchors=[g.anchor_id for g in base if g.anchor_id in ix];aset=set(anchors)
        pi0={i:g.anchor_id for g in base for i in g.member_ids};parent={}
        def find(i):
            parent.setdefault(i,i)
            while parent[i]!=i:
                parent[i]=parent[parent[i]];i=parent[i]
            return i
        picked=set(selection.selected_ids)
        for c in candidates.candidates:
            if c.candidate_id in picked:
                a,b=find(c.source_id),find(c.target_id);parent[b]=a
        chains=defaultdict(list)
        for i in parent: chains[find(i)].append(i)
        chains=sorted((sorted(v,key=rank.__getitem__) for v in chains.values()),key=lambda c:(rank[c[0]],c[0]))
        members={g.anchor_id:set() for g in base}; heads={c[0] for c in chains if c[0] in aset}; chained=set(parent)
        for g in base:
            if g.anchor_id not in heads: members[g.anchor_id].add(g.anchor_id)
        for n in component_nodes(request):
            if n.node_id not in chained and n.node_id not in members: members[pi0[n.node_id]].add(n.node_id)
        hosts=[]
        for chain in chains:
            host=chain[0] if chain[0] in aset else max(anchors,key=lambda a:sum(float(geometry.vectors[ix[i]] @ geometry.vectors[ix[a]]) for i in chain))
            members[host].update(chain);hosts.append({'host':host,'chain':chain})
        groups=tuple(Group(g.anchor_id,tuple(sorted(members[g.anchor_id],key=lambda i:(rank.get(i,-1),i)))) for g in base)
        check_groups(component_nodes(request),groups,target=len(base))
        emit(context,self.spec.plugin_id,'memfolder.planning.hosting',nodes=list(parent),chains=hosts)
        return groups


@dataclass(frozen=True)
class RecordFolderPlanner:
    anchors: object = DensityPeakAnchors()
    assignment: object = NearestAnchorAssignment()
    candidates: object = TemporalCandidates()
    scorer: object = FusedAffinity()
    gate: object = AnchorGate()
    matcher: object = ChainMatcher()
    hosting: object = ChainHosting()
    rewrite_singletons: bool = False
    input_view: str = 'original'
    spec = spec('recordfolder', 'planner', actions=('keep','merge','rewrite'), diagnostics=('memfolder.compression.completed', 'memfolder.planning.plan'))

    async def plan(self, request, context):
        groups=[]
        for _,nodes,target in node_targets(request):
            if not nodes: continue
            require(len({n.scope for n in nodes})==1,'RecordFolder budget group must remain within one scope')
            local=selection_request(subset_request(request,nodes), 'merge')
            selection=await resolve(self.anchors.select(local,target,context));check_anchors(local,nodes,selection,target)
            require({n.node_id for n in selection_required(local,nodes)} <= set(selection.selected_ids), 'Selector omitted merge-protected anchors')
            base=await resolve(self.assignment.assign(local,selection,context))
            check_groups(nodes,base,target=target)
            if len(base)==len(nodes):
                groups.extend(base);continue
            candidates=await resolve(self.candidates.generate(local,context));validate_candidates(request.snapshot,candidates)
            if candidates.candidates:
                active_ids={n.node_id for n in nodes if n.retention.may_merge}
                order=candidates.extensions.get('memfolder.temporal_order', ())
                require(len(order)==len(active_ids) and len(set(order))==len(order) and set(order)==active_ids,
                        'Chain candidates must declare a complete local temporal order')
                rank={i:p for p,i in enumerate(order)}
                pairs=[(c.source_id,c.target_id) for c in candidates.candidates]
                require(len(set(pairs))==len(pairs), 'Duplicate candidate endpoints are ambiguous for chain matching')
                require(all(a in active_ids and b in active_ids and rank[a]<rank[b] for a,b in pairs),
                        'Chain candidates must stay within mergeable local nodes and point forward in time')
                geo=Geometry.of(local,tuple(n for n in nodes if n.retention.may_merge),getattr(self.hosting,'feature_name','semantic'))
                ix={i:p for p,i in enumerate(geo.node_ids)}; pi0={i:g.anchor_id for g in base for i in g.member_ids}
                baseline={i:float(geo.vectors[ix[i]] @ geo.vectors[ix[pi0[i]]]) for i in geo.node_ids}
                local=replace(local,extensions=FrozenMap({**local.extensions,'memfolder.recordfolder':{
                    'anchors':[g.anchor_id for g in base], 'baseline':baseline,
                    'endpoints':{c.candidate_id:[c.source_id,c.target_id] for c in candidates.candidates}}}))
                scores=await resolve(self.scorer.score(local,candidates,context));validate_scores(candidates,scores)
                gates=await resolve(self.gate.decide(local,scores,context));validate_gates(scores,gates)
                selection=await resolve(self.matcher.match(local,candidates,scores,gates,context));validate_selection(candidates,selection)
                accepted={d.candidate_id for d in gates.decisions if d.accepted}
                require(set(selection.selected_ids)<=accepted,'Matcher selected a rejected candidate')
                picked=[c for c in candidates.candidates if c.candidate_id in set(selection.selected_ids)]
                require(len({c.source_id for c in picked})==len(picked) and len({c.target_id for c in picked})==len(picked),
                        'Chain matcher must have at most one incoming and one outgoing edge per node')
                require(not {c.target_id for c in picked}&{g.anchor_id for g in base}, 'Chain matcher cannot absorb an anchor')
                base=await resolve(self.hosting.route(local,base,candidates,selection,context));check_groups(nodes,base,target=target)
            groups.extend(base)
        return PlanningResult(plan=plan_groups(request,tuple(groups),method=self.spec.plugin_id,
            rewrite_singletons=self.rewrite_singletons,input_view=self.input_view))


@dataclass(frozen=True)
class ContextFolderPlanner(RecordFolderPlanner):
    rewrite_singletons: bool = True
    spec = spec('contextfolder', 'planner', actions=('keep','merge','rewrite'), diagnostics=('memfolder.compression.completed', 'memfolder.planning.plan'))
