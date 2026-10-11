"""Dedicated BGE/QA cache namespaces; never reuse small-model embeddings."""
from contextlib import closing
import json
import math
import os
import sqlite3
import threading
from .providers import Transport, digest
from .runtime import ROOT, CHAT_URL, EMBED_URL

class MemOSTransport(Transport):
    def __init__(self,concurrency=24):
        self.path=ROOT/'cache/memos_api.sqlite'
        self.lock=threading.Lock()
        self.slots=threading.BoundedSemaphore(concurrency)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        from openai import OpenAI
        self.chat_client=OpenAI(api_key=os.environ['MEMFOLDER_CHAT_KEY'],base_url=CHAT_URL,timeout=120,max_retries=0)
        self.embedding_client=OpenAI(api_key=os.environ['MEMFOLDER_EMBEDDING_KEY'],base_url=EMBED_URL,timeout=120,max_retries=0)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS responses(key TEXT PRIMARY KEY,kind TEXT,body TEXT,sha TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS audit(time REAL,kind TEXT,key TEXT,elapsed REAL,status TEXT,model TEXT,usage TEXT)')
            db.commit()
    def embed(self,texts):
        if isinstance(texts,str):texts=[texts]
        texts=list(texts)
        keys=[digest(('embedding',EMBED_URL,'bge-m3',text)) for text in texts]
        vectors=[self.get(key) for key in keys]
        missing=[i for i,x in enumerate(vectors) if x is None]
        for start in range(0,len(missing),32):
            indices=missing[start:start+32]
            response=self.retry(lambda:self.embedding_client.embeddings.create(model='bge-m3',input=[texts[i] for i in indices],encoding_format='float'),'bge_embedding',digest([keys[i] for i in indices]))
            rows=sorted(response.data,key=lambda x:x.index)
            if response.model!='bge-m3' or len(rows)!=len(indices) or [r.index for r in rows]!=list(range(len(indices))):raise RuntimeError('BGE model/count mismatch')
            for i,row in zip(indices,rows,strict=True):
                vector=row.embedding
                if len(vector)!=1024 or not all(math.isfinite(x) for x in vector) or sum(x*x for x in vector)<=0:raise RuntimeError('Invalid BGE vector')
                vectors[i]=vector
                self.put(keys[i],'bge_embedding',vector)
                # Concurrent duplicate requests use the first durably cached vector.
                vectors[i]=self.get(keys[i])
        return vectors
