"""Pinned local BGE-M3 vectors, precomputed before the GPU reranker starts."""
from contextlib import closing
import json
import math
import sqlite3
import time

from .dataset import batches, questions
from .io import save
from .providers import digest
from .runtime import ROOT, PACKAGE, PROTOCOL, EMBEDDING_MODEL_DIR

MANIFEST=json.loads((PACKAGE/'embedding_model.json').read_text(encoding='utf-8'))
CACHE=ROOT/'cache/memos_local_embeddings.sqlite'


def cache_key(text):
    return digest({'embedding':PROTOCOL['embedding'],'artifacts':MANIFEST,'text':text})


def validate(vector):
    if len(vector)!=1024 or not all(math.isfinite(x) for x in vector):
        raise RuntimeError('Invalid local BGE-M3 vector')
    if abs(sum(x*x for x in vector)-1)>1e-4:
        raise RuntimeError('Local BGE-M3 vector is not normalized')
    return vector


def get_vectors(texts):
    if not CACHE.is_file():raise RuntimeError('Precompute local embeddings before running MemOS')
    with closing(sqlite3.connect(CACHE.as_uri()+'?mode=ro',uri=True)) as db:
        result=[]
        for text in texts:
            row=db.execute('SELECT body,sha FROM vectors WHERE key=?',(cache_key(text),)).fetchone()
            if row is None:raise RuntimeError('Local embedding missing; rerun the embedding command')
            vector=json.loads(row[0])
            if digest(vector)!=row[1]:raise RuntimeError('Local embedding checksum mismatch')
            result.append(validate(vector))
        return result


def precompute():
    expected={'backend':'local','dtype':'float32','pooling':'cls','normalize':True,'normalization_passes':2,'strip_text':True,'query_instruction':None,'attention':'eager','tf32':False,'dimension':1024,'max_length':8192}
    if any(PROTOCOL['embedding'].get(k)!=v for k,v in expected.items()):
        raise RuntimeError('Unsupported local BGE-M3 configuration')
    # This fast reader preserves both turns verbatim. Native reader coverage
    # checks ensure that this prepared text matches the actual persisted node.
    dataset=json.loads((ROOT/'inputs/locomo10.json').read_text(encoding='utf-8'))
    texts=list(dict.fromkeys(
        [''.join(f"{m['role']}: [{m['chat_time']}]: {m['content']}\n" for m in b['messages']) for b in batches(dataset)]
        +[q['question'] for _,_,q in questions(dataset)]))
    CACHE.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(CACHE)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS vectors(key TEXT PRIMARY KEY,body TEXT NOT NULL,sha TEXT NOT NULL)')
        existing={row[0] for row in db.execute('SELECT key FROM vectors')}
        pending=[text for text in texts if cache_key(text) not in existing]
        report={'status':'running','phase':'local_bge_embedding','total_texts':len(texts),'completed_texts':len(texts)-len(pending),'model_revision':MANIFEST['revision']}
        path=ROOT/'reports/memos_locomo/embedding_service.json'
        save(path,report)
        if pending:
            from .prepare import sha
            for name,meta in MANIFEST['files'].items():
                if sha(EMBEDDING_MODEL_DIR/name)!=meta['sha256']:raise RuntimeError('Unverified BGE-M3 artifact: '+name)
            import torch
            from transformers import AutoModel,AutoTokenizer
            if not torch.cuda.is_available():raise RuntimeError('CUDA required for local FP32 BGE-M3')
            torch.set_num_threads(1);torch.manual_seed(0)
            torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
            tokenizer=AutoTokenizer.from_pretrained(EMBEDDING_MODEL_DIR,local_files_only=True)
            model=AutoModel.from_pretrained(EMBEDDING_MODEL_DIR,torch_dtype=torch.float32,device_map='cuda',
                low_cpu_mem_usage=True,attn_implementation='eager',local_files_only=True).eval()
            started=time.monotonic();size=PROTOCOL['embedding']['batch_size']
            # SentenceTransformer.encode sorts by text length before batching.
            pending.sort(key=len,reverse=True)
            for start in range(0,len(pending),size):
                batch=pending[start:start+size]
                # SentenceTransformer's Transformer.tokenize strips each text.
                model_texts=[text.strip() for text in batch]
                # Fail on unsupported input rather than silently truncating.
                if max(len(ids) for ids in tokenizer(model_texts)['input_ids'])>PROTOCOL['embedding']['max_length']:
                    raise RuntimeError('Memory exceeds the configured BGE-M3 input length')
                tokens=tokenizer(model_texts,padding=True,truncation=False,return_tensors='pt').to('cuda')
                with torch.inference_mode():
                    vectors=model(**tokens).last_hidden_state[:,0].float()
                    # The checkpoint includes a Normalize module; encode(...,
                    # normalize_embeddings=True) applies normalization again.
                    for _ in range(PROTOCOL['embedding']['normalization_passes']):
                        vectors=torch.nn.functional.normalize(vectors,p=2,dim=1)
                    vectors=vectors.cpu().tolist()
                for text,vector in zip(batch,vectors,strict=True):
                    validate(vector)
                    db.execute('INSERT OR IGNORE INTO vectors VALUES(?,?,?)',(cache_key(text),json.dumps(vector),digest(vector)))
                db.commit()
                report.update(completed_texts=len(texts)-len(pending)+min(start+size,len(pending)),elapsed_seconds=time.monotonic()-started)
                save(path,report)
            report.update(device=torch.cuda.get_device_name(0),dtype=str(next(model.parameters()).dtype),peak_gpu_mib=torch.cuda.max_memory_allocated()/1024**2)
        # Revalidate resumed values too; a cache hit must be a real vector.
        get_vectors(texts)
        report.update(status='complete',completed_texts=len(texts))
        save(path,report)
        print(json.dumps(report),flush=True)
