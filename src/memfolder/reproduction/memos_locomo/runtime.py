"""Operational paths and endpoints; scientific choices live in protocol.json."""
from pathlib import Path
import json
import os

ROOT=Path(os.environ.get('MEMFOLDER_MEMOS_RUN_DIR','build/memos_locomo')).expanduser().resolve()
PACKAGE=Path(__file__).resolve().parent
PROTOCOL=json.loads((PACKAGE/'protocol.json').read_text(encoding='utf-8'))
MODEL=PROTOCOL['evaluation']['model']
REVISION=PROTOCOL['framework']['upstream_revision']
UPSTREAM=Path(os.environ.get('MEMFOLDER_MEMOS_SOURCE',str(ROOT/'upstream'/('MemOS-'+REVISION)))).resolve()
CHAT_URL=os.environ.get('MEMFOLDER_CHAT_BASE_URL','https://api15.xhub.chat/v1').rstrip('/')
EMBED_URL=os.environ.get('MEMFOLDER_EMBEDDING_BASE_URL','https://dapi.aivue.cn/v1').rstrip('/')
PORT=int(os.environ.get('MEMFOLDER_MEMOS_POSTGRES_PORT','28142'))
RERANKER_PORT=int(os.environ.get('MEMFOLDER_MEMOS_RERANKER_PORT','28112'))
USER='memfolder_owner'
DATABASE='memfolder_locomo'
BIN=Path(os.environ.get('MEMFOLDER_POSTGRES_BIN',str(ROOT/'environment/postgres/pgsql/bin'))).resolve()
DATA=ROOT/'runs/memos_locomo/postgres_data'
MODEL_DIR=Path(os.environ.get('MEMFOLDER_MEMOS_MODEL_DIR',str(ROOT/'cache/models/bge-reranker-v2-m3'))).resolve()
EMBEDDING_MODEL_DIR=Path(os.environ.get('MEMFOLDER_MEMOS_EMBEDDING_MODEL_DIR',str(ROOT/'cache/models/bge-m3'))).resolve()
OWNER=os.environ.get('MEMFOLDER_MEMOS_OWNER','')

def initialize():
    for folder in ['cache','tmp','logs','reports/memos_locomo','runs/memos_locomo']:(ROOT/folder).mkdir(parents=True,exist_ok=True)
    for name in ['TEMP','TMP','TMPDIR']:os.environ[name]=str(ROOT/'tmp')
    os.environ['HF_HOME']=str(ROOT/'cache/huggingface')
    os.environ['TIKTOKEN_CACHE_DIR']=str(ROOT/'cache/tiktoken')
    os.environ['MEMOS_BASE_PATH']=str(ROOT/'runs/memos_locomo')
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['TOKENIZERS_PARALLELISM']='false'
    for name in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS']:os.environ.setdefault(name,'1')
