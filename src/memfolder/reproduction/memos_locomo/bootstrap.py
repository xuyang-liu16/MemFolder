"""Prepare a private Windows PostgreSQL distribution and build pinned pgvector.

Requires the x64 MSVC build tools. Linux users may supply a matching installation
through --postgres-bin; no system service or administrator access is required.
"""
import json
import os
from pathlib import Path
import subprocess
import zipfile

from .runtime import ROOT
from .prepare import download
from .io import save

PG_URL='https://get.enterprisedb.com/postgresql/postgresql-16.10-1-windows-x64-binaries.zip'
PG_SHA='ebb3b6af4fa69dea9951b66855bc4d42dc04e56ccb9aa7024ce3c58bd89d6b0c'
VECTOR_REV='778dacf20c07caf904557a88705142631818d8cb'
VECTOR_SHA='5badef2cdfed828d93b7f70ae6ad38236e36954420bb24001aa5508e61bf2d7c'


def extract(archive,target):
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            if not (target/item.filename).resolve().is_relative_to(target.resolve()):
                raise RuntimeError('Unsafe PostgreSQL archive path')
        package.extractall(target)


def windows_postgres(vcvars):
    if os.name!='nt':raise RuntimeError('Use --postgres-bin with PostgreSQL 16.10 + pgvector 0.8.1 on Linux')
    if not vcvars or not Path(vcvars).is_file():raise RuntimeError('Supply --vcvars with the x64 Visual Studio vcvars64.bat path')
    vcvars=Path(vcvars).resolve()
    # cmd quoting is deliberately limited to verified paths, with no user code.
    if any(c in str(vcvars)+str(ROOT) for c in '\r\n"%&|<>^!'):raise RuntimeError('Build paths contain unsupported cmd metacharacters')
    home=ROOT/'environment/postgres';home.mkdir(parents=True,exist_ok=True)
    cache=ROOT/'cache/downloads';cache.mkdir(parents=True,exist_ok=True)
    pg=cache/'postgresql-16.10-1-windows-x64-binaries.zip'
    vector=cache/('pgvector-'+VECTOR_REV+'.zip')
    download(PG_URL,pg,PG_SHA)
    download('https://codeload.github.com/pgvector/pgvector/zip/'+VECTOR_REV,vector,VECTOR_SHA)
    if not (home/'pgsql/bin/postgres.exe').exists():extract(pg,home)
    source=home/('pgvector-'+VECTOR_REV)
    if not source.exists():extract(vector,home)
    env=dict(os.environ);env['PGROOT']=str(home/'pgsql')
    script=ROOT/'tmp/build-pgvector.cmd'
    script.write_text('@echo off\ncall "'+str(vcvars)+'"\nif errorlevel 1 exit /b 1\nnmake /F Makefile.win\nif errorlevel 1 exit /b 1\nnmake /F Makefile.win install\nexit /b %errorlevel%\n',encoding='utf-8')
    log=ROOT/'logs/build-pgvector.log'
    with log.open('w',encoding='utf-8') as handle:
        result=subprocess.run(['cmd.exe','/d','/c',str(script)],cwd=source,env=env,stdout=handle,stderr=handle,timeout=600,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or not (home/'pgsql/lib/vector.dll').is_file():raise RuntimeError('pgvector build failed; inspect logs/build-pgvector.log')
    report={'postgres_bin':str(home/'pgsql/bin'),'postgres_version':'16.10','postgres_archive_sha256':PG_SHA,'pgvector_version':'0.8.1','pgvector_revision':VECTOR_REV,'pgvector_archive_sha256':VECTOR_SHA}
    save(ROOT/'reports/memos_locomo/postgres_preparation.json',report)
    return report
