"""Experiment wrapper around unmodified MemOS 2.0.33 native reader/tree/searcher.

Only transports and process ownership are local. No benchmark answers enter
the reader or retrieval, no scheduler/compression/AGPR or internet expansion.
"""
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import threading
import uuid

from .providers import MODEL, digest, client_proxy
from .runtime import ROOT, UPSTREAM, PROTOCOL, PORT, USER, DATABASE, RERANKER_PORT, CHAT_URL
from memos.configs.embedder import BaseEmbedderConfig, EmbedderConfigFactory
from memos.embedders.base import BaseEmbedder
from memos.embedders.factory import EmbedderFactory
from memos.configs.mem_reader import SimpleStructMemReaderConfig
from memos.configs.memory import TreeTextMemoryConfig
from memos.mem_reader.simple_struct import SimpleStructMemReader
from memos.memories.textual.item import TextualMemoryItem
from memos.memories.textual.tree import TreeTextMemory
from memos.reranker.http_bge import HTTPBGEReranker
from memos.api.handlers.formatters_handler import format_memory_item, post_process_textual_mem, rerank_knowledge_mem

TRANSPORT=None
PROVIDER_ERRORS=[]
ERR_LOCK=threading.Lock()

from .io import save as _save

def save(path,value):
    return _save(path,value,telemetry=Path(path).name=='status.json')

class BGEConfig(BaseEmbedderConfig):pass
class BGEAPI(BaseEmbedder):
    def __init__(self,config):self.config=config
    def embed(self,texts):
        try:return TRANSPORT.embed(texts)
        except Exception as exc:
            with ERR_LOCK:PROVIDER_ERRORS.append(('embedding',type(exc).__name__))
            raise

class StrictReranker(HTTPBGEReranker):
    def rerank(self,*args,**kwargs):
        try:
            # The upstream decorator hides service failures as zero-score answers.
            # Execute the unchanged scoring method with its exception fallback disabled.
            method=HTTPBGEReranker.rerank.__wrapped__
            result=method(self,*args,**kwargs)
            if any(not math.isfinite(score) or not 0<=score<=1 for _,score in result):raise RuntimeError('Invalid reranker score')
            return result
        except Exception as exc:
            with ERR_LOCK:PROVIDER_ERRORS.append(('reranker',type(exc).__name__))
            raise

def new_native(transport):
    global TRANSPORT
    TRANSPORT=transport
    EmbedderConfigFactory.backend_to_class['memos_bge_api']=BGEConfig
    EmbedderFactory.backend_to_class['memos_bge_api']=BGEAPI
    for name in ['memos','httpx','httpcore']:logging.getLogger(name).setLevel(logging.ERROR)
    llm={'backend':'openai','config':{'model_name_or_path':MODEL,'api_key':os.environ['MEMFOLDER_CHAT_KEY'],'api_base':CHAT_URL,'temperature':0.0,'max_tokens':2048,'top_p':1.0}}
    embedding={'backend':'memos_bge_api','config':{'model_name_or_path':'bge-m3','embedding_dims':1024}}
    reader=SimpleStructMemReader(SimpleStructMemReaderConfig(llm=llm,embedder=embedding,
        chunker={'backend':'sentence','config':{'tokenizer_or_token_counter':'character','chunk_size':512,'chunk_overlap':0,'save_rawfile':False}},chat_window_max_tokens=8192))
    tree=TreeTextMemory(TreeTextMemoryConfig(extractor_llm=llm,dispatcher_llm=llm,embedder=embedding,
        graph_db={'backend':'postgres','config':{'host':'127.0.0.1','port':PORT,'user':USER,'password':'','db_name':DATABASE,'schema_name':'memos','user_name':'memfolder_locomo','embedding_dimension':1024,'use_multi_db':False,'maxconn':40}},
        reranker={'backend':'http_bge','config':{'url':f'http://127.0.0.1:{RERANKER_PORT}/rerank','model':'bge-reranker-v2-m3','timeout':120}},
        search_strategy={'bm25':False,'cot':False,'fast_graph':False,'fulltext':False},mode='sync',reorganize=False,
        memory_size={'WorkingMemory':20,'LongTermMemory':10000,'UserMemory':10000,'RawFileMemory':10000},include_embedding=False))
    # Upstream's factory caches identical LLM configs. Replace each shared
    # object once so closing one client's connection does not close its proxy.
    replaced=set()
    for llm_obj in [reader.llm,tree.extractor_llm,tree.dispatcher_llm]:
        if id(llm_obj) in replaced:continue
        replaced.add(id(llm_obj))
        if callable(getattr(llm_obj.client,'close',None)):llm_obj.client.close()
        llm_obj.client=client_proxy(transport,kind='memos_native_dispatch')
    tree.reranker=StrictReranker(f'http://127.0.0.1:{RERANKER_PORT}/rerank',model='bge-reranker-v2-m3',timeout=120,boost_weights={})
    return reader,tree

