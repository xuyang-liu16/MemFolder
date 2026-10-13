"""JSON, Qdrant SQLite and restricted M3 pickle source readers."""

from __future__ import annotations
import base64
import pickle
import shutil
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID
from .contracts import LoadOptions
from ..core import ContractError, FrozenMap
from ..core.values import digest, fingerprint, identifier, require
from .validation import strict_json


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


class _Point:
    pass


class _Sparse:
    pass


class _ValueUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module in ('qdrant_client.http.models.models', 'qdrant_client.http.models'):
            if name == 'PointStruct':
                return _Point
            if name == 'SparseVector':
                return _Sparse
        if (module, name) == ('uuid', 'UUID'):
            return UUID
        if module == 'builtins' and name in ('set', 'frozenset'):
            return {'set': set, 'frozenset': frozenset}[name]
        raise ContractError('Qdrant SQLite contains an unsupported pickle global; use a value-only export')

    def persistent_load(self, pid):
        raise ContractError('External pickle references are not supported in Qdrant SQLite')


def _unpickle(raw: bytes):
    try:
        stream = BytesIO(raw)
        result = _ValueUnpickler(stream).load()
        require(stream.read(1) == b'', 'Trailing data after Qdrant point pickle')
        return result
    except ContractError:
        raise
    except (pickle.UnpicklingError, EOFError, ValueError, TypeError, AttributeError):
        raise ContractError('Invalid Qdrant persisted point representation') from None


def _fields(model):
    state = vars(model)
    if '__dict__' not in state:
        return state  # plain values / older serialization
    require(type(state['__dict__']) is dict, 'Invalid Qdrant model state')
    fields = dict(state['__dict__'])
    extras = state.get('__pydantic_extra__')
    require(extras is None or type(extras) is dict, 'Invalid Qdrant model extras')
    if extras:
        require(not set(fields).intersection(extras), 'Conflicting Qdrant model extras')
        fields.update(extras)
    require(not state.get('__pydantic_private__'), 'Unsupported private Qdrant model state')
    return fields


def _value(value):
    if value is None or type(value) in (str, int, float, bool):
        return value
    if type(value) is UUID:
        return str(value)
    if type(value) in (tuple, list):
        return [_value(v) for v in value]
    if type(value) is dict:
        require(all(type(k) is str for k in value), 'Invalid Qdrant value map key')
        return {k: _value(v) for k, v in value.items()}
    if type(value) is _Sparse:
        return _value(_fields(value))
    raise ContractError('Unsupported Qdrant persisted value; no opaque objects imported')


def _hash(path: Path, limit: int):
    require(path.is_file() and not path.is_symlink(), 'Missing/linked Qdrant SQLite source')
    require(path.stat().st_size <= limit, 'Qdrant SQLite file-size limit exceeded')
    result, size = sha256(), 0
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            require(size <= limit, 'Qdrant SQLite file-size limit exceeded')
            result.update(chunk)
    return result.hexdigest()


