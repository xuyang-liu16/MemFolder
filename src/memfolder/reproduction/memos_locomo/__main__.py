"""Prepare and run the native MemOS LoCoMo protocol."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request


def main(argv=None):
    parser=argparse.ArgumentParser(prog='memfolder-memos-locomo')
    parser.add_argument('command',choices=['prepare','run','reranker'])
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--source-dir',type=Path)
    parser.add_argument('--postgres-bin',type=Path)
    parser.add_argument('--model-dir',type=Path)
    parser.add_argument('--reranker-python',type=Path)
    parser.add_argument('--postgres-port',type=int,default=28142)
    parser.add_argument('--reranker-port',type=int,default=28112)
    parser.add_argument('--build-workers',type=int,default=12)
    parser.add_argument('--qa-workers',type=int,default=4)
    parser.add_argument('--weights',action='store_true')
    parser.add_argument('--postgres',action='store_true',help='Build private PostgreSQL + pgvector on Windows')
    parser.add_argument('--vcvars',type=Path)
    args=parser.parse_args(argv)
    if not 1<=args.build_workers<=64 or not 1<=args.qa_workers<=64:parser.error('workers must be in [1,64]')
    if any(port<1024 or port>65535 for port in (args.postgres_port,args.reranker_port)):parser.error('ports must be in [1024,65535]')
    for name,value in [('MEMFOLDER_MEMOS_RUN_DIR',args.run_dir.resolve()),('MEMFOLDER_MEMOS_POSTGRES_PORT',args.postgres_port),('MEMFOLDER_MEMOS_RERANKER_PORT',args.reranker_port)]:os.environ[name]=str(value)
    for name,value in [('MEMFOLDER_MEMOS_SOURCE',args.source_dir),('MEMFOLDER_POSTGRES_BIN',args.postgres_bin),('MEMFOLDER_MEMOS_MODEL_DIR',args.model_dir)]:
        if value:os.environ[name]=str(value.resolve())
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr,'reconfigure'):sys.stderr.reconfigure(encoding='utf-8')
    from .runtime import initialize,ROOT,UPSTREAM,PACKAGE,RERANKER_PORT
    initialize()
    from .prepare import prepare,verify_source
    if args.command=='prepare':
        result=prepare(weights=args.weights)
        if args.postgres:
            from .bootstrap import windows_postgres
            result['postgres']=windows_postgres(args.vcvars)
        print(json.dumps(result,ensure_ascii=False));return 0
    if args.command=='reranker':
        from .reranker import main as serve
        serve();return 0
    if not os.environ.get('MEMFOLDER_CHAT_KEY') or not os.environ.get('MEMFOLDER_EMBEDDING_KEY'):raise RuntimeError('Set MEMFOLDER_CHAT_KEY and MEMFOLDER_EMBEDDING_KEY')
    verify_source()
    sys.path.insert(0,str(UPSTREAM/'src'))
    os.environ['MEMFOLDER_MEMOS_OWNER']=secrets.token_hex(16)
    child_env=dict(os.environ)
    child_env['PYTHONPATH']=str(PACKAGE.parents[2])+os.pathsep+child_env.get('PYTHONPATH','')
    child_env['PYTHONUTF8']='1'
    logs=[];child=None
    try:
        for name in ['reranker.stdout.log','reranker.stderr.log']:logs.append((ROOT/'logs'/name).open('w',encoding='utf-8'))
        command=[str(args.reranker_python or sys.executable),'-B','-m','memfolder.reproduction.memos_locomo','reranker','--run-dir',str(ROOT),'--reranker-port',str(RERANKER_PORT)]
        child=subprocess.Popen(command,env=child_env,stdout=logs[0],stderr=logs[1],creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        deadline=time.monotonic()+120
        ready=False
        while time.monotonic()<deadline:
            if child.poll() is not None:raise RuntimeError('Reranker exited; inspect logs/reranker.stderr.log')
            try:
                health=json.load(urllib.request.urlopen(f'http://127.0.0.1:{RERANKER_PORT}/health',timeout=2))
                if health.get('owner')!=child_env['MEMFOLDER_MEMOS_OWNER']:raise RuntimeError('Reranker port belongs to another process')
                if health['status']=='ready':ready=True;break
            except urllib.error.URLError:pass
            time.sleep(.5)
        if not ready:raise RuntimeError('Reranker startup timed out')
        from . import runner
        sys.argv=['memfolder-memos-locomo','--build-workers',str(args.build_workers),'--qa-workers',str(args.qa_workers)]
        try:runner.main()
        except Exception as exc:
            runner.status(status='failed',error_type=type(exc).__name__,error=str(exc));raise
    finally:
        if child is not None:
            try:
                request=urllib.request.Request(f'http://127.0.0.1:{RERANKER_PORT}/shutdown',data=b'',headers={'X-MemFolder-Owner':child_env['MEMFOLDER_MEMOS_OWNER']},method='POST')
                urllib.request.urlopen(request,timeout=3).close();child.wait(timeout=10)
            except (OSError,subprocess.TimeoutExpired):
                if child.poll() is None:
                    import psutil
                    try:
                        process=psutil.Process(child.pid)
                        for owned in reversed(process.children(recursive=True)):
                            try:owned.terminate()
                            except psutil.NoSuchProcess:pass
                        process.terminate()
                    except psutil.NoSuchProcess:pass
        for handle in logs:handle.close()
    return 0


if __name__=='__main__':raise SystemExit(main())
