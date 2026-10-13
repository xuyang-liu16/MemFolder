"""Optional native searches; canonical provenance/visibility remains authoritative."""

from dataclasses import dataclass
from math import sqrt
import re
from ..component_runtime import resolve, spec
from ..core import RetrievalHit, to_data
from ..core.values import require


def visible(node,question,*,require_as_of=True):
    if (node.scope.dataset_id,node.scope.sample_id)!=(question.sample.dataset_id,question.sample.sample_id):return False
    bounds=(node.available_at,node.expires_at)
    if any(bounds) and question.as_of is None:
        require(not require_as_of,'Time-bounded memory needs an as_of query or explicit whole-bank policy')
        return True
    for bound in bounds:
        if bound is not None:require(question.as_of is not None and bound.clock==question.as_of.clock,'Reader visibility clocks disagree')
    return (node.available_at is None or question.as_of.value>=node.available_at.value) and (node.expires_at is None or question.as_of.value<node.expires_at.value)


def hits(rows,view):
    return tuple(RetrievalHit(node_id=n.node_id,rank=i+1,origins=n.origins,score=float(score),
        backend_id=view.node_id_map[n.node_id]) for i,(n,score) in enumerate(rows))


@dataclass(frozen=True)
class LexicalRetriever:
    top_k: int = 10
    require_as_of: bool = True
    spec=spec('retrieval.lexical','retriever')
    def retrieve(self,question,view,context):
        require(type(self.top_k) is int and self.top_k>0,'Invalid top_k')
        words=set(re.findall(r'\w+',' '.join(p.text or '' for p in question.parts).casefold()))
        rows=[(n,len(words&set(re.findall(r'\w+',n.text.casefold())))) for n in view.snapshot.records
            if n.text and visible(n,question,require_as_of=self.require_as_of)]
        rows.sort(key=lambda row:(-row[1],row[0].node_id))
        return hits(rows[:self.top_k],view)


@dataclass(frozen=True)
class DenseRetriever:
    space: object
    service: str = 'embeddings'
    top_k: int = 10
    require_as_of: bool = True
    spec=spec('retrieval.dense','retriever')
    async def retrieve(self,question,view,context):
        require(type(self.top_k) is int and self.top_k>0 and self.space.metric in ('cosine','dot','euclidean'),'Invalid dense retrieval configuration')
        vectors=await resolve(context.services.require(self.service).encode((' '.join(p.text or '' for p in question.parts),)))
        require(len(vectors)==1 and len(vectors[0])==self.space.dimension,'Query embedding dimension mismatch')
        query=tuple(float(x) for x in vectors[0]);require(all(__import__('math').isfinite(x) for x in query),'Nonfinite query vector')
        rows=[]
        for n in view.snapshot.records:
            if not n.text or not visible(n,question,require_as_of=self.require_as_of):continue
            selected=[e for e in n.embeddings if e.space==self.space and e.values]
            require(len(selected)==1,'Reader requires content embeddings in the configured query model space')
            vector=selected[0].values;dot=sum(a*b for a,b in zip(query,vector))
            score=dot
            if self.space.metric=='cosine':
                denominator=sqrt(sum(v*v for v in query)*sum(v*v for v in vector));score=dot/denominator if denominator else 0.
            elif self.space.metric=='euclidean':score=-sqrt(sum((a-b)**2 for a,b in zip(query,vector)))
            rows.append((n,score))
        rows.sort(key=lambda row:(-row[1],row[0].node_id));return hits(rows[:self.top_k],view)


@dataclass(frozen=True)
class GraphExpansion:
    retriever: object = LexicalRetriever()
    hops: int = 1
    max_nodes: int = 32
    require_as_of: bool = True
    relations: tuple[str,...] = ()
    spec=spec('retrieval.graph_expansion','retriever')
    async def retrieve(self,question,view,context):
        require(type(self.hops) is int and self.hops>=0 and self.max_nodes>0,'Invalid graph expansion')
        seeds=await resolve(self.retriever.retrieve(question,view,context));nodes={n.node_id:n for n in view.snapshot.records}
        visited={h.node_id for h in seeds};ordered=[(nodes[h.node_id],h.score or 0.) for h in seeds]
        frontier=list(visited)
        for depth in range(self.hops):
            next_ids=set()
            for e in view.snapshot.edges:
                if self.relations and e.relation not in self.relations:continue
                if e.source_id in frontier:next_ids.add(e.target_id)
                if not e.directed and e.target_id in frontier:next_ids.add(e.source_id)
            frontier=[]
            for node_id in sorted(next_ids-visited):
                if len(ordered)>=self.max_nodes:break
                node=nodes[node_id]
                if visible(node,question,require_as_of=self.require_as_of):
                    visited.add(node_id);frontier.append(node_id);ordered.append((node,0.))
        return hits(ordered[:self.max_nodes],view)


