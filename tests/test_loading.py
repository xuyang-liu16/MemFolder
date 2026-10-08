"""Memory imports: native format semantics, complete paging, provenance, and failure cases."""
from dataclasses import replace
from contextlib import closing
from hashlib import sha256
import json
import base64
import sqlite3
from pathlib import Path
import pickle
import subprocess
import sys
import tempfile
import types
import unittest

from memfolder.core import (
    ContractError, ContentPart, EmbeddingSpace, EvaluationCase, EvaluationSet, FrozenMap,
    RetentionPolicy, dumps, fingerprint, loads,
)
from memfolder.loading import (
    Importer, LoadOptions, M3Adapter, Mem0Adapter, MemOSAdapter, NativeLibrary, NativeRecord,
    SourceDocument, attach_evaluation, load_library, load_m3, load_mem0, load_mem0_client,
    load_mem0_legacy_nodes, load_mem0_qdrant, load_memos_cube, native_vector_sets, read_json, save_library,
    load_mem0_sqlite,
)


def document(data, name='fixture'):
    return SourceDocument(source_id=name, data=data, sha256=fingerprint(data))


def mem0_row(nid='p1', user='alice', text=' 记忆 A\n'):
    return {'id': nid, 'payload': {'data': text, 'user_id': user,
            'timestamp': '9:00 am on 4 October, 2026', 'custom': {'role': 'user', 'score': 3}},
            'vector': [0.1, 0.2, 0.3]}


def m3_document():
    return {'video_id': 'robot/bedroom', 'nodes': [
        {'id': 0, 'type': 'img', 'metadata': {'contents': ['base64-image']}, 'embeddings': [[0.1, 0.2], [0.3, 0.4]]},
        {'id': 1, 'type': 'voice', 'metadata': {'contents': ['voice-reference']}, 'embeddings': [[0.5, 0.6]]},
        {'id': 2, 'type': 'semantic', 'metadata': {'contents': ['Equivalence: <voice_1> is <face_0>'], 'timestamp': 0}, 'embeddings': [[0.1, 0.9]]},
        {'id': 3, 'type': 'episodic', 'metadata': {'contents': ['Alice speaks.', 'The door opens.'], 'timestamp': 0}, 'embeddings': [[0.2, 0.8], [0.3, 0.7]]},
        {'id': 4, 'type': 'semantic', 'metadata': {'contents': ['Alice likes tea.'], 'timestamp': 1}, 'embeddings': [[0.4, 0.6]]}],
        'edges': [{'source': 0, 'target': 3, 'weight': 2.5}, {'source': 3, 'target': 0, 'weight': 2.5}],
        'text_nodes': [3, 2, 4], 'text_nodes_by_clip': {'0': [3, 2], '1': [4]},
        'event_sequence_by_clip': {'0': [3]},
        'character_mappings': {'character_0': ['face_0', 'voice_1']},
        'reverse_character_mappings': {'face_0': 'character_0', 'voice_1': 'character_0'}, 'next_node_id': 5}


def write_legacy_pickle(path, data, *, module_name='mmagent.videograph', protocol=4, numpy_arrays=False, numpy_dtype='float32'):
    """Official names/attributes, without importing the original model/config runtime."""
    module = types.ModuleType(module_name)
    exec('class VideoGraph:\n    class Node:\n        pass\n', module.__dict__)
    parent = types.ModuleType('mmagent')
    parent.__path__ = []
    names = ['mmagent', module_name]
    previous = {name: sys.modules.get(name) for name in names}
    sys.modules['mmagent'] = parent
    sys.modules[module_name] = module
    parent.videograph = module
    try:
        graph = module.VideoGraph()
        for key, value in data.items():
            if key not in ('nodes', 'edges', 'video_id'):
                if key in ('text_nodes_by_clip', 'event_sequence_by_clip'):
                    value = {int(k): v for k, v in value.items()}
                setattr(graph, key, value)
        graph.nodes = {}
        for row in data['nodes']:
            node = module.VideoGraph.Node()
            for key, value in row.items():
                if numpy_arrays and key == 'embeddings':
                    import numpy as np
                    value = [np.array(v, dtype=numpy_dtype) for v in value]
                setattr(node, key, value)
            graph.nodes[row['id']] = node
        graph.edges = {(r['source'], r['target']): r['weight'] for r in data['edges']}
        path.write_bytes(pickle.dumps(graph, protocol=protocol))
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def write_points_sqlite(path, rows):
    """Exact persisted class names/state, without requiring Qdrant or Pydantic."""
    name = 'qdrant_client.http.models.models'
    module = types.ModuleType(name)
    exec('class PointStruct:\n    def __getstate__(self):\n        return {"__dict__":vars(self),"__pydantic_extra__":None,"__pydantic_private__":None,"__pydantic_fields_set__":set(vars(self))}\n', module.__dict__)
    names = ['qdrant_client', 'qdrant_client.http', 'qdrant_client.http.models', name]
    previous = {n: sys.modules.get(n) for n in names}
    for n in names[:-1]:
        parent = types.ModuleType(n)
        parent.__path__ = []
        sys.modules[n] = parent
    sys.modules[name] = module
    try:
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute('CREATE TABLE points (id TEXT PRIMARY KEY, point BLOB)')
            for row in rows:
                point = module.PointStruct()
                vars(point).update(row)
                key = base64.b64encode(pickle.dumps(row['id'])).decode('ascii')
                connection.execute('INSERT INTO points VALUES (?,?)', (key, pickle.dumps(point)))
    finally:
        for n, old in previous.items():
            if old is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = old


