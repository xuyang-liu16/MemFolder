"""Local JSON transports and exhaustive Qdrant scrolling without model imports."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import shutil
import tempfile

from memfolder.core import ContractError, FrozenMap
from memfolder.core.values import digest, fingerprint, identifier, require
from .common import strict_json
from .types import LoadOptions


@dataclass(frozen=True, kw_only=True)
class SourceDocument:
    source_id: str
    data: object
    sha256: str
    coverage: str | None = None
    consistency: str = 'file'

    def __post_init__(self):
        identifier(self.source_id)
        digest(self.sha256)
        require(self.coverage in (None, 'declared_complete', 'partial', 'unknown'), 'Invalid source coverage')
        require(self.consistency in ('file', 'best_effort', 'caller_snapshot'), 'Invalid source consistency')


def read_json(path: str | Path, *, options: LoadOptions, source_id: str | None = None,
              jsonl: bool | None = None) -> SourceDocument:
    path = Path(path)
    label = source_id or path.name
    require(path.is_file(), f'{label}: source file does not exist')
    require(path.stat().st_size <= options.max_file_bytes, f'{label}: file-size limit exceeded')
    is_lines = path.suffix.lower() in ('.jsonl', '.ndjson') if jsonl is None else jsonl
    if is_lines:
        rows, hasher, size = [], sha256(), 0
        with path.open('rb') as stream:
            for index, raw in enumerate(stream, 1):
                hasher.update(raw)
                size += len(raw)
                require(size <= options.max_file_bytes, f'{label}: file-size limit exceeded')
                try:
                    text = raw.decode('utf-8-sig' if index == 1 else 'utf-8')
                except UnicodeDecodeError:
                    raise ContractError(f'{label}: invalid UTF-8 at line {index}') from None
                if text.strip():
                    require(len(rows) < options.max_records, f'{label}: record limit exceeded')
                    rows.append(strict_json(text, f'{label}:line {index}'))
        return SourceDocument(source_id=label, data=rows, sha256=hasher.hexdigest())
    raw = path.read_bytes()
    require(len(raw) <= options.max_file_bytes, f'{label}: file-size limit exceeded')
    try:
        data = strict_json(raw.decode('utf-8-sig'), label)
    except UnicodeDecodeError:
        raise ContractError(f'{label}: invalid UTF-8') from None
    return SourceDocument(source_id=label, data=data, sha256=sha256(raw).hexdigest())


def child_path(root: Path, relative: str) -> Path:
    require(type(relative) is str and bool(relative) and not Path(relative).is_absolute(),
            'Cube memory filename must be relative')
    result = (root / relative).resolve()
    require(result.is_relative_to(root.resolve()), 'Cube memory filename escapes its root')
    return result


def read_qdrant(client, collection: str, *, options: LoadOptions,
                source_id: str | None = None, page_size: int = 256, scroll_filter=None) -> SourceDocument:
    """Caller-owned client. Exhaust every page; no Mem0 SDK/LLM initialization."""
    require(type(page_size) is int and page_size > 0, 'Invalid Qdrant page size')
    require(type(collection) is str and bool(collection), 'Missing Qdrant collection')
    label = source_id or 'qdrant:' + collection
    rows, offsets, point_ids = [], set(), set()
    offset = None
    pages = 0
    while True:
        points, next_offset = client.scroll(collection_name=collection, limit=page_size,
            offset=offset, with_payload=True, with_vectors=True, scroll_filter=scroll_filter)
        pages += 1
        require(pages <= options.max_records + 1, f'{label}: excessive pagination')
        for point in points:
            require(len(rows) < options.max_records, f'{label}: record limit exceeded')
            if type(point) is dict:
                row = {k: point.get(k) for k in ('id', 'payload', 'vector')}
            else:
                pid = point.id
                # UUID objects are value identifiers, not live resources.
                if type(pid) not in (str, int):
                    from uuid import UUID
                    require(isinstance(pid, UUID), f'{label}: unsupported Qdrant ID')
                    pid = str(pid)
                row = {'id': pid, 'payload': point.payload, 'vector': point.vector}
            require(type(row['id']) in (str, int), f'{label}: invalid Qdrant point ID')
            key = (type(row['id']).__name__, str(row['id']))
            require(key not in point_ids, f'{label}: repeated point across scroll pages')
            point_ids.add(key)
            # Pydantic SparseVector objects need explicit value conversion.
            vector = row['vector']
            if type(vector) is dict:
                row['vector'] = {k: v.model_dump(mode='json') if hasattr(v, 'model_dump') else v
                                 for k, v in vector.items()}
            FrozenMap(row)
            rows.append(row)
        if next_offset is None:
            break
        require(type(next_offset) in (str, int), f'{label}: invalid scroll offset')
        key = (type(next_offset).__name__, str(next_offset))
        require(key not in offsets, f'{label}: scroll offset repeated')
        offsets.add(key)
        offset = next_offset  # zero is a valid cursor
    data = {'points': rows, 'collection': collection, 'pages_read': pages}
    return SourceDocument(source_id=label, data=data, sha256=fingerprint({'collection': collection, 'points': rows}),
        coverage='declared_complete', consistency='best_effort')


def read_local_qdrant(path: str | Path, collection: str, *, options: LoadOptions,
                      source_id: str | None = None, page_size: int = 256, client_factory=None,
                      metadata_path: str | Path | None = None) -> SourceDocument:
    """Open a temporary copy only. The supplied original is never opened by the SDK."""
    root = Path(path).resolve()
    if (root / 'qdrant').is_dir():
        root = root / 'qdrant'
    require(root.is_dir(), 'Local Qdrant directory does not exist')
    meta = Path(metadata_path).resolve() if metadata_path is not None else root / 'meta.json'
    require(meta.is_file(), 'Qdrant meta.json is missing; supply metadata_path or use load_mem0_sqlite')
    meta_doc = read_json(meta, options=options)
    require(type(meta_doc.data) is dict and type(meta_doc.data.get('collections')) is dict
            and collection in meta_doc.data['collections'], 'Qdrant metadata does not declare this collection')
    if metadata_path is not None and (root / 'meta.json').exists():
        require((root / 'meta.json').read_bytes() == meta.read_bytes(), 'Conflicting Qdrant metadata sources')
    if client_factory is None:
        try:
            from qdrant_client import QdrantClient
        except ImportError:
            raise ContractError('Local Qdrant loading requires the optional qdrant-client package') from None
        client_factory = QdrantClient
    def inventory():
        result = {}
        for p in root.rglob('*'):
            require(not p.is_symlink(), 'Symlink in Qdrant source; provide a regular offline copy')
            if p.is_file() and not p.name.startswith('.lock'):
                stat = p.stat()
                result[p.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
        return result
    before = inventory()
    require(bool(before), 'Local Qdrant directory is empty')
    with tempfile.TemporaryDirectory(prefix='memfolder-read-') as folder:
        copied = Path(folder) / 'qdrant'
        shutil.copytree(root, copied, ignore=shutil.ignore_patterns('.lock*'))
        shutil.copyfile(meta, copied / 'meta.json')
        require(sha256((copied / 'meta.json').read_bytes()).hexdigest() == meta_doc.sha256
                and sha256(meta.read_bytes()).hexdigest() == meta_doc.sha256, 'Qdrant metadata changed while copying')
        require(before == inventory(), 'Qdrant source changed while copying; provide a stopped/offline snapshot')
        client = client_factory(path=str(copied))
        try:
            return read_qdrant(client, collection, options=options, source_id=source_id, page_size=page_size)
        finally:
            client.close()
