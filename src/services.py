"""Model calls, caches, token counting, LLMLingua-2 services and call metering."""

import asyncio
import inspect
import json
import os
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from functools import cached_property
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from .artifacts import parse_json
from .component_runtime import emit, resolve, spec
from .core import ContractError, FrozenMap, fingerprint, to_data
from .core.values import require


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


@dataclass(frozen=True)
class LLMLingua2Service:
    model_name: str = 'microsoft/llmlingua-2-xlm-roberta-large-meetingbank'
    revision: str = 'ebaba9b0e874dadd3003ffcff828e4397e568089'
    device_map: str = 'cuda'
    dtype: str = 'float16'
    max_batch_size: int = 16
    spec = spec('service.official_llmlingua2.v1', 'service')

    def __post_init__(self):
        require(bool(self.model_name) and bool(self.revision) and bool(self.device_map),
                'Declare LLMLingua-2 model, revision and device')
        require(self.dtype in ('float16', 'float32', 'bfloat16'), 'Invalid LLMLingua-2 dtype')
        require(type(self.max_batch_size) is int and self.max_batch_size > 0,
                'LLMLingua-2 batch size must be positive')
        object.__setattr__(self, '_lock', threading.Lock())

    @property
    def cache_identity(self):
        return fingerprint(('llmlingua==0.2.2', self.model_name, self.revision,
                            self.device_map, self.dtype, self.max_batch_size))

    @cached_property
    def _compressor(self):
        require(version('llmlingua') == '0.2.2', 'Install memfolder[llmlingua2] (llmlingua==0.2.2)')
        import torch
        from llmlingua import PromptCompressor
        return PromptCompressor(model_name=self.model_name, device_map=self.device_map,
            use_llmlingua2=True,
            model_config={'revision': self.revision, 'torch_dtype': getattr(torch, self.dtype),
                          'trust_remote_code': False},
            llmlingua2_config={'max_batch_size': self.max_batch_size})

    def _compress(self, text, rate):
        # One model instance has mutable token-classifier state; serialize access.
        with self._lock:
            result = self._compressor.compress_prompt(text, rate=rate, use_context_level_filter=False)
        require(isinstance(result, dict) and type(result.get('compressed_prompt')) is str,
                'Invalid official LLMLingua-2 response')
        return {'text': result['compressed_prompt'], 'rate': rate,
            'input_view': 'current_record', 'input_text_sha256': sha256(text.encode('utf-8')).hexdigest(),
            'use_llmlingua2': True, 'use_context_level_filter': False,
            'implementation': 'llmlingua==0.2.2', 'model_name': self.model_name,
            'model_revision': self.revision, 'device_map': self.device_map, 'dtype': self.dtype,
            'original_tokens': result.get('origin_tokens'), 'compressed_tokens': result.get('compressed_tokens'),
            'request_fingerprint': fingerprint((self.cache_identity, text, rate, False, 'current_record'))}

    async def compress(self, text, *, rate):
        from .operators.llmlingua2 import validate_rate
        validate_rate(rate)
        require(type(text) is str and bool(text.strip()), 'LLMLingua-2 needs non-empty current text')
        return await asyncio.to_thread(self._compress, text, rate)

    async def close(self):
        def release():
            with self._lock:
                self.__dict__.pop('_compressor', None)
        await asyncio.to_thread(release)


PROFILE = 'llmlingua2.token_budget.normalized_fallback.v3'


class _Cl100kTokenCounter:
    def count(self, text):
        import tiktoken
        # Use cl100k_base token counting, including its
        # handling of special-token strings, rather than broadening that API.
        return len(tiktoken.get_encoding('cl100k_base').encode(text))


