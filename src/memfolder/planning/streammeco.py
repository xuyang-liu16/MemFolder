"""Pinned official StreamMeCo graph pruning, decomposed into three plugins.

The official recipe has two class budgets, not one global exact K. Caller
budgets are checked after selection; incompatibilities are explicit errors.
"""
from __future__ import annotations
from .common import resolve
from dataclasses import dataclass
from collections import defaultdict
import math
from ..core import PlanningResult, validate_budget, fingerprint
from ..core.values import require
from .common import emit, feature, numpy, plan_prune, spec, ordered_nodes


@dataclass(frozen=True)
class MediaConnectivity:
    text_kinds: tuple[str,...] = ('episodic','semantic')
    media_kinds: tuple[str,...] = ('img','voice')
    spec = spec('streammeco.media_connectivity','graph_classifier', diagnostics=('memfolder.streammeco.classification',))
    def classify(self,request,context):
        nodes={n.node_id:n for n in request.snapshot.records}
        ordered=[n.node_id for n in ordered_nodes(request) if n.kind in self.text_kinds]
        require(set(ordered)=={n.node_id for n in ordered_nodes(request)},
                'StreamMeCo text kinds do not cover eligible nodes; supply an explicit classifier for another framework')
        weights=defaultdict(dict);processed=set()
        for e in request.snapshot.edges:
            pair=tuple(sorted((e.source_id,e.target_id)))
            if pair in processed:continue  # original M3 stores both orientations
            processed.add(pair);a,b=nodes[e.source_id],nodes[e.target_id]
            text,media=(a,b) if a.kind in self.text_kinds and b.kind in self.media_kinds else (b,a)
            if text.node_id in set(ordered) and media.kind in self.media_kinds:
                require((text.scope.dataset_id,text.scope.sample_id)==(media.scope.dataset_id,media.scope.sample_id),'Graph media edge crosses samples')
                weights[text.node_id][media.node_id]=e.weight
        first=tuple(i for i in ordered if i not in weights);second=tuple(i for i in ordered if i in weights)
        emit(context,self.spec.plugin_id,'memfolder.streammeco.classification',nodes=ordered,
             no_media=first,with_media=second,media_weights={i:dict(v) for i,v in weights.items()})
        return first,second,{i:sum(v.values()) for i,v in weights.items()}


@dataclass(frozen=True)
class SphericalCoverage:
    feature_name: str = 'semantic'
    cluster_ratio: float = .05
    keep_ratio: float = .7
    spec = spec('streammeco.spherical_coverage','graph_selector', diagnostics=('memfolder.streammeco.first_class',))
    def select(self,request,ids,context):
        from ._streammeco import _select_via_spherical_kmeans
        require(0<self.cluster_ratio<=1 and 0<self.keep_ratio<=1,'Invalid StreamMeCo first-class ratios')
        np=numpy();batch=feature(request,self.feature_name,())
        require(batch.space is not None and batch.space.metric=='cosine','StreamMeCo needs a declared cosine feature space')
        vectors={r.node_id:r.vector for r in batch.rows};nodes={n.node_id:n for n in request.snapshot.records}
        by_clip=defaultdict(list)
        for i in ids:by_clip[nodes[i].scope].append(i)
        kept=set()
        for scope,group in by_clip.items():
            candidates=[i for i in group if vectors.get(i)]
            kept.update(i for i in group if not vectors.get(i))  # official missing-embedding policy
            if candidates:
                values=[np.asarray(vectors[i],dtype=np.float32) for i in candidates]
                require(all(v.shape==(batch.space.dimension,) for v in values),'StreamMeCo feature dimensions mismatch')
                chosen=_select_via_spherical_kmeans(candidates,values,self.cluster_ratio,self.keep_ratio)
                kept.update(chosen)
        emit(context,self.spec.plugin_id,'memfolder.streammeco.first_class',nodes=ids,retained=sorted(kept),
             cluster_ratio=self.cluster_ratio,keep_ratio=self.keep_ratio)
        return frozenset(kept)


@dataclass(frozen=True)
class ImportanceDiversity:
    feature_name: str = 'semantic'
    alpha: float = .1
    keep_ratio: float = .7
    spec = spec('streammeco.importance_diversity','graph_selector', diagnostics=('memfolder.streammeco.second_class',))
    def select(self,request,ids,importance,context):
        from ._streammeco import _assign_rank_weights
        require(0<=self.alpha<=1 and 0<self.keep_ratio<=1,'Invalid StreamMeCo second-class parameters')
        if not ids:return frozenset()
        np=numpy();batch=feature(request,self.feature_name,())
        require(batch.space is not None and batch.space.metric=='cosine','StreamMeCo needs a declared cosine feature space')
        vectors={r.node_id:r.vector for r in batch.rows};nodes={n.node_id:n for n in request.snapshot.records}
        by_sample=defaultdict(list)
        for i in ids:by_sample[(nodes[i].scope.dataset_id,nodes[i].scope.sample_id)].append(i)
        retained=set()
        for group in by_sample.values():
            data=np.asarray([vectors.get(i) or (0.,)*batch.space.dimension for i in group],dtype=np.float32)
            require(data.shape==(len(group),batch.space.dimension),'Reject mixed embedding spaces; use an explicit feature adapter')
            norms=np.linalg.norm(data,axis=1,keepdims=True);data=data/np.where(norms==0,1,norms)
            similarity=(data @ data.T).sum(axis=1)
            iw=_assign_rank_weights({i:importance.get(i,0.) for i in group})
            sw=_assign_rank_weights({i:float(v) for i,v in zip(group,similarity)},invert=True)
            scores={i:self.alpha*iw[i]+(1-self.alpha)*sw[i] for i in group};positions={i:p for p,i in enumerate(group)}
            ranking=sorted(group,key=lambda i:(-scores[i],positions[i]));keep=max(1,math.ceil(len(group)*self.keep_ratio))
            retained.update(ranking[:keep])
            emit(context,self.spec.plugin_id,'memfolder.streammeco.second_class',nodes=group,
                importance=iw,dissimilarity=sw,combined=scores,ranking=ranking,retained=ranking[:keep])
        return frozenset(retained)


@dataclass(frozen=True)
class StreamMeCoPlanner:
    classifier: object = MediaConnectivity()
    first_selector: object = SphericalCoverage()
    second_selector: object = ImportanceDiversity()
    spec = spec('streammeco.official_graph_pruning','planner',actions=('keep','drop'),modes=('once','stream'), diagnostics=('memfolder.compression.completed', 'memfolder.planning.plan'))
    async def plan(self,request,context):
        first,second,weights=await resolve(self.classifier.classify(request,context))
        nodes=ordered_nodes(request);ids={n.node_id for n in nodes}
        require(not set(first)&set(second) and set(first)|set(second)==ids,'Graph classifier must partition eligible nodes')
        kept_first=set(await resolve(self.first_selector.select(request,first,context)))
        kept_second=set(await resolve(self.second_selector.select(request,second,weights,context)))
        require(kept_first<=set(first) and kept_second<=set(second), 'Graph selector crossed its declared class')
        retained=kept_first|kept_second
        retained.update(n.node_id for n in nodes if not n.retention.may_drop)
        require(retained<=ids,'Graph selector returned unknown node IDs')
        for b in request.budgets:
            require(b.request.unit=='nodes','StreamMeCo official recipe only supports node budget checks')
            realized={t.group.group_id:len(set(t.group.member_ids)&retained) for t in b.targets}
            validate_budget(b,realized)
        return PlanningResult(plan=plan_prune(request,retained,method=self.spec.plugin_id))
