"""Experiment-local, durable API transport. Secrets only enter through environment."""
from __future__ import annotations
import asyncio
import hashlib
import json
import math
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace


from .runtime import ROOT, MODEL, CHAT_URL, EMBED_URL

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()

class Transport:
    def __init__(self, concurrency=32):
        self.path = ROOT / 'cache/api.sqlite'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(concurrency)
        from openai import OpenAI
        self.chat_client=OpenAI(api_key=os.environ['MEMFOLDER_CHAT_KEY'],base_url=CHAT_URL,timeout=120,max_retries=0)
        self.embedding_client=OpenAI(api_key=os.environ['MEMFOLDER_EMBEDDING_KEY'],base_url=EMBED_URL,timeout=120,max_retries=0)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, kind TEXT, body TEXT, sha TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS audit (time REAL, kind TEXT, key TEXT, elapsed REAL, status TEXT, model TEXT, usage TEXT)')
            db.commit()

    def get(self, key):
        with closing(sqlite3.connect(self.path, timeout=60)) as db:
            row = db.execute('SELECT body, sha FROM responses WHERE key=?', (key,)).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        if digest(value) != row[1]:
            raise RuntimeError('API cache checksum mismatch')
        return value

    def put(self, key, kind, value):
        with self.lock, closing(sqlite3.connect(self.path, timeout=60)) as db:
            db.execute('INSERT OR IGNORE INTO responses VALUES (?,?,?,?)', (key, kind, json.dumps(value, ensure_ascii=False, allow_nan=False), digest(value)))
            db.commit()

    def audit(self, kind, key, start, status, model='', usage=None):
        with self.lock, closing(sqlite3.connect(self.path, timeout=60)) as db:
            db.execute('INSERT INTO audit VALUES (?,?,?,?,?,?,?)', (time.time(), kind, key, time.perf_counter()-start, status, model, json.dumps(usage or {})))
            db.commit()

    def retry(self, operation, kind, key):
        for attempt in range(5):
            start = time.perf_counter()
            try:
                with self.slots:
                    result = operation()
                self.audit(kind, key, start, 'ok', result.model, result.usage.model_dump() if result.usage else None)
                return result
            except Exception as exc:
                status = getattr(exc, 'status_code', None)
                code = getattr(exc, 'code', None)
                self.audit(kind, key, start, f'{type(exc).__name__}:{status}:{code}')
                if status in (400, 401, 403, 404) or code in ('insufficient_quota', 'quota_exceeded') or attempt == 4:
                    raise
                time.sleep(min(2 ** attempt, 16))

    def chat(self, *, kind, messages, nonce='', validate=None, **params):
        params['model'] = MODEL
        key = digest(('chat', CHAT_URL, kind, nonce, messages, params))
        cached = self.get(key)
        if cached is not None:
            response = response_view(cached)
            if validate:
                validate(response.choices[0].message.content)
            return response
        response = self.retry(lambda: self.chat_client.chat.completions.create(messages=messages, **params), kind, key)
        if response.model != MODEL:
            raise RuntimeError(f'Unexpected returned model: {response.model}')
        if not response.choices or response.choices[0].finish_reason != 'stop':
            raise RuntimeError('Incomplete or filtered response; no result was cached')
        if not response.choices[0].message.content:
            raise RuntimeError('Empty LLM response')
        if validate:
            try:
                validate(response.choices[0].message.content)
            except Exception as exc:
                folder = ROOT / 'cache/invalid_responses'
                folder.mkdir(exist_ok=True)
                path = folder / (key+f'.{time.time_ns()}.json')
                detail = exc.errors(include_input=False, include_url=False) if hasattr(exc, 'errors') else {'type':type(exc).__name__}
                path.write_text(json.dumps({'kind':kind, 'model':response.model, 'content':response.choices[0].message.content, 'errors':detail}, ensure_ascii=False, default=str), encoding='utf-8')
                exc.invalid_response = response
                raise
        self.put(key, kind, response.model_dump(mode='json'))
        return response

class SyncCompletions:
    def __init__(self, transport, kind='extract', nonce='', validate=None):
        self.transport, self.kind, self.nonce, self.validate = transport, kind, nonce, validate
    def create(self, messages, **params):
        return self.transport.chat(kind=self.kind,messages=messages,nonce=self.nonce,validate=self.validate,**params)

class AsyncCompletions(SyncCompletions):
    async def create(self, messages, **params):
        return await asyncio.to_thread(super().create, messages=messages, **params)

def client_proxy(transport, *, kind, nonce='', validate=None, asynchronous=False):
    cls = AsyncCompletions if asynchronous else SyncCompletions
    return SimpleNamespace(chat=SimpleNamespace(completions=cls(transport, kind, nonce, validate)))

def response_view(value):
    # Validate locally cached API responses before reuse.
    choices=[SimpleNamespace(finish_reason=c['finish_reason'],message=SimpleNamespace(content=c['message']['content'])) for c in value['choices']]
    if value['model']!=MODEL or not choices or choices[0].finish_reason!='stop' or not choices[0].message.content:
        raise RuntimeError('Invalid cached chat response')
    return SimpleNamespace(model=value['model'],choices=choices)
