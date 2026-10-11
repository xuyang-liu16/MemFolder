"""Own a private PostgreSQL cluster, never an OS service or another run's cluster."""
from contextlib import contextmanager
import os
import socket
import subprocess
import time
from .runtime import ROOT,BIN,DATA,PORT,USER,DATABASE
from .io import save


def command(name,args):
    executable=BIN/(name+('.exe' if os.name=='nt' else ''))
    if not executable.is_file():raise RuntimeError('Missing PostgreSQL executable: '+str(executable))
    log=ROOT/'logs'/f'{name}_{time.time_ns()}.log'
    with log.open('w',encoding='utf-8') as handle:
        result=subprocess.run([str(executable),*args],stdin=subprocess.DEVNULL,stdout=handle,stderr=handle,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode:raise RuntimeError('PostgreSQL command failed; inspect '+str(log))

@contextmanager
def postgres_service():
    import psycopg2
    with socket.socket() as probe:
        probe.settimeout(.2)
        if probe.connect_ex(('127.0.0.1',PORT))==0:raise RuntimeError('PostgreSQL port occupied; use another port or stop the previously owned cluster')
    DATA.parent.mkdir(parents=True,exist_ok=True)
    if not (DATA/'PG_VERSION').exists():
        command('initdb',['-D',str(DATA),'-U',USER,'-A','trust','-E','UTF8','--locale=C'])
    (DATA/'postgresql.conf').write_text(f"listen_addresses='127.0.0.1'\nport={PORT}\nshared_buffers='64MB'\nwork_mem='4MB'\nmaintenance_work_mem='32MB'\nmax_connections=60\nmax_parallel_workers=2\n",encoding='utf-8')
    command('pg_ctl',['-D',str(DATA),'-l',str(ROOT/'logs/postgres.log'),'-w','start'])
    receipt={'status':'running','port':PORT,'data':str(DATA),'database':DATABASE,'pid':int((DATA/'postmaster.pid').read_text().splitlines()[0])}
    path=ROOT/'reports/memos_locomo/postgres_service.json'
    try:
        db=psycopg2.connect(host='127.0.0.1',port=PORT,user=USER,dbname='postgres')
        try:
            db.autocommit=True
            with db.cursor() as c:
                c.execute('SELECT 1 FROM pg_database WHERE datname=%s',(DATABASE,))
                if c.fetchone() is None:c.execute('CREATE DATABASE memfolder_locomo')
        finally:db.close()
        with psycopg2.connect(host='127.0.0.1',port=PORT,user=USER,dbname=DATABASE) as db:
            with db.cursor() as c:
                c.execute('CREATE EXTENSION IF NOT EXISTS vector')
                c.execute("SELECT version(),extversion FROM pg_extension WHERE extname='vector'")
                version,vector_version=c.fetchone()
                if 'PostgreSQL 16.10' not in version or vector_version!='0.8.1':raise RuntimeError('This reproduction requires PostgreSQL 16.10 and pgvector 0.8.1')
                c.execute("SELECT 1-('[1,0]'::vector <=> '[1,0]'::vector),1-('[1,0]'::vector <=> '[0,1]'::vector)")
                if c.fetchone()!=(1.0,0.0):raise RuntimeError('pgvector cosine witness failed')
                receipt.update(postgres_version=version,pgvector_version=vector_version,cosine_witness=[1,0])
        save(path,receipt,telemetry=True)
        yield receipt
    finally:
        command('pg_ctl',['-D',str(DATA),'-w','-m','fast','stop'])
        receipt.update(status='stopped',stopped_at=time.strftime('%Y-%m-%d %H:%M:%S'))
        save(path,receipt,telemetry=True)
