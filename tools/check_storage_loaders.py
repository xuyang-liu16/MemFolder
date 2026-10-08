"""Optional real-SDK storage checks in a temporary directory, with no model/API calls.

Run with an environment containing numpy/qdrant-client, or provide --sdk-path.
The fixture data are synthetic; these are not benchmark runs.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
parser = argparse.ArgumentParser()
parser.add_argument('--sdk-path', type=Path)
args = parser.parse_args()
if args.sdk_path:
    import site
    # Windows pywin32 uses .pth entries for its DLL and module directories.
    site.addsitedir(str(args.sdk_path.resolve()))
    sys.path.insert(0, str(args.sdk_path.resolve()))
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))

import numpy as np
from qdrant_client import QdrantClient, models
from memfolder.core import EmbeddingSpace, FrozenMap, dumps
from memfolder.loading import LoadOptions, load_mem0_qdrant, load_mem0_sqlite, native_vector_sets

suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_loading.py')
result = unittest.TextTestRunner(verbosity=1).run(suite)
assert result.wasSuccessful() and not result.skipped, 'All loading tests, including numpy, must pass'


def hashes(root):
    return {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


with tempfile.TemporaryDirectory(prefix='memfolder-sdk-test-') as folder:
    source = Path(folder) / 'mem0' / 'qdrant'
    client = QdrantClient(path=str(source))
    try:
        client.create_collection('mem0', vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE))
        rows = [models.PointStruct(id=i, vector=[0.1 + i, 0.2, 0.3], payload={
            'data': f'中文记忆 {i}\n', 'user_id': 'alice' if i < 4 else 'bob',
            'timestamp': '9:00 am on 4 October, 2026', 'metadata': {'source_id': f'dia-{i}'}}) for i in range(7)]
        client.upsert('mem0', points=rows)
        native_rows, native_offset = client.scroll('mem0', limit=100, with_vectors=True, with_payload=True)
        assert native_offset is None
        expected = {str(p.id): (p.payload, tuple(p.vector)) for p in native_rows}
        client.create_collection('named', vectors_config={
            'a': models.VectorParams(size=3, distance=models.Distance.COSINE),
            'b': models.VectorParams(size=2, distance=models.Distance.DOT)},
            sparse_vectors_config={'bm25': models.SparseVectorParams()})
        client.upsert('named', points=[models.PointStruct(id=99, payload={'data': 'named slots', 'user_id': 'alice'},
            vector={'a': [1., 0., 0.], 'b': [3., 4.], 'bm25': models.SparseVector(indices=[1, 5], values=[0.2, 0.5])})])
    finally:
        client.close()
    # Compare with persisted SDK reads, rather than pre-close in-memory vectors:
    # cosine stores may normalize while loading persisted float32 arrays.
    reference = QdrantClient(path=str(source))
    try:
        persisted, final_offset = reference.scroll('mem0', limit=100, with_vectors=True, with_payload=True)
        assert final_offset is None
        expected = {str(p.id): (p.payload, tuple(p.vector)) for p in persisted}
    finally:
        reference.close()
    before = hashes(source)
    library = load_mem0_qdrant(source.parent, page_size=2, options=LoadOptions(
        naive_timezone='UTC', embedding_spaces={'default': EmbeddingSpace(
            provider='test', model='synthetic-3d', revision='1', dimension=3)}))
    assert library.report.samples_loaded == 2 and library.report.records_loaded == 7
    records = [n for i in library.inputs for n in i.initial_snapshot.records]
    for n in records:
        payload, vector = expected[n.native['id']]
        assert n.text == payload['data'] and n.embeddings[0].values == vector
        assert n.native['record']['payload'] == FrozenMap(payload)
        assert n.origins[0].source_id == n.native['id']
    # Two source imports must produce identical canonical identity/content.
    again = load_mem0_qdrant(source, page_size=2, options=LoadOptions(
        naive_timezone='UTC', embedding_spaces={'default': EmbeddingSpace(
            provider='test', model='synthetic-3d', revision='1', dimension=3)}))
    assert again == library
    named = load_mem0_qdrant(source, collection='named', page_size=1)
    node = named.inputs[0].initial_snapshot.records[0]
    assert {s.slot for s in native_vector_sets(node)} == {'a', 'b'}
    assert node.native['record']['vector']['bm25']['indices'] == (1, 5)
    # Real PointStruct/SparseVector persisted pickles, read with no model imports.
    sqlite = load_mem0_sqlite(source / 'collection/mem0/storage.sqlite')
    assert sqlite.report.records_loaded == 7
    sql_named = load_mem0_sqlite(source / 'collection/named/storage.sqlite')
    sql_node = sql_named.inputs[0].initial_snapshot.records[0]
    assert {s.slot for s in native_vector_sets(sql_node)} == {'a', 'b'}
    assert sql_node.native['record']['vector']['bm25']['indices'] == (1, 5)
    assert native_vector_sets(sql_node)[1].vectors == ((3., 4.),)
    assert hashes(source) == before, 'Original storage bytes changed'
    assert '中文记忆' in dumps(library)

report = {'status': 'passed', 'loading_tests': result.testsRun, 'skipped': 0,
    'python_version': sys.version.split()[0], 'numpy_version': np.__version__,
    'qdrant_client_version': importlib.metadata.version('qdrant-client'),
    'real_qdrant_collections': 2, 'real_qdrant_records': 8,
    'real_qdrant_page_size': 2, 'named_and_sparse_vectors': 'passed',
    'sqlite_persisted_models_and_sparse_vectors': 'passed',
    'original_storage_bytes_unchanged': True, 'numpy_pickle_protocols': [4, 5],
    'data_kind': 'synthetic native storage', 'user_libraries_tested': 0, 'benchmark_runs': 0}
report['source_sha256'] = {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
    for base in ('src', 'tests', 'examples') for p in sorted((ROOT / base).rglob('*.py'))}
(ROOT / 'build/storage_validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({k: v for k, v in report.items() if k != 'source_sha256'}))
