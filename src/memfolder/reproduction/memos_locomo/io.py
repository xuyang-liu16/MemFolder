"""Windows atomic JSON writes for this private experiment only."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from .runtime import ROOT
_LOCK=threading.Lock()
_PATH_LOCKS={}
_LAST={}
_STATS={'saved':0,'replacement_retries':0,'telemetry_deferred':0,'telemetry_throttled':0}
EVENTS=ROOT/'logs/io_recovery_events.jsonl'

def stats():
    with _LOCK:return dict(_STATS)

def _event(path,exc,attempts):
    event={'time':time.strftime('%Y-%m-%d %H:%M:%S'),'path':str(path),'error_type':type(exc).__name__,'winerror':getattr(exc,'winerror',None),'attempts':attempts,'action':'telemetry_deferred'}
    try:
        with _LOCK:
            with EVENTS.open('a',encoding='utf-8') as handle:handle.write(json.dumps(event)+'\n')
    except OSError:
        print('Private experiment progress file temporarily unavailable; computation continues.',flush=True)

def save(path,value,*,telemetry=False,timeout=None):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('Recovery writer is confined to the private experiment directory')
    encoded=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')
    key=str(path)
    signature=(value.get('status'),value.get('phase')) if isinstance(value,dict) else None
    with _LOCK:lock=_PATH_LOCKS.setdefault(key,threading.Lock())
    with lock:
        now=time.monotonic()
        previous=_LAST.get(key)
        if telemetry and previous and previous[1]==signature and now-previous[0]<0.5:
            with _LOCK:_STATS['telemetry_throttled']+=1
            return True
        path.parent.mkdir(parents=True,exist_ok=True)
        deadline=now+(timeout if timeout is not None else (1.0 if telemetry else 10.0))
        temporary=None
        attempts=0
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as handle:
                temporary=Path(handle.name)
                handle.write(encoded)
                handle.flush()
                if not telemetry:os.fsync(handle.fileno())
            while True:
                attempts+=1
                try:
                    os.replace(temporary,path)
                    _LAST[key]=(time.monotonic(),signature)
                    with _LOCK:_STATS['saved']+=1
                    return True
                except OSError as exc:
                    if not isinstance(exc,PermissionError) and getattr(exc,'winerror',None) not in (5,32,33):raise
                    with _LOCK:_STATS['replacement_retries']+=1
                    if time.monotonic()>=deadline:
                        if telemetry:
                            _LAST[key]=(time.monotonic(),signature)
                            with _LOCK:_STATS['telemetry_deferred']+=1
                            _event(path,exc,attempts)
                            return False
                        raise
                    time.sleep(min(0.02*attempts,0.1))
        finally:
            if temporary is not None:
                try:temporary.unlink(missing_ok=True)
                except OSError:pass