def read_qdrant_sqlite(path: str | Path, *, options: LoadOptions,
                       source_id: str | None = None) -> SourceDocument:
    """Read every persisted point from a checkpointed offline SQLite file.

    Missing meta.json is allowed: distance metric and model identity stay unknown.
    A temporary copy avoids creating journal/SHM/lock files in the original bank.
    """
    path = Path(path).resolve()
    label = source_id or 'sqlite:' + path.name
    wal = path.with_name(path.name + '-wal')
    journal = path.with_name(path.name + '-journal')

    def stopped():
        require(all(not p.exists() or p.stat().st_size == 0 for p in (wal, journal)),
                'Qdrant SQLite has an active journal/WAL; provide a checkpointed offline snapshot')

    stopped()
    before = _hash(path, options.max_file_bytes)
    rows = []
    with tempfile.TemporaryDirectory(prefix='memfolder-sqlite-') as folder:
        copied = Path(folder) / 'storage.sqlite'
        shutil.copyfile(path, copied)
        require(_hash(copied, options.max_file_bytes) == before
                and _hash(path, options.max_file_bytes) == before, 'Qdrant SQLite changed while copying')
        stopped()
        try:
            with closing(sqlite3.connect(copied.as_uri() + '?mode=ro&immutable=1', uri=True)) as connection:
                connection.execute('PRAGMA query_only=ON')
                columns = [r[1] for r in connection.execute('PRAGMA table_info(points)')]
                require(columns == ['id', 'point'], 'Not a supported Qdrant points SQLite database')
                count = connection.execute('SELECT count(*) FROM points').fetchone()[0]
                require(count <= options.max_records, 'Qdrant SQLite record limit exceeded')
                for key, raw in connection.execute('SELECT id, point FROM points ORDER BY id'):
                    require(type(key) is str and type(raw) is bytes, 'Invalid Qdrant persisted row')
                    point = _unpickle(raw)
                    require(type(point) is _Point, 'Qdrant SQLite row is not a PointStruct')
                    row = _value(_fields(point))
                    require(type(row.get('id')) in (str, int) and 'vector' in row and 'payload' in row,
                            'Qdrant SQLite row is missing point fields')
                    try:
                        decoded = _unpickle(base64.b64decode(key, validate=True))
                    except (ValueError, TypeError):
                        raise ContractError('Invalid Qdrant persisted point key') from None
                    require(type(decoded) in (str, int, UUID), 'Invalid Qdrant point key type')
                    decoded = str(decoded) if type(decoded) is UUID else decoded
                    require(type(decoded) is type(row['id']) and decoded == row['id'],
                            'Qdrant persisted key does not match point ID')
                    FrozenMap(row)  # rejects nonfinite numbers and unsupported nested values
                    rows.append(row)
                require(len(rows) == count, 'Qdrant SQLite row count changed')
        except sqlite3.Error:
            raise ContractError('Unreadable Qdrant points SQLite database') from None
    return SourceDocument(source_id=label, sha256=before, consistency='file', coverage='unknown',
        data={'points': rows, 'transport': 'qdrant.local.sqlite.v1', 'persisted_rows_complete': True,
              'collection_configuration': 'not_loaded', 'vector_values': 'stored_unmodified'})


class _Graph:
    pass


class _Node:
    pass


class _M3Unpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module in ('mmagent.videograph', 'videograph'):
            if name == 'VideoGraph':
                return _Graph
            if name in ('VideoGraph.Node', 'Node'):
                return _Node
        allowed = {
            ('numpy', 'ndarray'), ('numpy', 'dtype'),
            ('numpy.core.multiarray', '_reconstruct'), ('numpy._core.multiarray', '_reconstruct'),
            ('numpy.core.multiarray', 'scalar'), ('numpy._core.multiarray', 'scalar'),
            ('numpy.core.numeric', '_frombuffer'), ('numpy._core.numeric', '_frombuffer'),
        }
        if (module, name) not in allowed:
            raise ContractError('M3 pickle contains an unsupported global; use a JSON export for this variant')
        try:
            import numpy as np
        except ImportError:
            raise ContractError('This M3 pickle requires the optional numpy package') from None
        require(hasattr(np, 'ndarray') and hasattr(np, 'dtype'), 'M3 pickle needs a functional numpy installation')
        if name == 'ndarray':
            return np.ndarray
        if name == 'dtype':
            return np.dtype
        # Both numpy 1.x and 2.x serialization module names are recognized.
        core = getattr(np, '_core', None)
        if core is None:
            core = np.core
        if name == '_reconstruct':
            return core.multiarray._reconstruct
        if name == 'scalar':
            def scalar(dtype, value):
                require(not dtype.hasobject and dtype.kind in 'biuf', 'Unsupported numpy scalar dtype')
                return core.multiarray.scalar(dtype, value)
            return scalar
        def frombuffer(buffer, dtype, shape, order):
            require(not dtype.hasobject and dtype.kind in 'biuf', 'Unsupported numpy array dtype')
            return core.numeric._frombuffer(buffer, dtype, shape, order)
        return frombuffer

    def persistent_load(self, pid):
        raise ContractError('External references are not supported in M3 pickle imports')


