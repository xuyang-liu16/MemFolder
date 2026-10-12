"""Provider-neutral services, explicit environments and content-addressed caches."""
from dataclasses import dataclass
from pathlib import Path
import asyncio
import json
import os
import sqlite3
from contextlib import closing
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit
from .core import FrozenMap,fingerprint,to_data,ContractError
from .core.values import require
from .planning.common import spec,resolve
from .artifacts import parse_json


@dataclass(frozen=True)
class CompatibleHTTP:
    base_url: str
    model: str
    api_key_env: str = 'OPENAI_API_KEY'
    timeout_seconds: float = 60.
    revision: str = 'caller-declared'
    max_response_bytes: int = 32*1024*1024
    spec=spec('service.compatible_http','service')
    def __post_init__(self):
        url=urlsplit(self.base_url)
        require(url.scheme in ('http','https') and url.netloc and url.username is None and not url.query and not url.fragment,'Invalid provider URL')
        require(bool(self.model) and self.timeout_seconds>0 and self.max_response_bytes>0,'Invalid provider limits/model')
    @property
    def cache_identity(self):return fingerprint((self.base_url,self.model,self.revision))
    def _post(self,path,payload):
        key=os.environ.get(self.api_key_env,'');require(bool(key),'Missing provider key environment variable: '+self.api_key_env)
        request=Request(self.base_url.rstrip('/')+'/'+path,data=json.dumps(payload,allow_nan=False).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        try:
            with urlopen(request,timeout=self.timeout_seconds) as response:
                raw=response.read(self.max_response_bytes+1)
                require(len(raw)<=self.max_response_bytes,'Provider response exceeds limit')
                return parse_json(raw.decode('utf-8'))
        except (HTTPError,URLError,TimeoutError,OSError):
            raise ContractError('Provider request failed; inspect endpoint/credentials outside run artifacts') from None
    async def complete(self,request):
        payload={'model':self.model,'messages':[{'role':request.message_role,'content':request.prompt}],'temperature':request.temperature}
        if request.max_tokens is not None:payload['max_tokens']=request.max_tokens
        if request.response_format is not None:payload['response_format']={'type':request.response_format}
        response=await asyncio.to_thread(self._post,'chat/completions',payload)
        require(type(response) is dict and len(response.get('choices',[]))==1,'Invalid chat response')
        text=response['choices'][0]['message']['content'];require(type(text) is str and text.strip(),'Empty/nontext provider response');return text
    async def encode(self,texts):
        require(all(type(t) is str for t in texts),'Encoder requires text inputs')
        if not texts:return ()
        response=await asyncio.to_thread(self._post,'embeddings',{'model':self.model,'input':list(texts)})
        rows=response.get('data',[]);require(len(rows)==len(texts) and {r['index'] for r in rows}==set(range(len(texts))),'Misaligned embedding response')
        values=tuple(tuple(float(v) for v in row['embedding']) for row in sorted(rows,key=lambda r:r['index']))
        FrozenMap({'vectors':values});require(all(values),'Empty embedding response');return values


def cache_get(path,key):
    with closing(sqlite3.connect(path,timeout=30)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, value TEXT NOT NULL, digest TEXT NOT NULL)')
        row=db.execute('SELECT value,digest FROM responses WHERE key=?',(key,)).fetchone()
        if row is None:return None
        value=parse_json(row[0]);require(fingerprint(value)==row[1],'Cache checksum mismatch');return value


def cache_put(path,key,value):
    value=to_data(FrozenMap({'value':value}))['value']
    with closing(sqlite3.connect(path,timeout=30)) as db:
        db.execute('INSERT OR IGNORE INTO responses VALUES (?,?,?)',(key,json.dumps(value,ensure_ascii=False,allow_nan=False),fingerprint(value)))
        db.commit()


@dataclass(frozen=True)
class CachedService:
    provider: object
    path: Path
    namespace: str
    spec=spec('service.cached','service')
    def __post_init__(self):
        require(bool(self.namespace),'Cache requires explicit model/revision namespace')
        Path(self.path).parent.mkdir(parents=True,exist_ok=True)
    @property
    def cache_identity(self):return fingerprint((self.namespace,getattr(self.provider,'cache_identity',self.namespace)))
    async def complete(self,request):
        key=fingerprint((self.cache_identity,'chat',request.role,request.prompt,request.max_tokens,
                         request.temperature,request.message_role,request.response_format,request.prompt_id))
        value=await asyncio.to_thread(cache_get,self.path,key)
        if value is None:
            value=await resolve(self.provider.complete(request));require(type(value) is str and value.strip(),'Invalid cached chat result')
            await asyncio.to_thread(cache_put,self.path,key,value)
        require(type(value) is str,'Cache response type mismatch');return value
    async def encode(self,texts):
        # Store individual inputs so different batches reuse the same embeddings.
        keys=[fingerprint((self.cache_identity,'embedding',text)) for text in texts]
        values=[await asyncio.to_thread(cache_get,self.path,key) for key in keys]
        missing=[i for i,v in enumerate(values) if v is None]
        if missing:
            new=await resolve(self.provider.encode(tuple(texts[i] for i in missing)))
            require(len(new)==len(missing),'Cached encoder alignment mismatch')
            for i,vector in zip(missing,new):
                values[i]=list(vector);await asyncio.to_thread(cache_put,self.path,keys[i],values[i])
        return tuple(tuple(v) for v in values)
    async def close(self):
        if callable(getattr(self.provider,'close',None)):await resolve(self.provider.close())


@dataclass(frozen=True)
class TiktokenCounter:
    encoding: str = 'cl100k_base'
    spec=spec('service.tiktoken','service')
    @property
    def measurement_id(self):return 'tiktoken:'+self.encoding
    def count(self,text):
        import tiktoken
        return len(tiktoken.get_encoding(self.encoding).encode(text,disallowed_special=()))


class MeteredService:
    """Count calls/durations without serializing prompts, responses or credentials."""
    def __init__(self,provider):self.provider=provider;self.calls={};self.failed={};self.seconds={}
    def __getattr__(self,name):
        method=getattr(self.provider,name)
        if name not in ('complete','encode'):return method
        async def call(*args,**kwargs):
            from time import perf_counter
            start=perf_counter();self.calls[name]=self.calls.get(name,0)+1
            try:return await resolve(method(*args,**kwargs))
            except Exception:
                self.failed[name]=self.failed.get(name,0)+1;raise
            finally:self.seconds[name]=self.seconds.get(name,0.)+perf_counter()-start
        return call
    def report(self):return {'calls':dict(self.calls),'failed':dict(self.failed),'seconds':dict(self.seconds),'provider_token_usage':None}