@dataclass(frozen=True)
class TokenBudgetLLMLingua2Service:
    model_name: str = 'microsoft/llmlingua-2-xlm-roberta-large-meetingbank'
    revision: str = 'ebaba9b0e874dadd3003ffcff828e4397e568089'
    device_map: str = 'cuda'
    spec = spec('service.llmlingua2_token_budget.v1', 'service')

    def __post_init__(self):
        require(all(type(value) is str and value for value in
                    (self.model_name, self.revision, self.device_map)),
                'Declare the token-budget LLMLingua model, revision and device')
        object.__setattr__(self, '_lock', threading.Lock())

    @property
    def cache_identity(self):
        return fingerprint((PROFILE, 'llmlingua==0.2.2', self.model_name,
                            self.revision, self.device_map, 'cl100k_base',
                            'python_round', 6, True, 'conditional_newline'))

    @cached_property
    def _counter(self):
        return _Cl100kTokenCounter()

    @cached_property
    def _compressor(self):
        require(version('llmlingua') == '0.2.2',
                'Install memfolder[llmlingua2] (llmlingua==0.2.2)')
        from huggingface_hub import snapshot_download
        from llmlingua import PromptCompressor
        checkpoint = snapshot_download(repo_id=self.model_name, revision=self.revision)
        # The token-budget service supplies only these three arguments. In
        # particular, it does not override dtype or the internal batch size.
        return PromptCompressor(model_name=str(checkpoint),
                                use_llmlingua2=True, device_map=self.device_map)

    def _compress(self, text, rate):
        source = text.strip()
        source_tokens = self._counter.count(source)
        kwargs = {'target_token': max(6, round(rate * source_tokens)),
                  'force_reserve_digit': True}
        if '\n' in source:
            kwargs['force_tokens'] = ['\n']
        with self._lock:
            result = self._compressor.compress_prompt(source, **kwargs)
        require(isinstance(result, dict) and
                isinstance(result.get('compressed_prompt'), (str, type(None))),
                'Invalid token-budget LLMLingua-2 response')
        output = (result.get('compressed_prompt') or '').strip()
        # The existing writer explicitly retains its source on empty output.
        # Other model failures propagate; no failed inference becomes a score.
        response = {'text': output, 'rate': rate, 'profile': PROFILE,
                'input_view': 'current_record',
                'input_text_sha256': sha256(text.encode('utf-8')).hexdigest(),
                'normalized_input_sha256': sha256(source.encode('utf-8')).hexdigest(),
                'output_text_sha256': sha256((output or source).encode('utf-8')).hexdigest(),
                'use_llmlingua2': True,
                # A single string has no context-level filtering in the
                # upstream algorithm; this flag describes effective behavior.
                'use_context_level_filter': False,
                'effective_kwargs': kwargs, 'budget_tokenizer': 'cl100k_base',
                'original_tokens': source_tokens,
                'compressed_tokens': self._counter.count(output or source),
                'implementation': 'llmlingua==0.2.2',
                'model_name': self.model_name, 'model_revision': self.revision,
                'device_map': self.device_map, 'constructor_policy': 'defaults',
                'fallback_reason': None if output else 'empty_classifier_output',
                'source_preserved': not bool(output),
                'request_fingerprint': fingerprint((self.cache_identity, text, rate, kwargs))}
        if not output:
            response['fallback_text'] = source
        return response

    async def compress(self, text, *, rate):
        from .operators.llmlingua2 import validate_rate
        validate_rate(rate)
        require(type(text) is str and bool(text.strip()),
                'Token-budget LLMLingua requires nonempty final Record text')
        return await asyncio.to_thread(self._compress, text, rate)

    async def close(self):
        def release():
            with self._lock:
                self.__dict__.pop('_compressor', None)
        await asyncio.to_thread(release)


class MeteredServices:
    def __init__(self,services,context,*,capture_prompts=False):
        self.services=services;self.context=context;self.capture_prompts=capture_prompts;self.calls=0;self._proxies={}
    def require(self,name):
        provider=self.services.require(name)
        if not callable(getattr(provider,'complete',None)):return provider
        if name not in self._proxies:self._proxies[name]=_ChatProxy(provider,self)
        return self._proxies[name]


class _ChatProxy:
    def __init__(self,provider,meter):self._provider=provider;self._meter=meter
    def __getattr__(self,name):return getattr(self._provider,name)
    def complete(self,request):
        m=self._meter;m.calls+=1
        data={'role':request.role,'call_index':m.calls,'prompt_hash':fingerprint(request.prompt),
              'max_tokens':request.max_tokens,'temperature':request.temperature}
        if m.capture_prompts:data['prompt']=request.prompt
        try:
            response=self._provider.complete(request)
        except Exception:
            emit(m.context,'memfolder.services.chat','memfolder.service.chat_call',**data,status='failed')
            raise
        def finished(value):
            data['response_hash']=fingerprint(value)
            if m.capture_prompts:data['response']=value
            emit(m.context,'memfolder.services.chat','memfolder.service.chat_call',**data,status='completed')
            return value
        if inspect.isawaitable(response):
            async def finish_async():
                try:return finished(await response)
                except Exception:
                    emit(m.context,'memfolder.services.chat','memfolder.service.chat_call',**data,status='failed')
                    raise
            return finish_async()
        return finished(response)
