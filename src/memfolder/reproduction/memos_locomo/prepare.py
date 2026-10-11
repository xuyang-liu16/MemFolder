"""Checksum-verified upstream assets and self-contained recorded-run evidence."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile
from .runtime import ROOT,PACKAGE,UPSTREAM,REVISION,MODEL_DIR
from .io import save


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(4*1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def download(url,path,expected):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and sha(path)==expected:return
    part=path.with_suffix(path.suffix+'.partial')
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'MemFolder-reproduction'}),timeout=120) as response,part.open('wb') as handle:
        shutil.copyfileobj(response,handle,1024*1024)
    if sha(part)!=expected:raise RuntimeError('Downloaded asset checksum mismatch: '+path.name)
    part.replace(path)


def verify_source():
    marker=UPSTREAM/'.memfolder-source.json'
    if marker.is_file():
        value=json.loads(marker.read_text(encoding='utf-8'))
        expected=json.loads((PACKAGE/'upstream.json').read_text(encoding='utf-8'))
        if value!=expected:raise RuntimeError('MemOS source revision marker differs from the pinned configuration')
    else:
        import subprocess
        result=subprocess.run(['git','-C',str(UPSTREAM),'rev-parse','HEAD'],capture_output=True,text=True)
        clean=subprocess.run(['git','-C',str(UPSTREAM),'diff','--quiet','HEAD'],capture_output=True)
        if result.returncode or result.stdout.strip()!=REVISION or clean.returncode:raise RuntimeError('Run prepare, or supply a clean checkout of the pinned MemOS revision')
    if not (UPSTREAM/'src/memos').is_dir():raise RuntimeError('Pinned MemOS source is missing')
    return REVISION


def prepare(weights=False):
    manifest=json.loads((PACKAGE/'upstream.json').read_text(encoding='utf-8'))
    if not (UPSTREAM/'src/memos').is_dir():
        path=ROOT/'cache/downloads'/('MemOS-'+REVISION+'.zip')
        download('https://codeload.github.com/MemTensor/MemOS/zip/'+REVISION,path,manifest['archive_sha256'])
        target=UPSTREAM.parent;target.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if not (target/member.filename).resolve().is_relative_to(target.resolve()):raise RuntimeError('Unsafe upstream archive path')
            archive.extractall(target)
        (UPSTREAM/'.memfolder-source.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    verified=verify_source()
    data=ROOT/'inputs/locomo10.json'
    if not data.exists():
        data.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(UPSTREAM/'evaluation/data/locomo/locomo10.json',data)
    if weights:
        model=json.loads((PACKAGE/'model.json').read_text(encoding='utf-8'))
        for name,meta in model['files'].items():download(f"https://huggingface.co/BAAI/bge-reranker-v2-m3/resolve/{model['revision']}/{name}?download=true",MODEL_DIR/name,meta['sha256'])
    report={'status':'prepared','memos_revision':REVISION,'verified_revision':verified,'dataset':str(data),'weights_prepared':weights}
    save(ROOT/'reports/memos_locomo/preparation.json',report)
    return report