class MemoryLoadingTests(unittest.TestCase):
    def import_mem0(self, data, **options):
        return Importer(adapter=Mem0Adapter(), options=LoadOptions(**options)).load_documents((document(data),))

    def test_mem0_points_preserve_exact_content_native_ids_and_unknown_fields(self):
        original = mem0_row()
        lib = self.import_mem0([original])
        node = lib.inputs[0].initial_snapshot.records[0]
        self.assertEqual(node.text, original['payload']['data'])
        self.assertEqual(node.origins[0].source_id, 'p1')
        self.assertEqual(node.native['record']['payload']['custom']['score'], 3)
        original['payload']['custom']['score'] = 99
        self.assertEqual(node.native['record']['payload']['custom']['score'], 3)
        self.assertEqual(len(native_vector_sets(node)[0].vectors[0]), 3)
        self.assertFalse(node.embeddings)
        self.assertIn('embedding_space_undeclared', [i.code for i in lib.report.issues])
        self.assertEqual(loads(dumps(lib)), lib)

    def test_mem0_api_exports_lists_results_legacy_metadata_and_whitespace(self):
        row = {'id': 'api-1', 'memory': ' ', 'metadata': {'user_id': 'alice', 'arbitrary': ['x']}}
        for data in ([row], {'results': [row]}, {'result': {'points': [mem0_row()]}}):
            lib = self.import_mem0(data)
            self.assertEqual(lib.report.records_loaded, 1)
        self.assertEqual(self.import_mem0([row]).inputs[0].initial_snapshot.records[0].text, ' ')

    def test_native_identity_conflict_and_absent_identity_require_explicit_scope(self):
        row = {'id': '1', 'memory': 'hello'}
        with self.assertRaises(ContractError):
            self.import_mem0([row])
        self.assertEqual(self.import_mem0([row], namespace='external').inputs[0].sample.sample_id, 'namespace:external')
        row.update({'user_id': 'a', 'metadata': {'user_id': 'b'}})
        with self.assertRaises(ContractError):
            self.import_mem0([row])

    def test_users_and_agent_run_namespaces_are_separate_and_explicit_grouping_retains_partitions(self):
        a, b = mem0_row(user='a'), mem0_row(user='b')
        lib = self.import_mem0([a, b])
        self.assertEqual({i.sample.sample_id for i in lib.inputs}, {'user_id:a', 'user_id:b'})
        grouped = self.import_mem0([a, b], sample_id='conversation-1')
        nodes = grouped.inputs[0].initial_snapshot.records
        self.assertEqual(len({n.scope.partition_id for n in nodes}), 2)
        self.assertEqual(len({n.node_id for n in nodes}), 2)
        b['payload']['user_id'] = 'a'
        b['payload']['run_id'] = 'r2'
        self.assertEqual(self.import_mem0([a, b]).report.records_loaded, 2)

    def test_owner_domain_collision_does_not_combine_user_and_agent(self):
        user = {'id': 'u1', 'memory': 'user memory', 'user_id': 'same-name'}
        agent = {'id': 'a1', 'memory': 'agent memory', 'agent_id': 'same-name'}
        lib = self.import_mem0([user, agent])
        self.assertEqual({i.sample.sample_id for i in lib.inputs}, {'user_id:same-name', 'agent_id:same-name'})

    def test_selectors_use_exact_values_and_mappings_never_suffix_heuristics(self):
        rows = [mem0_row(user='participant_1'), mem0_row(user='participant_11')]
        lib = self.import_mem0(rows, selectors=FrozenMap({'user_id': 'participant_1'}),
                               sample_map=FrozenMap({'user_id:participant_1': 'locomo-1'}))
        self.assertEqual(lib.inputs[0].sample.sample_id, 'locomo-1')
        self.assertEqual(lib.report.records_filtered, 1)
        with self.assertRaises(ContractError):
            self.import_mem0(rows, selectors=FrozenMap({'typo_field': 'x'}))

    def test_named_and_sparse_vectors_are_preserved_without_selecting_the_first(self):
        row = mem0_row()
        row['vector'] = {'dense_a': [1., 2.], 'dense_b': [3., 4., 5.],
                         'bm25': {'indices': [1, 5], 'values': [0.5, 0.2]}}
        lib = self.import_mem0([row])
        node = lib.inputs[0].initial_snapshot.records[0]
        self.assertEqual({s.slot for s in native_vector_sets(node)}, {'dense_a', 'dense_b'})
        self.assertEqual(node.native['record']['vector']['bm25']['indices'], (1, 5))
        self.assertFalse(node.embeddings)

    def test_embedding_binding_requires_explicit_space_and_validates_dimension(self):
        space = EmbeddingSpace(provider='test', model='dense', revision='v1', dimension=3)
        lib = self.import_mem0([mem0_row()], embedding_spaces={'default': space})
        node = lib.inputs[0].initial_snapshot.records[0]
        self.assertEqual(node.embeddings[0].space, space)
        self.assertEqual(node.embeddings[0].source_fingerprint, node.content_fingerprint)
        self.assertFalse(native_vector_sets(node)[0].content_verified)
        with self.assertRaises(ContractError):
            self.import_mem0([mem0_row()], embedding_spaces={'default': replace(space, dimension=2)})

    def test_missing_content_duplicate_ids_invalid_numbers_fail_instead_of_skipping(self):
        for data in ([mem0_row(), mem0_row()], [{'id': '1', 'user_id': 'a'}],
                     [dict(mem0_row(), vector=[float('nan'), 1.])], [dict(mem0_row(), vector=[True, 1])]):
            with self.assertRaises(ContractError):
                self.import_mem0(data)
        a = document([mem0_row()], 'a')
        b = document([mem0_row()], 'b')
        with self.assertRaises(ContractError):
            Importer(adapter=Mem0Adapter()).load_documents((a, b))

    def test_plain_nested_json_fingerprint_equals_immutable_json_fingerprint(self):
        data = {'rows': [{'nested': [1, {'unicode': '记忆'}]}]}
        self.assertEqual(fingerprint(data), fingerprint(FrozenMap(data)))

    def test_time_zone_is_explicit_unknown_times_never_turn_into_zero(self):
        lib = self.import_mem0([mem0_row()])
        node = lib.inputs[0].initial_snapshot.records[0]
        self.assertFalse(node.time_ranges)
        self.assertIn('timestamp_unparsed', [i.code for i in lib.report.issues])
        lib = self.import_mem0([mem0_row()], naive_timezone='UTC')
        self.assertGreater(lib.inputs[0].initial_snapshot.records[0].time_ranges[0].start.value, 1_000_000)
        row = mem0_row()
        row['payload']['timestamp'] = 'invalid'
        with self.assertRaises(ContractError):
            self.import_mem0([row], naive_timezone='UTC', order_by='time_id')

    def test_explicit_visibility_is_separate_from_event_time(self):
        row = mem0_row()
        row['payload']['created_at'] = '2026-10-04T12:00:00Z'
        node = self.import_mem0([row], visibility_field='created_at').inputs[0].initial_snapshot.records[0]
        self.assertEqual(node.available_at.clock, 'unix_seconds')
        self.assertFalse(node.time_ranges)
        with self.assertRaises(ContractError):
            self.import_mem0([row], visibility_field='missing')

    def test_mem0_partial_page_is_rejected_unless_explicitly_accepted(self):
        data = {'points': [mem0_row()], 'next_page_offset': 0}
        with self.assertRaises(ContractError):
            self.import_mem0(data)
        lib = self.import_mem0(data, allow_partial=True)
        self.assertEqual(lib.report.sources[0].coverage, 'partial')

    def test_qdrant_scroll_exhausts_all_pages_including_zero_offset(self):
        class Client:
            calls = []
            def scroll(self, **kwargs):
                self.calls.append(kwargs)
                index = len(self.calls)
                return [mem0_row(nid=str(index))], 0 if index == 1 else None
        client = Client()
        lib = load_mem0_client(client, page_size=1)
        self.assertEqual(lib.report.records_loaded, 2)
        self.assertEqual(client.calls[1]['offset'], 0)
        self.assertTrue(all(c['with_payload'] and c['with_vectors'] for c in client.calls))
        self.assertEqual(lib.report.sources[0].consistency, 'best_effort')

    def test_qdrant_repeated_offsets_or_rows_fail_and_record_limit_is_enforced(self):
        for duplicate in (True, False):
            class Client:
                index = 0
                def scroll(self, **kwargs):
                    self.index += 1
                    return [mem0_row(nid='1' if duplicate else str(self.index))], 1
            with self.assertRaises(ContractError):
                load_mem0_client(Client(), page_size=1)
        class Client:
            def scroll(self, **kwargs):
                return [mem0_row('1'), mem0_row('2')], None
        with self.assertRaises(ContractError):
            load_mem0_client(Client(), options=LoadOptions(max_records=1))

    def test_qdrant_dataset_identity_is_independent_of_page_size(self):
        class Client:
            def scroll(self, **kwargs):
                start = 0 if kwargs['offset'] is None else kwargs['offset']
                end = min(5, start + kwargs['limit'])
                return [mem0_row(str(i)) for i in range(start, end)], None if end == 5 else end
        small = load_mem0_client(Client(), page_size=1)
        large = load_mem0_client(Client(), page_size=3)
        self.assertEqual(small.inputs[0].sample.identity, large.inputs[0].sample.identity)
        self.assertEqual(small.inputs[0].initial_snapshot.records, large.inputs[0].initial_snapshot.records)

    def test_source_relocation_preserves_dataset_and_node_identity(self):
        importer = Importer(adapter=Mem0Adapter())
        a = importer.load_documents((document([mem0_row()], 'old-name'),))
        b = importer.load_documents((document([mem0_row()], 'new-name'),))
        self.assertEqual(a.inputs[0].sample.identity, b.inputs[0].sample.identity)
        self.assertEqual(a.inputs[0].initial_snapshot.records[0].node_id, b.inputs[0].initial_snapshot.records[0].node_id)

    def test_local_qdrant_opens_only_a_copy_and_closes_after_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'original'
            source.mkdir()
            (source / 'storage.sqlite').write_bytes(b'original')
            (source / 'meta.json').write_text(json.dumps({'collections': {'mem0': {}}}))
            (source / '.lock').write_bytes(b'lock')
            instances = []
            class Client:
                closed = False
                def __init__(self, path):
                    self.path = Path(path)
                    instances.append(self)
                    self.assertions()
                def assertions(self):
                    assert self.path != source and self.path.exists()
                    assert not (self.path / '.lock').exists()
                    (self.path / 'storage.sqlite').write_bytes(b'copy changed')
                def scroll(self, **kwargs):
                    raise RuntimeError('test error')
                def close(self):
                    self.closed = True
            with self.assertRaises(RuntimeError):
                load_mem0_qdrant(source, client_factory=Client)
            self.assertTrue(instances[0].closed)
            self.assertFalse(instances[0].path.exists())
            self.assertEqual((source / 'storage.sqlite').read_bytes(), b'original')
            self.assertEqual((source / '.lock').read_bytes(), b'lock')

    def test_qdrant_missing_metadata_fails_before_sdk_and_split_metadata_is_copied(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'bank'
            source.mkdir()
            (source / 'storage.sqlite').write_bytes(b'original')
            instances = []
            class Client:
                def __init__(self, path):
                    self.path = Path(path)
                    instances.append(self)
                    assert (self.path / 'meta.json').is_file()
                def scroll(self, **kwargs):
                    return [mem0_row()], None
                def close(self):
                    self.closed = True
            with self.assertRaisesRegex(ContractError, 'meta.json is missing'):
                load_mem0_qdrant(source, client_factory=Client)
            self.assertFalse(instances)
            meta = root / 'split-meta.json'
            meta.write_text(json.dumps({'collections': {'mem0': {}}}))
            lib = load_mem0_qdrant(source, metadata_path=meta, client_factory=Client)
            self.assertEqual(lib.report.records_loaded, 1)
            self.assertTrue(instances[0].closed)
            self.assertFalse((source / 'meta.json').exists())
            self.assertEqual((source / 'storage.sqlite').read_bytes(), b'original')

    def test_sqlite_without_metadata_retains_exact_vectors_payload_and_sample_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'storage.sqlite'
            rows = [mem0_row('a', 'User_0'), mem0_row(7, 'Assistant_0')]
            rows[0]['vector'] = [3., 4., 0.]
            write_points_sqlite(path, rows)
            before = path.read_bytes()
            lib = load_mem0_sqlite(path, options=LoadOptions(sample_id='s000'))
            self.assertEqual((lib.report.samples_loaded, lib.report.records_loaded), (1, 2))
            nodes = lib.inputs[0].initial_snapshot.records
            indexed = {str(r['id']): r for r in rows}
            self.assertEqual(len({n.scope.partition_id for n in nodes}), 2)
            for node in nodes:
                row = indexed[node.native['id']]
                self.assertEqual(node.native['record'], FrozenMap(row))
                self.assertEqual(node.text, row['payload']['data'])
                self.assertEqual(native_vector_sets(node)[0].vectors[0], tuple(row['vector']))
                self.assertEqual(node.origins[0].source_id, str(row['id']))
            self.assertEqual(lib.report.sources[0].coverage, 'unknown')
            selected = load_mem0_sqlite(path, options=LoadOptions(selectors={'user_id': ['User_0']}))
            self.assertEqual((selected.report.records_loaded, selected.report.records_filtered), (1, 1))
            self.assertEqual(loads(dumps(lib)), lib)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['storage.sqlite'])

    def test_sqlite_rejects_active_wal_mismatched_key_trailing_data_and_code_globals(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'storage.sqlite'
            write_points_sqlite(path, [mem0_row()])
            wal = root / 'storage.sqlite-wal'
            wal.write_bytes(b'active')
            with self.assertRaisesRegex(ContractError, 'active journal/WAL'):
                load_mem0_sqlite(path)
            wal.unlink()
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute('UPDATE points SET id=?', (base64.b64encode(pickle.dumps('wrong')).decode(),))
            with self.assertRaisesRegex(ContractError, 'key does not match'):
                load_mem0_sqlite(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                original = connection.execute('SELECT point FROM points').fetchone()[0]
                connection.execute('UPDATE points SET point=?', (original + b'trailing',))
            with self.assertRaisesRegex(ContractError, 'Trailing data'):
                load_mem0_sqlite(path)
            marker = root / 'executed'
            class Exploit:
                def __reduce__(self):
                    return (eval, (f'__import__("pathlib").Path({str(marker)!r}).write_text("bad")',))
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute('UPDATE points SET point=?', (pickle.dumps(Exploit()),))
            with self.assertRaisesRegex(ContractError, 'unsupported pickle global'):
                load_mem0_sqlite(path)
            self.assertFalse(marker.exists())

    def test_sqlite_limits_and_invalid_database_do_not_return_empty_success(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'storage.sqlite'
            path.write_bytes(b'not SQLite')
            with self.assertRaises(ContractError):
                load_mem0_sqlite(path)
            with self.assertRaisesRegex(ContractError, 'file-size limit'):
                load_mem0_sqlite(path, options=LoadOptions(max_file_bytes=1))
            path.unlink()
            write_points_sqlite(path, [mem0_row('1'), mem0_row('2')])
            with self.assertRaisesRegex(ContractError, 'record limit'):
                load_mem0_sqlite(path, options=LoadOptions(max_records=1))

    def test_mem0_entity_relations_are_preserved_without_inventing_memory_edges(self):
        data = {'results': [{'id': 'x', 'memory': 'tea', 'user_id': 'a'}],
                'relations': [{'source': 'alice', 'relationship': 'likes', 'destination': 'tea'}]}
        lib = self.import_mem0(data)
        self.assertEqual(lib.report.edges_loaded, 0)
        meta = lib.inputs[0].initial_snapshot.extensions['memfolder.import']['sources']['fixture']['metadata']
        self.assertEqual(meta['relations'][0]['relationship'], 'likes')

    def test_memos_tree_preserves_relations_weights_status_provenance_and_embeddings(self):
        data = {'nodes': [{'id': '1', 'memory': 'hello', 'metadata': {'cube_id': 'cube-a',
                'memory_type': 'LongTermMemory', 'embedding': [0.1, 0.2], 'sources': [{'message_id': 'm1'}]}},
                {'id': '2', 'memory': 'archived', 'metadata': {'cube_id': 'cube-a', 'status': 'archived'}}],
                'edges': [{'source': '1', 'target': '2', 'type': 'CONFLICT', 'weight': 0.7}],
                'total_nodes': 2, 'total_edges': 1}
        lib = Importer(adapter=MemOSAdapter()).load_documents((document(data),))
        snapshot = lib.inputs[0].initial_snapshot
        self.assertEqual(snapshot.edges[0].relation, 'CONFLICT')
        self.assertEqual(snapshot.edges[0].weight, 0.7)
        self.assertEqual(lib.report.eligible_records, 1)
        archived = next(n for n in snapshot.records if n.native['id'] == '2')
        self.assertEqual(archived.retention, RetentionPolicy(may_drop=False, may_merge=False, may_rewrite=False))
        self.assertEqual(snapshot.records[0].native['record']['metadata']['sources'][0]['message_id'], 'm1')
        self.assertEqual(lib.report.sources[0].coverage, 'declared_complete')

    def test_memos_dangling_edges_and_partial_totals_are_not_swallowed(self):
        data = {'nodes': [{'id': '1', 'memory': 'hello'}],
                'edges': [{'source': '1', 'target': 'missing', 'type': 'NEXT'}]}
        options = LoadOptions(namespace='cube')
        with self.assertRaises(ContractError):
            Importer(adapter=MemOSAdapter(), options=options).load_documents((document(data),))
        data.update({'edges': [], 'total_nodes': 2, 'total_edges': 0})
        with self.assertRaises(ContractError):
            Importer(adapter=MemOSAdapter(), options=options).load_documents((document(data),))

    def test_memos_cube_uses_configured_file_and_keeps_opaque_components_without_config_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = {'cube_id': 'cube-a', 'text_mem': {'backend': 'naive_text', 'config': {
                'memory_filename': 'custom.json', 'extractor_llm': {'api_key': 'synthetic-test-secret'}}},
                'act_mem': {'backend': 'kv_cache', 'config': {}}, 'para_mem': {'backend': 'uninitialized'}}
            (root / 'config.json').write_text(json.dumps(config), encoding='utf-8')
            (root / 'custom.json').write_text(json.dumps([{'id': '1', 'memory': '记忆', 'metadata': {'unknown': 7}}]), encoding='utf-8')
            (root / 'activation_memory.pickle').write_bytes(b'not executed, opaque reference')
            before = {p.name: sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
            lib = load_memos_cube(root)
            self.assertEqual(lib.report.records_loaded, 2)
            self.assertEqual(lib.report.eligible_records, 1)
            snapshot = lib.inputs[0].initial_snapshot
            self.assertEqual(snapshot.assets[0].path, 'activation_memory.pickle')
            self.assertNotIn('synthetic-test-secret', dumps(lib))
            self.assertEqual(before, {p.name: sha256(p.read_bytes()).hexdigest() for p in root.iterdir()})

    def test_memos_cube_missing_file_and_path_escape_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for filename in ('missing.json', '../outside.json'):
                config = {'cube_id': 'a', 'text_mem': {'backend': 'naive_text', 'config': {'memory_filename': filename}}}
                (root / 'config.json').write_text(json.dumps(config))
                with self.assertRaises(ContractError):
                    load_memos_cube(root)

    def test_m3_preserves_all_nodes_contents_multi_vectors_edges_clip_and_identity_indexes(self):
        lib = Importer(adapter=M3Adapter()).load_documents((document(m3_document()),))
        snapshot = lib.inputs[0].initial_snapshot
        self.assertEqual(lib.report.records_loaded, 5)
        self.assertEqual(lib.report.eligible_records, 2)
        self.assertEqual(lib.report.edges_loaded, 2)
        self.assertEqual([e.weight for e in snapshot.edges], [2.5, 2.5])
        text = [n for n in snapshot.records if n.kind in ('episodic', 'semantic')]
        self.assertEqual([n.native['id'] for n in text], ['3', '2', '4'])
        self.assertEqual(text[0].text, 'Alice speaks.\nThe door opens.')
        self.assertEqual(len(native_vector_sets(text[0])[0].vectors), 2)
        self.assertEqual(text[0].scope.partition_id, 'clip:0')
        self.assertEqual(text[2].scope.partition_id, 'clip:1')
        self.assertEqual(text[2].available_at.clock, 'm3:robot/bedroom:clip')
        equivalence = next(n for n in snapshot.records if n.native['id'] == '2')
        self.assertFalse(equivalence.eligible)
        self.assertFalse(equivalence.retention.may_merge)
        meta = snapshot.extensions['memfolder.import']['sources']['fixture']['metadata']
        self.assertEqual(meta['character_mappings']['character_0'], ('face_0', 'voice_1'))

    def test_m3_multiple_embeddings_have_no_implicit_mean_or_first_vector(self):
        space = EmbeddingSpace(provider='test', model='text', revision='1', dimension=2)
        lib = Importer(adapter=M3Adapter(), options=LoadOptions(embedding_spaces={'episodic': space})).load_documents((document(m3_document()),))
        node = next(n for n in lib.inputs[0].initial_snapshot.records if n.kind == 'episodic')
        self.assertFalse(node.embeddings)
        self.assertEqual(len(native_vector_sets(node)[0].vectors), 2)
        self.assertEqual(native_vector_sets(node)[0].space, space)
        self.assertIn('multiple_vectors_preserved', [i.code for i in lib.report.issues])

    def test_m3_inconsistent_retrieval_indexes_timestamps_and_graph_edges_fail(self):
        for key, value in (('text_nodes', [4]), ('text_nodes_by_clip', {'0': [2, 3, 4]}),
                           ('event_sequence_by_clip', {'0': [2]}),
                           ('edges', [{'source': 0, 'target': 99, 'weight': 1.}])):
            data = m3_document()
            data[key] = value
            with self.assertRaises(ContractError):
                Importer(adapter=M3Adapter()).load_documents((document(data),))
        data = m3_document()
        data['nodes'][3]['metadata']['timestamp'] = '0'
        with self.assertRaises(ContractError):
            Importer(adapter=M3Adapter()).load_documents((document(data),))

    def test_m3_character_indexes_missing_events_and_explicit_video_conflicts_fail(self):
        for key, value in (('character_mappings', {'character_0': ['face_99']}),
                           ('reverse_character_mappings', {'face_0': 'character_wrong'}),
                           ('event_sequence_by_clip', {})):
            data = m3_document()
            data[key] = value
            with self.assertRaises(ContractError):
                Importer(adapter=M3Adapter()).load_documents((document(data),))
        with self.assertRaises(ContractError):
            Importer(adapter=M3Adapter(), options=LoadOptions(namespace='other-video')).load_documents((document(m3_document()),))
        data = m3_document()
        data['text_nodes_by_clip']['99'] = []
        self.assertEqual(Importer(adapter=M3Adapter()).load_documents((document(data),)).report.records_loaded, 5)

    def test_contributor_invalid_vector_and_edge_shapes_do_not_bypass_validation(self):
        for vectors in ({'dense': [[1., True]]}, {'dense': [[1.], [1., 2.]]}, {'dense': [1., 2.]}):
            with self.assertRaises(ContractError):
                NativeRecord(native_id='x', namespace='store', sample_key='sample', partition_key='session',
                             parts=(ContentPart(modality='text', text='x'),), native=FrozenMap(), vectors=vectors)

    def test_m3_official_and_legacy_module_pickle_names_protocols_4_and_5(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bedroom.pkl'
            for module in ('mmagent.videograph', 'videograph'):
                for protocol in (4, 5):
                    write_legacy_pickle(path, m3_document(), module_name=module, protocol=protocol)
                    lib = load_m3(path, options=LoadOptions(namespace='robot/bedroom'))
                    self.assertEqual(lib.report.records_loaded, 5)
                    self.assertEqual(lib.report.edges_loaded, 2)
                    self.assertEqual(lib.report.eligible_records, 2)
                    self.assertNotIn(module, sys.modules)

    def test_m3_numpy_vectors_keep_float_values_dtype_shape_and_source_file(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest('optional numpy unavailable')
        if not hasattr(np, 'array'):
            self.skipTest('optional numpy is not a functional installation')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bedroom.pkl'
            for protocol in (4, 5):
                write_legacy_pickle(path, m3_document(), protocol=protocol, numpy_arrays=True)
                before = path.read_bytes()
                lib = load_m3(path)
                node = next(n for n in lib.inputs[0].initial_snapshot.records if n.native['id'] == '3')
                storage = node.native['record']['embeddings_storage']
                self.assertEqual(storage[0]['dtype'], 'float32')
                self.assertEqual(storage[0]['shape'], (2,))
                self.assertEqual(native_vector_sets(node)[0].vectors[0][0], float(np.float32(0.2)))
                self.assertEqual(path.read_bytes(), before)

    def test_m3_pickle_rejects_arbitrary_code_globals_and_object_arrays(self):
        with tempfile.TemporaryDirectory() as folder:
            sentinel = Path(folder) / 'must-not-exist'
            class Exploit:
                def __reduce__(self):
                    return eval, ("__import__('pathlib').Path(" + repr(str(sentinel)) + ").write_text('bad')",)
            path = Path(folder) / 'bad.pkl'
            path.write_bytes(pickle.dumps(Exploit()))
            with self.assertRaises(ContractError):
                load_m3(path)
            self.assertFalse(sentinel.exists())
            try:
                import numpy as np
            except ImportError:
                np = None
            if np is not None and hasattr(np, 'array'):
                write_legacy_pickle(path, m3_document(), numpy_arrays=True, numpy_dtype='object')
                with self.assertRaises(ContractError):
                    load_m3(path)
        # Unknown global is rejected before any callable can execute.

    def test_jsonl_bom_chinese_empty_lines_and_strict_json_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'memories.jsonl'
            path.write_text('\ufeff' + json.dumps(mem0_row(), ensure_ascii=False) + '\n\n' +
                json.dumps(mem0_row('p2'), ensure_ascii=False) + '\n', encoding='utf-8')
            lib = load_mem0(path)
            self.assertEqual(lib.report.records_loaded, 2)
            for text in ('{"id":"1","id":"2"}', '{"number":NaN}', '{"n":1e999}', 'invalid'):
                path.write_text(text, encoding='utf-8')
                with self.assertRaises(ContractError):
                    read_json(path, options=LoadOptions())

    def test_historical_mem0_jsonl_uses_original_point_id_and_reports_missing_time(self):
        row = {'node_id': 'locomo_1_memory_000001', 'text': '记忆', 'timestamp': 0,
               'embedding': [0.1, 0.2], 'source': {'dataset': 'LoCoMo', 'sample_id': 'locomo_1',
               'point_id': 'original-point', 'user_id': 'Alice_1'}, 'raw_pointer': 'original-point'}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'nodes.jsonl'
            path.write_text(json.dumps(row, ensure_ascii=False) + '\n', encoding='utf-8')
            lib = load_mem0_legacy_nodes(path)
            node = lib.inputs[0].initial_snapshot.records[0]
            self.assertEqual(node.origins[0].source_id, 'original-point')
            self.assertEqual(lib.inputs[0].sample.sample_id, 'locomo_1')
            self.assertEqual(node.native['record']['node_id'], row['node_id'])
            self.assertFalse(node.time_ranges)
            self.assertIn('legacy_zero_timestamp', [i.code for i in lib.report.issues])

    def test_numeric_event_time_needs_declared_clock(self):
        row = mem0_row()
        row['payload']['timestamp'] = 123.5
        unknown = self.import_mem0([row]).inputs[0].initial_snapshot.records[0]
        declared = self.import_mem0([row], numeric_timestamp_clock='video:seconds').inputs[0].initial_snapshot.records[0]
        self.assertFalse(unknown.time_ranges)
        self.assertEqual(declared.time_ranges[0].start.clock, 'video:seconds')
        self.assertEqual(declared.time_ranges[0].start.value, 123.5)

    def test_cli_import_writes_library_and_content_free_report_and_failure_writes_nothing(self):
        env = {**__import__('os').environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'memories.json'
            path.write_text(json.dumps([mem0_row(text='PRIVATE_MEMORY_TEXT')]))
            output = root / 'imported'
            cmd = [sys.executable, '-X', 'utf8', '-m', 'memfolder.loading', 'mem0', str(path), '--output-dir', str(output)]
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(load_library(output / 'library.json').report.records_loaded, 1)
            self.assertNotIn('PRIVATE_MEMORY_TEXT', (output / 'report.json').read_text())
            self.assertNotIn('PRIVATE_MEMORY_TEXT', result.stdout + result.stderr)
            path.write_text('{"invalid":"PRIVATE_MEMORY_TEXT"}')
            bad_output = root / 'failed'
            cmd[-1] = str(bad_output)
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(bad_output.exists())
            self.assertNotIn('PRIVATE_MEMORY_TEXT', result.stdout + result.stderr)
            protected_output = root / 'inside-source'
            cmd = [sys.executable, '-m', 'memfolder.loading', 'memos-cube', str(root), '--output-dir', str(protected_output)]
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('outside the original', result.stderr)
            self.assertFalse(protected_output.exists())

    def test_file_limits_and_empty_sources_are_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'small.json'
            path.write_text('[]')
            with self.assertRaises(ContractError):
                read_json(path, options=LoadOptions(max_file_bytes=1))
            lib = load_mem0(path)
            self.assertEqual(lib.report.records_loaded, 0)
            self.assertEqual(lib.report.issues[0].code, 'empty_source')
        with self.assertRaises(ContractError):
            self.import_mem0([mem0_row('1'), mem0_row('2')], max_records=1)

    def test_canonical_bundle_roundtrip_and_exclusive_output(self):
        lib = self.import_mem0([mem0_row()], sample_id='locomo-1')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'library.json'
            save_library(lib, path)
            self.assertEqual(load_library(path), lib)
            with self.assertRaises(FileExistsError):
                save_library(lib, path)
            with self.assertRaises(ContractError):
                load_library(path, options=LoadOptions(sample_id='changed'))

    def test_observers_receive_only_detached_immutable_memory_inputs_and_report(self):
        inputs, reports = [], []
        class Observer:
            def on_input(self, value):
                inputs.append(value)
                with self_test.assertRaises(AttributeError):
                    value.sample = None
                with self_test.assertRaises(TypeError):
                    value.initial_snapshot.records[0].native['record']['new'] = 'x'
            def on_report(self, value):
                reports.append(value)
        self_test = self
        importer = Importer(adapter=Mem0Adapter())
        plain = importer.load_documents((document([mem0_row()]),))
        observed = importer.load_documents((document([mem0_row()]),), observer=Observer())
        self.assertEqual(plain, observed)
        self.assertEqual(inputs, list(plain.inputs))
        self.assertEqual(reports, [plain.report])

    def test_evaluation_composition_is_explicit_and_labels_do_not_enter_imported_memory(self):
        lib = self.import_mem0([mem0_row()])
        sample = lib.inputs[0].sample
        evaluation = EvaluationSet(sample=sample, protocol_id='test', cases=(EvaluationCase(
            sample=sample, question_id='q1', question=(ContentPart(modality='text', text='question'),),
            ground_truth=FrozenMap({'answer': 'ONLY_IN_EVALUATOR'})),))
        joined = attach_evaluation(lib, (evaluation,))
        self.assertEqual(joined[0].evaluation, evaluation)
        self.assertNotIn('ONLY_IN_EVALUATOR', dumps(joined[0].memory))
        with self.assertRaises(ContractError):
            attach_evaluation(lib, ())

    def test_contributor_format_adapter_works_without_core_or_dispatcher_edits(self):
        class Adapter:
            framework = 'research-store'
            format_id = 'research.store.v1'
            def decode(self, data, *, options, source_id):
                return NativeLibrary(framework=self.framework, format_id=self.format_id, records=(NativeRecord(
                    native_id='x', namespace='experiment', sample_key='sample', partition_key='session',
                    parts=(ContentPart(modality='text', text=data['content']),), native=FrozenMap(data)),))
        lib = Importer(adapter=Adapter()).load_documents((document({'content': 'new format'}),))
        self.assertEqual(lib.inputs[0].initial_snapshot.records[0].text, 'new format')

    def test_loading_import_has_no_sdk_or_model_import_side_effects(self):
        script = "import sys; import memfolder.loading; assert not any(n in sys.modules for n in ['numpy','qdrant_client','mem0','memos','mmagent','torch','transformers'])"
        result = subprocess.run([sys.executable, '-c', script], env={
            **__import__('os').environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
