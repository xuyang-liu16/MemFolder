"""Exclusive output files and verified copies. Never opens an input for writing."""
from hashlib import sha256
from pathlib import Path, PurePosixPath
from dataclasses import dataclass
import json
import shutil
from ..core import to_data
from ..core.values import require
from ..planning.common import spec


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
