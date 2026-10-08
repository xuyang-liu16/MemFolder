"""Immutable, checksum-addressed run artifacts and confined observer reports."""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from .core import ArtifactRef, FrozenMap, Contract, dumps, loads, to_data
from .core.values import require
from .wrappers.io import safe_path, file_digest


def parse_json(text):
    def pairs(items):
        values={}
        for key,value in items:
            require(key not in values,'Duplicate JSON key');values[key]=value
        return values
    value=json.loads(text,object_pairs_hook=pairs,parse_constant=lambda _:require(False,'Nonfinite JSON value'))
    FrozenMap({'value':value});return value


@dataclass(frozen=True)
class ArtifactStore:
    root: Path
    max_bytes: int = 512*1024*1024

    def put(self,name,value,*,schema_id='memfolder.artifact.json',record_count=None):
        text=dumps(value) if isinstance(value,Contract) else json.dumps(to_data(value),ensure_ascii=False,allow_nan=False,sort_keys=True)
        raw=(text+'\n').encode('utf-8');require(len(raw)<=self.max_bytes,'Artifact exceeds size limit')
        path=safe_path(self.root,name);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)
        digest=sha256(raw).hexdigest()
        return ArtifactRef(artifact_id='sha256:'+digest,path=name,sha256=digest,media_type='application/json',schema_id=getattr(value,'schema_id',schema_id),record_count=record_count)

    def verify(self,ref):
        path=ref.resolve(Path(self.root))
        return path.is_file() and path.stat().st_size<=self.max_bytes and file_digest(path)==ref.sha256

    def read(self,ref):
        require(self.verify(ref),'Artifact missing, changed or oversized')
        text=ref.resolve(Path(self.root)).read_text(encoding='utf-8');value=parse_json(text)
        return loads(text) if isinstance(value,dict) and set(value)=={'schema_id','schema_version','data'} else value


@dataclass(frozen=True)
class PublicArtifacts:
    store: ArtifactStore
    allowed: object  # recorder-owned set of immutable ArtifactRefs
    def verify(self,ref):return ref in self.allowed and self.store.verify(ref)
    def read_json(self,ref):
        require(ref in self.allowed,'Artifact is not published to observers')
        value=self.store.read(ref)
        require(isinstance(value,(dict,FrozenMap,Contract)),'Expected JSON object')
        return FrozenMap(to_data(value))
    def iter_rows(self,ref):
        require(ref in self.allowed,'Artifact is not published to observers')
        value=to_data(self.store.read(ref));rows=value.get('rows') if isinstance(value,dict) else value
        require(isinstance(rows,list),'Artifact has no row table')
        for row in rows:yield FrozenMap(row)


@dataclass(frozen=True)
class FileReportWriter:
    root: Path
    def write_json(self,name,value):
        require(isinstance(value,FrozenMap),'Observer reports must be detached FrozenMap values')
        ArtifactStore(self.root).put(name,value)
        return safe_path(self.root,name)
