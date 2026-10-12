"""Optional native searches; canonical provenance/visibility remains authoritative."""
from dataclasses import dataclass
from ..core.values import require
from ..planning.common import spec,resolve
from .retrieval import visible,hits


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
