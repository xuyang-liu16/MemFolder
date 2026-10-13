"""Safe file storage, verified assets and immutable run artifacts."""

from dataclasses import dataclass
from hashlib import sha256
import json
import shutil
from pathlib import Path, PurePosixPath
from .component_runtime import spec
from .core import ArtifactRef, Contract, FrozenMap, dumps, loads, to_data
from .core.values import require


def safe_path(root, name):
    p = PurePosixPath(name)
    require(type(name) is str and name == p.as_posix() and not p.is_absolute()
        and '..' not in p.parts and ':' not in name and '\\' not in name and name != '.', 'Invalid output path')
    base = Path(root).resolve(); target = (base / name).resolve()
    require(target.is_relative_to(base), 'Output path escaped its root')
    return target


def file_digest(path):
    h = sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def write_json(root, name, data):
    target = safe_path(root, name); target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(to_data(data), stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')
    return name


def asset_refs(snapshot):
    refs = list(snapshot.assets)
    for node in snapshot.records:
        refs.extend(p.artifact for p in node.parts if p.artifact)
        refs.extend(e.artifact for e in node.embeddings if e.artifact)
    unique = {}
    for ref in refs:
        require(ref.path not in unique or unique[ref.path] == ref, 'Conflicting artifact paths')
        unique[ref.path] = ref
    return tuple(unique.values())


@dataclass(frozen=True)
class VerifiedAssetCopier:
    root: Path
    spec = spec('wrapper.verified_assets', 'asset_copier')

    def copy(self, snapshot, directory, context):
        refs = asset_refs(snapshot)
        for ref in refs:
            source = ref.resolve(Path(self.root))
            require(source.is_file() and file_digest(source) == ref.sha256, 'Source artifact missing or changed')
        for ref in refs:
            target = safe_path(directory, ref.path); target.parent.mkdir(parents=True, exist_ok=True)
            with ref.resolve(Path(self.root)).open('rb') as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
            require(file_digest(target) == ref.sha256, 'Copied artifact checksum mismatch')
        return tuple(r.path for r in refs)


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