from .dataset import batches

def build_batch(reader,tree,batch):
    path=ROOT/'runs/memos_locomo/reader_receipts'/(batch['identity']+'.json')
    if path.exists():
        saved=json.loads(path.read_text(encoding='utf-8'))
        if saved['identity']!=batch['identity']:raise RuntimeError('Reader receipt identity mismatch')
        items=[TextualMemoryItem(**row) for row in saved['nodes']]
    else:
        groups=reader.get_memory([batch['messages']],type='chat',info={'user_id':batch['uid'],'session_id':batch['session']},mode='fast',user_name=batch['uid'])
        items=[item for group in groups for item in group]
        if not items:raise RuntimeError('Native reader silently lost a batch')
        for index,item in enumerate(items):
            item.id=str(uuid.uuid5(uuid.NAMESPACE_URL,batch['identity']+'/'+str(index)))
            if not item.metadata.embedding or len(item.metadata.embedding)!=1024:raise RuntimeError('Native reader lost vector')
        if len(items)!=1:raise RuntimeError('Unexpected multiple windows in a two-turn batch; protocol review needed')
        for message in batch['messages']:
            if message['content'] not in items[0].memory or message['chat_time'] not in items[0].memory:raise RuntimeError('Raw two-turn input/timestamp not preserved')
        save(path,{'identity':batch['identity'],'messages':batch['messages'],'user_name':batch['uid'],'nodes':[i.model_dump(mode='json') for i in items]})
    existing=tree.graph_store.get_nodes([i.id for i in items],user_name=batch['uid'])
    if existing:
        if {r['id'] for r in existing}!={i.id for i in items} or {r['id']:r['memory'] for r in existing}!={i.id:i.memory for i in items}:raise RuntimeError('Existing memory differs from durable reader receipt')
    else:
        ids=tree.add(items,user_name=batch['uid'])
        if set(ids)!={i.id for i in items}:raise RuntimeError('Native tree add lost/duplicated memory')
    if PROVIDER_ERRORS:raise RuntimeError('Provider error was hidden by upstream reader')
    return [i.id for i in items]

def retrieve(tree,query,uid):
    # Instantiate the same upstream searcher used by TreeTextMemory.search,
    # retaining it for this request so its background thread pool can be closed.
    from memos.memories.textual.tree_text_memory.retrieve.advanced_searcher import AdvancedSearcher
    searcher=AdvancedSearcher(tree.dispatcher_llm,tree.graph_store,tree.embedder,tree.reranker,
        bm25_retriever=None,internet_retriever=None,search_strategy=tree.search_strategy,manual_close_internet=True,include_embedding=False)
    try:
        top_k=PROTOCOL['search']['top_k_per_speaker']
        items=searcher.search(query=query,top_k=top_k,info={'user_id':uid},mode='fast',memory_type='All',user_name=uid,
            include_preference_memory=PROTOCOL['search']['include_preference'],pref_mem_top_k=PROTOCOL['search']['pref_top_k'],dedup=PROTOCOL['search']['dedup'])
    finally:searcher._usage_executor.shutdown(wait=True)
    if PROVIDER_ERRORS:raise RuntimeError('Provider error was hidden by upstream search')
    if not items:raise RuntimeError('Native search returned empty context')
    if any(item.metadata.user_id!=uid for item in items):raise RuntimeError('Cross-speaker native search leakage')
    formatted=[format_memory_item(item) for item in items]
    result=post_process_textual_mem({'text_mem':[],'tool_mem':[],'skill_mem':[],'pref_mem':[],'pref_note':''},formatted,uid)
    result['text_mem']=rerank_knowledge_mem(tree.reranker,query,result['text_mem'],top_k=PROTOCOL['search']['top_k_per_speaker'])
    if len(result['text_mem'][0]['memories'])>PROTOCOL['search']['top_k_per_speaker']:raise RuntimeError('API result exceeded native top_k')
    return result

from .prompts import prompts,judge_messages