@dataclass(frozen=True)
class TimeDecayRetriever:
    retriever: object = LexicalRetriever()
    rate: float = .01
    spec=spec('retrieval.time_decay','retriever')
    async def retrieve(self,question,view,context):
        require(self.rate>=0 and question.as_of is not None,'Time decay needs nonnegative rate and as_of')
        import math
        found=await resolve(self.retriever.retrieve(question,view,context));nodes={n.node_id:n for n in view.snapshot.records};rows=[]
        for hit in found:
            node=nodes[hit.node_id];points=[r.end for r in node.time_ranges]
            require(points and all(p.clock==question.as_of.clock for p in points),'Time decay requires event time in the query clock')
            age=max(0.,question.as_of.value-max(p.value for p in points))
            rows.append((node,(hit.score or 0.)*math.exp(-self.rate*age)))
        rows.sort(key=lambda row:(-row[1],row[0].node_id));return hits(rows,view)


def aligned(question,view,space,allow_unverified):
    nodes=[n for n in view.snapshot.records if n.text and visible(n,question)]
    for n in nodes:
        bound=any(e.space==space and e.values for e in n.embeddings)
        declared=n.native.get('embedding_spaces',{}).get(n.kind if view.framework_id=='m3' else 'default')
        from ..core import to_data
        require(bound or allow_unverified and to_data(declared)==to_data(space),'Native retrieval needs a matching content model or explicit unverified source declaration')
    return nodes


@dataclass(frozen=True)
class QdrantRetriever:
    space: object
    service: str = 'embeddings'
    top_k: int = 10
    allow_unverified: bool = False
    spec=spec('retrieval.qdrant','retriever')
    async def retrieve(self,question,view,context):
        require(view.framework_id=='mem0' and self.top_k>0,'Qdrant retriever needs Mem0 and positive top_k')
        nodes=aligned(question,view,self.space,self.allow_unverified)
        if not nodes:return ()
        vectors=await resolve(context.services.require(self.service).encode((' '.join(p.text or '' for p in question.parts),)))
        require(len(vectors)==1 and len(vectors[0])==self.space.dimension,'Native query embedding dimension mismatch')
        from ..wrappers import open_qdrant_view
        from qdrant_client import models
        client,collection=open_qdrant_view(context.services.require('materialized_root'))
        try:
            selected=client.query_points(collection_name=collection,query=list(vectors[0]),limit=self.top_k,
                query_filter=models.Filter(must=[models.HasIdCondition(has_id=[view.node_id_map[n.node_id] for n in nodes])])).points
            lookup={view.node_id_map[n.node_id]:n for n in nodes}
            return hits([(lookup[str(row.id)],row.score) for row in selected],view)
        finally:client.close()


@dataclass(frozen=True)
class M3NativeRetriever:
    space: object
    service: str = 'embeddings'
    graph_service: str = 'm3.graph_type'
    top_k: int = 10
    mode: str = 'max'
    allow_unverified: bool = False
    spec=spec('retrieval.m3_native','retriever')
    async def retrieve(self,question,view,context):
        require(view.framework_id=='m3' and self.top_k>0 and self.mode in ('mean','sum','max','min'),'Invalid M3 native retrieval configuration')
        nodes=aligned(question,view,self.space,self.allow_unverified)
        if not nodes:return ()
        vectors=await resolve(context.services.require(self.service).encode((' '.join(p.text or '' for p in question.parts),)))
        require(len(vectors)==1 and len(vectors[0])==self.space.dimension,'Native query embedding dimension mismatch')
        from ..wrappers import load_m3_view
        graph=load_m3_view(context.services.require('materialized_root'),context.services.require(self.graph_service))
        lookup={int(view.node_id_map[n.node_id]):n for n in nodes}
        graph.text_nodes=[i for i in graph.text_nodes if i in lookup]
        found=graph.search_text_nodes(vectors,mode=self.mode)
        return hits([(lookup[i],score) for i,score in found[:self.top_k]],view)


@dataclass(frozen=True)
class SDKRetriever:
    """Mem0/MemOS/M3/custom SDK bridge via a contributor-owned search service.

    search(question, view, allowed_native_ids, materialized_root) returns ordered
    {'id': native_id, 'score': number} rows; the caller owns credentials/client.
    """
    service: str = 'memory_search'
    top_k: int = 10
    spec=spec('retrieval.sdk_bridge','retriever')
    async def retrieve(self,question,view,context):
        require(self.top_k>0,'Invalid SDK top_k')
        nodes=[n for n in view.snapshot.records if visible(n,question)];lookup={view.node_id_map[n.node_id]:n for n in nodes}
        rows=await resolve(context.services.require(self.service).search(question,view,tuple(lookup),context.services.require('materialized_root')))
        require(all(type(r['id']) is str and r['id'] in lookup for r in rows) and len({r['id'] for r in rows})==len(rows),'SDK escaped visibility/identity or returned duplicates')
        return hits([(lookup[r['id']],r['score']) for r in rows[:self.top_k]],view)
