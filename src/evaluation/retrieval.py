"""Retrieval is an independent plugin, with visibility checked before ranking."""
from dataclasses import dataclass
from math import sqrt
import re
from ..core import RetrievalHit, FrozenMap, to_data
from ..core.values import require
from ..planning.common import spec,resolve


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
