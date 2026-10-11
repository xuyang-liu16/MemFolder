"""Private FP32 BGE cross-encoder service; fail visibly rather than silently score zero."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .runtime import ROOT,PACKAGE,PROTOCOL,MODEL_DIR,RERANKER_PORT,OWNER,initialize
from .io import save as save_json
initialize()
import torch
from transformers import AutoModelForSequenceClassification,AutoTokenizer
CONFIG={'port':RERANKER_PORT,'revision':json.loads((PACKAGE/'model.json').read_text())['revision'],'max_length':PROTOCOL['reranker']['max_length'],'batch_size':PROTOCOL['reranker']['batch_size']}
REPORT=ROOT/'reports/memos_locomo/reranker_service.json'
LOCK = threading.Lock()
STATE = {'status':'loading','pid':os.getpid(),'port':CONFIG['port'],'model_revision':CONFIG['revision'],
         'dtype':'float32','max_length':CONFIG['max_length'],'batch_size':CONFIG['batch_size'],
         'owner':OWNER,'execution_mode':'fp32_cuda','completed_requests':0,'computed_pairs':0,'cache_hits':0,'failed_requests':0}

def save():
    STATE['updated_at']=time.strftime('%Y-%m-%d %H:%M:%S')
    save_json(REPORT,STATE,telemetry=True)

def cache_key(query,document):
    return hashlib.sha256(json.dumps([CONFIG['revision'],'float32',CONFIG['max_length'],query,document],ensure_ascii=False).encode()).hexdigest()

def score(query,documents,use_cache=True):
    # One bounded GPU worker; callers may overlap HTTP/QA without model duplicates.
    with LOCK:
        started=time.monotonic()
        scores=[]
        pending=[]
        for i,doc in enumerate(documents):
            key=cache_key(query,doc)
            row=CACHE.execute('SELECT score FROM pairs WHERE key=?',(key,)).fetchone() if use_cache else None
            scores.append(row[0] if row else None)
            if row:STATE['cache_hits']+=1
            else:pending.append((i,key,doc))
        for start in range(0,len(pending),CONFIG['batch_size']):
            batch=pending[start:start+CONFIG['batch_size']]
            pairs=[[query,entry[2]] for entry in batch]
            inputs=TOKENIZER(pairs,padding=True,truncation=True,return_tensors='pt',max_length=CONFIG['max_length']).to('cuda')
            with torch.inference_mode():
                values=torch.sigmoid(MODEL(**inputs).logits.view(-1).float()).cpu().tolist()
            for (i,key,_),value in zip(batch,values,strict=True):
                if not 0<=value<=1:raise RuntimeError('Nonfinite reranker score')
                scores[i]=float(value)
                CACHE.execute('INSERT OR REPLACE INTO pairs(key,score) VALUES(?,?)',(key,float(value)))
            CACHE.commit()
            STATE['computed_pairs']+=len(batch)
        STATE['completed_requests']+=1
        STATE['last_request_seconds']=time.monotonic()-started
        STATE['last_documents']=len(documents)
        STATE['peak_gpu_allocated_mib']=torch.cuda.max_memory_allocated()/1024**2
        save()
        return scores

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send_json(self,code,payload):
        body=json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path=='/health':self.send_json(200,dict(STATE))
        else:self.send_json(404,{'error':'unknown endpoint'})
    def do_POST(self):
        if self.path=='/shutdown':
            if self.headers.get('X-MemFolder-Owner')!=OWNER or not OWNER:self.send_json(403,{'error':'ownership mismatch'});return
            self.send_json(200,{'status':'stopping'})
            threading.Thread(target=self.server.shutdown,daemon=True).start()
            return
        if self.path!='/rerank':self.send_json(404,{'error':'unknown endpoint'});return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=4*1024*1024:raise ValueError('Invalid request size')
            payload=json.loads(self.rfile.read(length))
            query=payload['query']; docs=payload['documents']
            if not isinstance(query,str) or not isinstance(docs,list) or not 1<=len(docs)<=256 or any(not isinstance(x,str) or not x for x in docs):
                raise ValueError('Invalid query/documents')
            values=score(query,docs)
            result={'results':[{'index':i,'relevance_score':v} for i,v in enumerate(values)],'model_revision':CONFIG['revision'],'dtype':'float32','max_length':CONFIG['max_length']}
            self.send_json(200,result)
        except Exception as exc:
            with LOCK:
                STATE['failed_requests']+=1
                STATE['last_error_type']=type(exc).__name__
                save()
            self.send_json(500,{'error_type':type(exc).__name__})

def main():
    global TOKENIZER,MODEL,CACHE
    save()
    if not torch.cuda.is_available():raise RuntimeError('CUDA is required for the configured FP32 reranker')
    torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    torch.set_num_threads(1)
    verify=json.loads((PACKAGE/'model.json').read_text(encoding='utf-8'))
    for name,meta in verify['files'].items():
        p=MODEL_DIR/name
        h=hashlib.sha256()
        with p.open('rb') as stream:
            for chunk in iter(lambda:stream.read(4*1024*1024),b''):h.update(chunk)
        if h.hexdigest()!=meta['sha256']:raise RuntimeError('Unverified reranker artifact: '+name)
    TOKENIZER=AutoTokenizer.from_pretrained(str(MODEL_DIR),local_files_only=True)
    MODEL=AutoModelForSequenceClassification.from_pretrained(str(MODEL_DIR),torch_dtype=torch.float32,device_map='cuda',low_cpu_mem_usage=True,local_files_only=True).eval()
    assert next(MODEL.parameters()).dtype==torch.float32
    CACHE=sqlite3.connect(ROOT/'cache/memos_reranker.sqlite',check_same_thread=False)
    CACHE.execute('PRAGMA journal_mode=WAL')
    CACHE.execute('CREATE TABLE IF NOT EXISTS pairs(key TEXT PRIMARY KEY,score REAL NOT NULL)')
    STATE.update(status='ready',gpu_name=torch.cuda.get_device_name(0),torch_version=torch.__version__)
    save()
    print(json.dumps({'status':'ready','port':CONFIG['port'],'model_revision':CONFIG['revision']}),flush=True)
    ThreadingHTTPServer(('127.0.0.1',CONFIG['port']),Handler).serve_forever()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        STATE.update(status='failed',last_error_type=type(exc).__name__)
        save()
        raise
