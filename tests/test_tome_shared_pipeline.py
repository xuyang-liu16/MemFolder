"""Public ToMe compositions use common features/operator, with no paid calls."""
import asyncio
from dataclasses import replace
import importlib.util
import json
import math
from pathlib import Path
import re
import tempfile
import unittest

from memfolder.assembly import assemble
from memfolder.compression import CompressionEngine, ServiceMap
from memfolder.core import BudgetRequest, ContractError, resolve_budget, to_data
from memfolder.experiment import assemble_experiment, verify_experiment
from memfolder.operators import ConservativeRecordBuilder, NativeSummaryWriter, TextOperator
from memfolder.planning import (TemporalTomePlanner, RecordFolderPlanner, TemporalCandidates,
    FusedAffinity, MemForestPlanner, JointClusters, MstPairRouter, PartitionPlanner,
    KmeansClusters)
from memfolder.planning.features import SemanticEmbeddingFeatures
from memfolder.services import CachedService
from memfolder.wrappers.embedding import ChangedTextEmbeddings
from memfolder.wrappers.codecs import Mem0Codec
from memfolder.wrappers.types import NativeArchive
from test_experiment import CTX
from test_temporal_tome import fixture, SPACE

ROOT=Path(__file__).resolve().parents[1]


def raw_request(n=6,target=3):
    request=fixture(n=n,target=target)
    snapshot=replace(request.snapshot,records=tuple(replace(node,embeddings=())
                     for node in request.snapshot.records))
    return replace(request,snapshot=snapshot,features=(),budgets=(resolve_budget(
        snapshot,BudgetRequest(unit='nodes',limit=target)),))


class Encoder:
    cache_identity='test.tome.shared.encoder.v1'
    def __init__(self):self.calls=[]
    def encode(self,texts):
        self.calls.append(tuple(texts))
        return tuple((-1.,0.) if 'memory0.0' in text and 'memory0.3' in text
                     else (1.,0.) for text in texts)


class Chat:
    cache_identity='test.tome.shared.chat.v1'
    def __init__(self):self.requests=[]
    def complete(self,request):
        self.requests.append(request)
        if request.role=='memory_merge':
            members=re.findall(r'Memory \d+: (.*?), Timestamp \d+:',request.prompt)
            return '; '.join(members) or 'Alice likes tea'
        if request.role=='memforest_judge':return '{"label":"CORRECT"}'
        if request.role=='memory_qa':return 'tea'
        if request.role=='fact_extract':return '{"facts":[]}'
        raise AssertionError('Unexpected scripted request: '+request.role)


def execute(request,encoder=None,planner=None):
    encoder=encoder or Encoder();chat=Chat()
    engine=CompressionEngine(planner or TemporalTomePlanner(),TextOperator(),
                             (SemanticEmbeddingFeatures(space=SPACE),))
    result=asyncio.run(engine.run(request,services=ServiceMap({'chat':chat,'embeddings':encoder})))
    pairs=[action for step in result.steps for action in step.planning.plan.actions
           if action.kind=='merge']
    return result,pairs,encoder,chat


