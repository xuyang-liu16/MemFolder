"""Read persisted Qdrant points without SDK initialization or collection metadata.

Only data models are recognized in pickles, and replaced with inert containers.
No Qdrant/Pydantic constructors, imports or pickle-provided functions are called.
"""
from __future__ import annotations

import base64
from contextlib import closing
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import pickle
import shutil
import sqlite3
import tempfile
from uuid import UUID

from memfolder.core import ContractError, FrozenMap
from memfolder.core.values import require
from .readers import SourceDocument
from .types import LoadOptions


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