def json_value(value, *, arrays_as_lists=False):
    if value is None or type(value) in (str, int, float, bool):
        return value
    if type(value) is bytes:
        return {'encoding': 'base64', 'python_type': 'bytes', 'data': base64.b64encode(value).decode('ascii')}
    if type(value) in (tuple, list):
        return [json_value(v, arrays_as_lists=arrays_as_lists) for v in value]
    if type(value) is dict:
        require(all(type(k) in (str, int) for k in value), 'Unsupported M3 metadata map key')
        require(len({str(k) for k in value}) == len(value), 'Colliding M3 metadata keys')
        return {str(k): json_value(v, arrays_as_lists=arrays_as_lists) for k, v in value.items()}
    # Lazy numpy import only after a pickle actually contains numerical arrays.
    if type(value).__module__.startswith('numpy'):
        import numpy as np
        require(isinstance(value, (np.ndarray, np.generic)), 'Unsupported numpy object')
        require(not value.dtype.hasobject and value.dtype.kind in 'biuf', 'Unsupported M3 array dtype')
        if isinstance(value, np.generic):
            return value.item()
        values = value.tolist()
        if arrays_as_lists:
            return values
        return {'encoding': 'ndarray', 'dtype': str(value.dtype), 'shape': list(value.shape), 'values': values}
    raise ContractError('Unsupported M3 metadata object; no opaque object was imported')


def graph_to_document(graph, *, video_id: str) -> dict:
    require(type(graph) is _Graph, 'M3 pickle does not contain a VideoGraph')
    require(type(getattr(graph, 'nodes', None)) is dict and type(getattr(graph, 'edges', None)) is dict,
            'M3 graph is missing nodes or edges')
    nodes = []
    for key, node in graph.nodes.items():
        require(type(node) is _Node, 'Unsupported M3 node object')
        require(type(key) in (str, int) and str(key) == str(getattr(node, 'id', None)), 'M3 node key/ID mismatch')
        payload = {k: json_value(v) for k, v in vars(node).items() if k != 'embeddings'}
        vectors = getattr(node, 'embeddings', [])
        payload['embeddings'] = json_value(vectors, arrays_as_lists=True)
        # Preserve ndarray dtype/shape instead of only retaining converted floats.
        payload['embeddings_storage'] = json_value(vectors)
        nodes.append(payload)
    edges = []
    for key, weight in graph.edges.items():
        require(type(key) is tuple and len(key) == 2, 'Unsupported M3 edge key')
        edges.append({'source': json_value(key[0]), 'target': json_value(key[1]), 'weight': json_value(weight)})
    result = {k: json_value(v) for k, v in vars(graph).items() if k not in ('nodes', 'edges')}
    require('video_id' not in result or result['video_id'] == video_id, 'Conflicting M3 video identity')
    result.update({'video_id': video_id, 'nodes': nodes, 'edges': edges})
    FrozenMap(result)
    return result


def read_m3_pickle(path: str | Path, *, options: LoadOptions, source_id: str | None = None) -> SourceDocument:
    path = Path(path)
    label = source_id or path.name
    require(path.is_file() and path.stat().st_size <= options.max_file_bytes, 'Missing/oversized M3 pickle')
    raw = path.read_bytes()
    require(len(raw) <= options.max_file_bytes, 'M3 pickle file-size limit exceeded')
    try:
        stream = BytesIO(raw)
        graph = _M3Unpickler(stream).load()
        require(stream.read(1) == b'', 'Trailing data after M3 pickle')
    except (pickle.UnpicklingError, EOFError, ValueError, TypeError, AttributeError) as ex:
        raise ContractError('M3 pickle is invalid or uses an unsupported value representation') from None
    data = graph_to_document(graph, video_id=options.namespace or options.sample_id or path.stem)
    return SourceDocument(source_id=label, data=data, sha256=sha256(raw).hexdigest())