class SharedTomeTests(unittest.TestCase):
    def test_raw_text_uses_common_operator_and_live_semantics(self):
        request=raw_request()
        result,pairs,encoder,chat=execute(request)
        self.assertEqual(len(result.snapshot.records),3)
        self.assertEqual([pair.output_ids[0] for pair in pairs],
                         ['p0.n003','p0.n004','p0.n004'])
        self.assertTrue(all(not node.embeddings for node in request.snapshot.records))
        self.assertTrue(all(not node.embeddings for node in result.snapshot.records))
        # The updated n003 text is encoded before the second match; its changed
        # direction makes n004 the best destination instead of frozen n003.
        self.assertTrue(any('memory0.0' in text and 'memory0.3' in text
                            for text in encoder.calls[1]))
        self.assertEqual(len(chat.requests),3)
        self.assertTrue(all(request.prompt_id=='memforest.shared.v1.merge'
                            for request in chat.requests))
        self.assertEqual(sum(len(node.origins) for node in result.snapshot.records),6)

    def test_same_public_features_and_operator_work_with_other_planners(self):
        class DistinctEncoder:
            def encode(self, texts):
                return tuple((math.cos(index), math.sin(index))
                             for index in range(len(texts)))

        planners=(RecordFolderPlanner(candidates=TemporalCandidates(use_entities=False,
                    temporal_order='order'),scorer=FusedAffinity(mode='no_entity')),
                  MemForestPlanner(clusterer=JointClusters(time_order='order'),
                                   router=MstPairRouter(time_order='order')),
                  PartitionPlanner(partitioner=KmeansClusters()),TemporalTomePlanner())
        for planner in planners:
            with self.subTest(planner=type(planner).__name__):
                result,_,_,_=execute(raw_request(),DistinctEncoder(),planner=planner)
                self.assertEqual(len(result.snapshot.records),3)

    def test_cache_only_calls_encoder_for_new_text_and_final_materialization(self):
        provider=Encoder()
        with tempfile.TemporaryDirectory() as folder:
            encoder=CachedService(provider,Path(folder)/'embeddings.sqlite','shared.space.v1')
            result,_,_,_=execute(raw_request(),encoder)
            context=replace(CTX,services=ServiceMap({'embeddings':encoder}))
            refreshed=asyncio.run(ChangedTextEmbeddings(space=SPACE).refresh(result.snapshot,context))
            self.assertEqual([len(batch) for batch in provider.calls],[6,1,1,1])
            self.assertEqual(len(refreshed.records),3)
            self.assertTrue(all(node.embeddings[0].source_fingerprint==node.content_fingerprint
                                for node in refreshed.records))

    def test_common_builder_retains_destination_time_order_and_native_projection(self):
        request=raw_request()
        # Storage order intentionally differs from chronological order.
        request=replace(request,snapshot=replace(request.snapshot,
                        records=tuple(reversed(request.snapshot.records))))
        result,pairs,encoder,_=execute(request)
        destination=next(node for node in result.snapshot.records if node.node_id=='p0.n003')
        self.assertEqual(destination.order,3)
        self.assertEqual(destination.extensions['memfolder.timestamp_policy'],'latest')
        self.assertEqual(destination.extensions['memfolder.event_timestamp'],
                         '1970-01-01T00:00:03+00:00')
        self.assertEqual(len(destination.time_ranges),2)
        context=replace(CTX,services=ServiceMap({'embeddings':encoder}))
        refreshed=asyncio.run(ChangedTextEmbeddings(space=SPACE).refresh(result.snapshot,context))
        native=Mem0Codec(space=SPACE).encode(refreshed,NativeArchive(request.snapshot),context)
        point=next(point for point in native.data['points'] if point['id'].endswith('0004'))
        self.assertEqual(point['payload']['timestamp'],'1970-01-01T00:00:03+00:00')
        self.assertEqual(tuple(point['vector']),destination_vector(refreshed,'p0.n003'))

    def test_optional_stored_vector_selector_and_builder_are_not_default_requirements(self):
        for name in ('text-operator','tome-operator','recordfolder-operator'):
            assembled=assemble({'planner':{'plugin':'tome'},'operator':{'plugin':name},
                'features':[{'plugin':'semantic-encoder','parameters':{'space':to_data(SPACE)}}]})
            self.assertIsInstance(assembled.engine.operator.writer,NativeSummaryWriter)
            self.assertIsInstance(assembled.engine.operator.record_builder,ConservativeRecordBuilder)
            result=asyncio.run(assembled.engine.run(raw_request(),
                services=ServiceMap({'chat':Chat(),'embeddings':Encoder()})))
            self.assertEqual(len(result.snapshot.records),3)

    def test_repeat_halves_owner_boundaries_and_partial_final_pass(self):
        result,pairs,_,_=execute(raw_request(n=9,target=2))
        self.assertEqual(len(result.snapshot.records),2)
        self.assertEqual([pair.parameters['half_pass'] for pair in pairs],[0,0,0,0,1,1,2])
        original=fixture(n=4,scopes=2,target=2)
        snapshot=replace(original.snapshot,records=tuple(replace(n,embeddings=())
                         for n in original.snapshot.records))
        request=replace(original,snapshot=snapshot,budgets=(resolve_budget(snapshot,
                        BudgetRequest(unit='nodes',limit=2)),))
        result,_,_,_=execute(request)
        self.assertEqual(len(result.snapshot.records),4)
        self.assertTrue(all(len({origin.scope for origin in node.origins})==1
                            for node in result.snapshot.records))

    def test_invalid_encoder_dimensions_fail_before_summary_calls(self):
        class BadEncoder:
            def encode(self,texts):return tuple((1.,) for text in texts)
        chat=Chat()
        engine=CompressionEngine(TemporalTomePlanner(),TextOperator(),
                                 (SemanticEmbeddingFeatures(space=SPACE),))
        with self.assertRaises(ContractError):
            asyncio.run(engine.run(raw_request(),services=ServiceMap(
                        {'chat':chat,'embeddings':BadEncoder()})))
        self.assertEqual(chat.requests,[])

    def test_full_public_history_template_qa_judge_and_dense_readback(self):
        for dense in (False, True):
            with self.subTest(dense=dense), tempfile.TemporaryDirectory() as folder:
                config=json.loads((ROOT/'examples/experiments/tome-template.json').read_text())
                config.pop('services')
                config['compression']['features'][0]['parameters']['space']=to_data(SPACE)
                if dense:
                    config['compression']['wrapper']['parameters']['embedding_provider']={
                        'plugin':'content-embeddings','parameters':{'space':to_data(SPACE)}}
                    config['reader']['parameters']['retriever']={
                        'plugin':'dense-retriever','parameters':{'space':to_data(SPACE)}}
                config['output_dir']=str(Path(folder)/'run')
                assembly=assemble_experiment(config,base_path=ROOT/'examples/experiments')
                result=asyncio.run(assembly.run(services={'chat':Chat(),'judge':Chat(),
                                                         'embeddings':Encoder()}))
                self.assertEqual((result.samples[0].statistics.input_eligible,
                                  result.samples[0].statistics.output_eligible),(4,2))
                self.assertEqual(result.manifest.evaluation_status,'completed')
                verify_experiment(Path(config['output_dir']))

    def test_record_then_context_example_accepts_raw_input_and_explicit_space(self):
        spec=importlib.util.spec_from_file_location('test_shared_stage_example',ROOT/'examples/record_then_context.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        class Words:
            measurement_id='test.words'
            def count(self,text):return len(text.split())
        services=ServiceMap({'chat':Chat(),'embeddings':Encoder(),'tokenizer':Words()})
        record,context=asyncio.run(module.record_then_context(raw_request(),services=services,
            context_method='contextfolder',embedding_space=SPACE))
        self.assertEqual(len(record.snapshot.records),3)
        self.assertEqual(len(context.snapshot.records),3)
        self.assertEqual({n.node_id for n in record.snapshot.records},
                         {n.node_id for n in context.snapshot.records})


def destination_vector(snapshot,node_id):
    return next(node for node in snapshot.records if node.node_id==node_id).embeddings[0].values


if __name__=='__main__':unittest.main()
