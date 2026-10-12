"""Legacy clock/order profiles and benchmark cutoffs, with scripted services only."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import re
import tempfile
import unittest

from memfolder.compression import ServiceMap, OriginalArchive
from memfolder.core import (AlgorithmContext, ContractError, FrozenMap,
    NullDiagnostics, OperatorContext, PlanningRequest, dumps, loads, to_data)
from memfolder.experiment import assemble_experiment, verify_experiment
from memfolder.loading import (Importer, LoadOptions, M3Adapter, Mem0Adapter, MemOSAdapter,
    load_library, save_library)
from memfolder.loading.factories import options_from_mapping
from memfolder.operators.text import ChronologicalMembers, ConservativeRecordBuilder
from memfolder.operators.types import TextWriteResult
from memfolder.wrappers.codecs import MemOSCodec
from memfolder.wrappers.types import NativeArchive
from memfolder.planning.features import SemanticEmbeddingFeatures
from memfolder.planning.recordfolder import TemporalCandidates
from test_loading import document
from test_temporal_tome import SPACE

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = AlgorithmContext(services=ServiceMap(), diagnostics=NullDiagnostics())
EXAMPLES = ROOT / 'examples/experiments'


class Encoder:
    cache_identity = 'offline.temporal.encoder.v1'
    def encode(self, texts):
        return tuple((1., float(len(text) % 11 + 1)) for text in texts)


class Chat:
    cache_identity = 'offline.temporal.chat.v1'
    def __init__(self):
        self.requests = []
    def complete(self, request):
        self.requests.append(request)
        if request.role == 'memory_grounding':
            return '{"entities": ["alice"]}'
        if request.role == 'memory_merge':
            return '; '.join(re.findall(r'Memory \d+: (.*?), Timestamp \d+:', request.prompt))
        if request.role == 'memory_qa':
            return 'tea'
        if request.role == 'memforest_judge':
            return '{"label": "CORRECT"}'
        if request.role == 'fact_extract':
            return '{"facts": []}'
        raise AssertionError('Unexpected scripted request: ' + request.role)


class Words:
    measurement_id = 'offline.words'
    def count(self, text):
        return len(text.split())


def points():
    return {'points': [
        {'id': 'b', 'payload': {'data': 'older memory', 'user_id': 'synthetic',
            'timestamp': 'Unknown', 'created_at': '2026-09-15T10:00:00Z'}},
        {'id': 'a', 'payload': {'data': 'newer memory', 'user_id': 'synthetic',
            'timestamp': 'Unknown', 'created_at': '2026-09-15T11:00:00Z'}}]}


def import_points(value, **options):
    return Importer(adapter=Mem0Adapter(), options=LoadOptions(**options)).load_documents((document(value),))


class TemporalProfileTests(unittest.TestCase):
    def test_created_at_is_explicit_and_default_does_not_invent_event_time(self):
        value = points()
        default = import_points(value).inputs[0].initial_snapshot
        self.assertTrue(all(not node.time_ranges for node in default.records))
        library = import_points(value, timestamp_fields=['created_at'], time_semantics='creation_time', order_by='time_id')
        records = library.inputs[0].initial_snapshot.records
        self.assertEqual([node.native['id'] for node in records], ['b', 'a'])
        self.assertTrue(all(node.time_ranges and node.available_at is None for node in records))
        self.assertEqual(records[0].extensions['memfolder.temporal_source']['semantics'], 'creation_time')
        self.assertEqual(records[0].native['record']['payload']['timestamp'], 'Unknown')
        self.assertEqual(value, points())

    def test_fallback_fields_and_nested_paths_do_not_guess_numeric_units(self):
        value = points()
        value['points'][0]['payload']['metadata'] = {'custom': {'when': '2026-09-15T09:00:00Z'}}
        library = import_points(value, timestamp_fields=['metadata.custom.when', 'created_at'], order_by='time_id')
        self.assertEqual(library.inputs[0].initial_snapshot.records[0].extensions['memfolder.temporal_source']['selected_field'],
                         'metadata.custom.when')
        value['points'][0]['payload']['created_at'] = 7
        with self.assertRaises(ContractError):
            import_points(value, timestamp_fields=['created_at'], order_by='time_id')
        result = import_points(value, timestamp_fields=['created_at'], numeric_timestamp_clock='unix_seconds')
        self.assertEqual(result.inputs[0].initial_snapshot.records[0].time_ranges[0].start.value, 7)

    def test_unknown_first_reproduces_sort_sentinel_without_inventing_a_date(self):
        value = points()
        value['points'].append({'id': 'unknown', 'payload': {'data': 'unknown time', 'user_id': 'synthetic'}})
        with self.assertRaises(ContractError):
            import_points(value, timestamp_fields=['created_at'], order_by='time_id')
        result = import_points(value, timestamp_fields=['created_at'], order_by='time_id', missing_time_order='first')
        records = result.inputs[0].initial_snapshot.records
        self.assertEqual([node.native['id'] for node in records], ['unknown', 'b', 'a'])
        self.assertFalse(records[0].time_ranges)

    def test_memos_uses_declared_ts_and_native_id_for_ties(self):
        value = {'nodes': [{'id': name, 'memory': name, 'ts': time, 'metadata': {'cube_id': 'synthetic'}}
            for name, time in [('z', '2026-09-15T09:00:00Z'), ('b', '2026-09-15T08:00:00Z'),
                               ('a', '2026-09-15T09:00:00Z')]]}
        result = Importer(adapter=MemOSAdapter(), options=LoadOptions(
            timestamp_fields=['ts'], time_semantics='memory_time', order_by='time_id')).load_documents((document(value),))
        self.assertEqual([node.native['id'] for node in result.inputs[0].initial_snapshot.records], ['b', 'a', 'z'])

    def test_m3_keeps_numeric_order_clip_scopes_and_visibility_clocks(self):
        value = json.loads((EXAMPLES / 'tiny_temporal/m3.json').read_text())
        result = Importer(adapter=M3Adapter(), options=LoadOptions(order_by='numeric_native_id')).load_documents((document(value),))
        records = result.inputs[0].initial_snapshot.records
        clip = [node for node in records if node.eligible and node.scope.partition_id == 'clip:0']
        self.assertEqual([node.native['id'] for node in clip], ['3', '10'])
        self.assertTrue(all(not node.time_ranges for node in records))
        self.assertTrue(all(node.available_at.clock == 'm3:synthetic-video:clip' for node in clip))
        self.assertEqual(clip[0].extensions['memfolder.event_timestamp'], '0')
        self.assertEqual(sum(not node.eligible for node in records), 3)

    def test_numeric_id_policy_rejects_noninteger_ids_and_numeric_collisions(self):
        for ids in (('a', '2'), ('01', '1')):
            value = points()
            for point, name in zip(value['points'], ids):
                point['id'] = name
            with self.assertRaises(ContractError):
                import_points(value, order_by='numeric_native_id')

    def test_candidates_use_imported_order_and_a_node_count_window(self):
        value = points()
        value['points'].append({'id': 'c', 'payload': {'data': 'third memory', 'user_id': 'synthetic',
            'created_at': '2026-09-15T12:00:00Z'}})
        snapshot = import_points(value, timestamp_fields=['created_at'], order_by='time_id').inputs[0].initial_snapshot
        features = asyncio.run(SemanticEmbeddingFeatures(space=SPACE).extract(
            snapshot, replace(CONTEXT, services=ServiceMap({'embeddings': Encoder()}))))
        request = PlanningRequest(run_id='offline.temporal', snapshot=snapshot, features=(features,))
        candidates = TemporalCandidates(use_entities=False, temporal_order='order', window=1).generate(request, CONTEXT)
        ids = {node.node_id: node.native['id'] for node in snapshot.records}
        self.assertEqual([(ids[c.source_id], ids[c.target_id]) for c in candidates.candidates], [('b', 'a'), ('a', 'c')])

    def test_member_resolver_preserves_explicit_order_in_equal_time_groups(self):
        from memfolder.core import Action
        value = points()
        value['points'][1]['payload']['created_at'] = value['points'][0]['payload']['created_at']
        snapshot = import_points(value, timestamp_fields=['created_at'], order_by='time_id').inputs[0].initial_snapshot
        action = Action(action_id='merge', kind='merge', member_ids=tuple(n.node_id for n in reversed(snapshot.records)),
                        output_ids=('output',), input_view='original')
        context = OperatorContext(services=ServiceMap(), diagnostics=NullDiagnostics(), originals=OriginalArchive(snapshot))
        _, members = ChronologicalMembers(order_by='order').resolve(action, snapshot, context)
        self.assertEqual([member.text for member in members], ['newer memory', 'older memory'])

    def test_profile_metadata_survives_canonical_roundtrip_and_remapping_is_rejected(self):
        library = import_points(points(), timestamp_fields=['created_at'], time_semantics='creation_time', order_by='time_id')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'library.json'
            save_library(library, path)
            self.assertEqual(load_library(path), library)
            with self.assertRaises(ContractError):
                load_library(path, options=LoadOptions(timestamp_fields=['created_at']))

    def test_invalid_time_configuration_is_rejected(self):
        for values in ({'timestamp_fields': []}, {'timestamp_fields': ['a..b']},
                       {'timestamp_fields': ['ts', 'ts']}, {'missing_time_order': 'guess'}):
            with self.assertRaises(ContractError):
                options_from_mapping(values)

    def test_native_memos_rewrites_nested_and_numeric_clock_fields_without_unit_conversion(self):
        from memfolder.core import Action
        for field in ('ts','metadata.custom.clock'):
            with self.subTest(field=field):
                rows=[]
                for index in (2,1):
                    row={'id':str(index),'memory':'memory '+str(index),'metadata':{'cube_id':'synthetic'}}
                    if field=='ts':row['ts']=index*100
                    else:row['metadata']['custom']={'clock':index*100}
                    rows.append(row)
                snapshot=Importer(adapter=MemOSAdapter(),options=LoadOptions(
                    timestamp_fields=[field],numeric_timestamp_clock='source_counter',
                    time_semantics='memory_time',order_by='time_id')).load_documents((document({'nodes':rows}),)).inputs[0].initial_snapshot
                action=Action(action_id='merge',kind='merge',member_ids=tuple(n.node_id for n in snapshot.records),
                              output_ids=('merged',),input_view='current')
                output=ConservativeRecordBuilder(timestamp_policy='latest').build(
                    snapshot.records,action,TextWriteResult(text='merged memory'),CONTEXT)
                native=MemOSCodec().encode(replace(snapshot,records=(output,)),NativeArchive(snapshot),CONTEXT)
                meta=native.data['nodes'][0]['metadata']
                self.assertEqual(meta['timestamp'],200)
                self.assertEqual(meta['ts'] if field=='ts' else meta['custom']['clock'],200)

    def test_latest_output_policy_retains_m3_clip_label_without_event_dates(self):
        from memfolder.core import Action
        value=json.loads((EXAMPLES/'tiny_temporal/m3.json').read_text())
        snapshot=Importer(adapter=M3Adapter(),options=LoadOptions(order_by='numeric_native_id')).load_documents((document(value),)).inputs[0].initial_snapshot
        inputs=tuple(n for n in snapshot.records if n.eligible and n.scope.partition_id=='clip:0')
        action=Action(action_id='merge',kind='merge',member_ids=tuple(n.node_id for n in inputs),
                      output_ids=('merged',),input_view='current',parameters=FrozenMap({'timestamp_policy':'latest'}))
        output=ConservativeRecordBuilder().build(inputs,action,TextWriteResult(text='merged memory'),CONTEXT)
        self.assertEqual(output.extensions['memfolder.event_timestamp'],'0')
        self.assertEqual(output.extensions['memfolder.temporal_source']['semantics'],'clip_index')
        self.assertFalse(output.time_ranges)

    def test_prefix_banks_refuse_missing_source_positions_and_drop_future_before_planning(self):
        config = json.loads((EXAMPLES / 'personamem-mem0-template.json').read_text())
        assembly = assemble_experiment(config, base_path=EXAMPLES)
        item = next(assembly.dataset.samples())
        memory = asyncio.run(assembly.initializer.initialize(item.memory, CONTEXT))
        self.assertEqual(len(memory.initial_snapshot.records), 4)
        self.assertNotIn('FUTURE_ONLY', dumps(memory))
        self.assertEqual(memory.initial_snapshot.extensions['memfolder.history_prefix']['exclusive_end'], 4)
        broken = replace(assembly.initializer, prefix_end_field='payload.missing')
        with self.assertRaises(ContractError):
            asyncio.run(broken.initialize(item.memory, CONTEXT))
        with self.assertRaises(ContractError):
            asyncio.run(assembly.initializer.initialize(memory, CONTEXT))
        empty = asyncio.run(assembly.initializer.initialize(replace(item.memory, history=()), CONTEXT))
        self.assertEqual(len(empty.initial_snapshot.records), 0)

    def test_public_templates_record_and_context_qa_judge_roundtrip_without_future_leak(self):
        for name in ('personamem-mem0', 'personamem-memos', 'm3-recordfolder'):
            for context in (False, True):
                with self.subTest(template=name, context=context), tempfile.TemporaryDirectory() as folder:
                    config = json.loads((EXAMPLES / (name + '-template.json')).read_text())
                    config.pop('services')
                    config['output_dir'] = str(Path(folder) / 'run')
                    config['compression']['features'][0]['parameters']['space'] = to_data(SPACE)
                    wrapper = config['compression']['wrapper']['parameters']
                    if 'embedding_provider' in wrapper:
                        wrapper['embedding_provider']['parameters']['space'] = to_data(SPACE)
                    if context:
                        config['compression']['planner']['plugin'] = 'contextfolder'
                        config['compression']['operator']['plugin'] = 'contextfolder-operator'
                    chat = Chat()
                    assembly = assemble_experiment(config, base_path=EXAMPLES)
                    result = asyncio.run(assembly.run(services={'chat': chat, 'grounding': chat,
                        'judge': chat, 'embeddings': Encoder(), 'tokenizer': Words()}))
                    stat = result.samples[0].statistics
                    self.assertEqual((stat.input_eligible, stat.output_eligible), (2, 1) if name == 'm3-recordfolder' else (4, 2))
                    self.assertEqual(result.manifest.evaluation_status, 'completed')
                    root=Path(config['output_dir'])
                    final=loads((root/result.samples[0].final.path).read_text())
                    native=loads(((root/result.samples[0].materialized.path).parent/'native.package.json').read_text())
                    if name=='personamem-memos':
                        rows={row['id']:row for row in native.data['nodes']}
                        for node in final.records:
                            if len(node.origins)>1:
                                row=rows[native.node_id_map[node.node_id]]
                                self.assertEqual(row['metadata']['ts'],node.extensions['memfolder.event_timestamp'])
                                self.assertEqual(row['metadata']['timestamp'],row['metadata']['ts'])
                    if name=='m3-recordfolder':
                        self.assertEqual(sum(not node.eligible for node in final.records),3)
                        self.assertTrue(all(not node.time_ranges for node in final.records))
                        merged=[node for node in final.records if node.eligible]
                        self.assertEqual(merged[0].extensions['memfolder.event_timestamp'],'0')
                    self.assertNotIn('FUTURE_ONLY', '\n'.join(request.prompt for request in chat.requests))
                    expected={'memory_merge':'memforest.shared.v1.merge',
                              'memory_qa':'memfolder.reader.memforest_prompt.v1',
                              'memforest_judge':'memforest.shared.v1.judge'}
                    self.assertTrue(all(request.prompt_id==expected[request.role]
                        for request in chat.requests if request.role in expected))
                    verify_experiment(root)

    def test_m3_web_keeps_per_clip_budget_minimum_and_protected_nodes(self):
        config = json.loads((EXAMPLES / 'm3-recordfolder-template.json').read_text())
        config.pop('services')
        config['dataset']['parameters'].update(variant='web', question_ids=['web-full'])
        config['compression']['features'][0]['parameters']['space'] = to_data(SPACE)
        config['compression']['wrapper']['parameters']['embedding_provider']['parameters']['space'] = to_data(SPACE)
        with tempfile.TemporaryDirectory() as folder:
            config['output_dir'] = str(Path(folder) / 'run')
            result = asyncio.run(assemble_experiment(config, base_path=EXAMPLES).run(services={
                'chat': Chat(), 'grounding': Chat(), 'judge': Chat(), 'embeddings': Encoder()}))
            self.assertEqual((result.samples[0].statistics.input_eligible, result.samples[0].statistics.output_eligible), (5, 3))
            verify_experiment(Path(config['output_dir']))


if __name__ == '__main__':
    unittest.main()
