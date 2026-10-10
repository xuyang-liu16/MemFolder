"""Meeting-contract regression witnesses; scripted vectors are not benchmark scores."""
import asyncio
from collections import Counter
from dataclasses import replace
from uuid import UUID
import unittest

from memfolder.assembly import assemble
from memfolder.compression import CompressionEngine, DiagnosticCollector, ServiceMap
from memfolder.core import (BudgetRequest, ContentPart, ContractError, Embedding, EmbeddingSpace,
    FrozenMap, MemoryRecord, OriginRef, PlanningRequest, RetentionPolicy, ScopeRef, Snapshot,
    TimePoint, TimeRange, resolve_budget, AlgorithmContext, NullDiagnostics)
from memfolder.operators import ConcatWriter, TextOperator, TomeEmbeddingBuilder, TomePairWriter
from memfolder.planning import CurrentEmbeddings, TemporalTomePlanner, TomeRoundPlanner
from memfolder.wrappers.codecs import Mem0Codec
from memfolder.wrappers.types import NativeArchive

SPACE = EmbeddingSpace(provider='test',model='scripted',revision='temporal-v1',dimension=2)

def fixture(n=6, vectors=None, scopes=1, target=None):
    records=[]
    for owner in range(scopes):
        scope=ScopeRef(dataset_id='test',sample_id='s',partition_id='owner'+str(owner))
        for i in range(n):
            node=MemoryRecord(node_id=f'p{owner}.n{i:03}',scope=scope,order=i,
                origins=(OriginRef(scope=scope,source_id=f'o{owner}.{i}'),),
                parts=(ContentPart(modality='text',text=f'memory{owner}.{i}'),),
                time_ranges=(TimeRange(start=TimePoint(value=i,clock='unix_seconds'),
                                       end=TimePoint(value=i,clock='unix_seconds')),),
                native=FrozenMap({'framework':'mem0','id':str(UUID(int=owner*n+i+1)),
                    'record':{'payload':{'user_id':'owner'+str(owner),'timestamp':'old-native-time'}}}))
            vector=(vectors[i] if vectors else (1.,0.))
            records.append(replace(node,embeddings=(Embedding(space=SPACE,
                source_fingerprint=node.content_fingerprint,values=vector),)))
    snapshot=Snapshot(snapshot_id='test.temporal',records=tuple(records))
    budget=resolve_budget(snapshot,BudgetRequest(unit='nodes',limit=(n//2 if target is None else target)))
    return PlanningRequest(run_id='test.temporal',snapshot=snapshot,budgets=(budget,),mode='repeat')

class Encoder:
    def __init__(self, dynamic=False): self.calls=[]; self.dynamic=dynamic
    async def encode(self,texts):
        self.calls.append(tuple(texts))
        return tuple((-1.,0.) if self.dynamic and 'memory0.0' in s and 'memory0.3' in s
                     else (1.,0.) for s in texts)

def run(req, encoder=None, operator=None, **kwargs):
    encoder=encoder or Encoder()
    diagnostics=DiagnosticCollector()
    engine=CompressionEngine(TemporalTomePlanner(),
        operator or TextOperator(writer=ConcatWriter(),record_builder=TomeEmbeddingBuilder()),
        (CurrentEmbeddings(),))
    result=asyncio.run(engine.run(req,services=ServiceMap({'embeddings':encoder}),
                                 diagnostics=diagnostics,**kwargs))
    pairs=[a for step in result.steps for a in step.planning.plan.actions if a.kind=='merge']
    return result,pairs,encoder,diagnostics

class TemporalTomeTests(unittest.TestCase):
    def test_contiguous_temporal_halves_and_repeated_destination(self):
        req=fixture()
        result,pairs,encoder,_=run(req)
        self.assertEqual([a.member_ids for a in pairs],[
            ('p0.n000','p0.n003'),('p0.n001','p0.n003'),('p0.n002','p0.n003')])
        self.assertEqual(len(result.snapshot.records),3)
        destination=next(n for n in result.snapshot.records if n.node_id=='p0.n003')
        self.assertEqual(len(destination.origins),4)
        self.assertEqual(destination.extensions['memfolder.event_timestamp'],'1970-01-01T00:00:03+00:00')
        self.assertEqual(destination.order,3)
        self.assertEqual(destination.embeddings[0].source_fingerprint,destination.content_fingerprint)
        self.assertEqual(len(encoder.calls),3)
        self.assertIn('memory0.0',encoder.calls[1][0])
        self.assertIn('memory0.1',encoder.calls[1][0])

    def test_second_match_uses_generated_destination_embedding(self):
        vectors=[(1.,0.),(.95,.31),(1.,0.),(1.,0.),(.8,.6),(-1.,0.)]
        result,pairs,encoder,_=run(fixture(vectors=vectors),Encoder(dynamic=True))
        self.assertEqual(pairs[0].output_ids,('p0.n003',))
        # Frozen original vectors would choose n003 again. Its generated text
        # has vector(-1,0), so the next source must instead choose n004.
        self.assertEqual(pairs[1].output_ids,('p0.n004',))
        self.assertEqual(len(result.snapshot.records),3)

    def test_ratios_and_partial_final_half(self):
        for target,passes in [(70,{0:30}),(50,{0:50}),(30,{0:50,1:20})]:
            with self.subTest(target=target):
                result,pairs,_,_=run(fixture(n=100,target=target))
                self.assertEqual(len(result.snapshot.records),target)
                self.assertEqual(Counter(a.parameters['half_pass'] for a in pairs),passes)
                origins=[o for n in result.snapshot.records for o in n.origins]
                self.assertEqual(len(origins),100)
                self.assertEqual(len(set(origins)),100)

    def test_odd_size_and_repeated_halving(self):
        result,pairs,_,_=run(fixture(n=5,target=2))
        self.assertEqual(len(result.snapshot.records),2)
        self.assertEqual([a.parameters['half_pass'] for a in pairs],[0,0,1])
        result,pairs,_,_=run(fixture(n=9,target=1))
        self.assertEqual(len(result.snapshot.records),1)
        self.assertEqual(len(result.snapshot.records[0].origins),9)
        self.assertEqual(result.snapshot.records[0].extensions['memfolder.event_timestamp'],
                         '1970-01-01T00:00:08+00:00')

    def test_owner_isolation(self):
        result,pairs,_,_=run(fixture(n=6,scopes=2,target=3))
        self.assertEqual(len(result.snapshot.records),6)
        self.assertEqual(len(pairs),6)
        self.assertTrue(all(len({o.scope for o in n.origins})==1 for n in result.snapshot.records))

    def test_time_order_is_not_storage_order_and_latest_time_reaches_mem0(self):
        req=fixture()
        req=replace(req,snapshot=replace(req.snapshot,records=tuple(reversed(req.snapshot.records))))
        result,pairs,_,_=run(req)
        self.assertEqual(pairs[0].member_ids,('p0.n000','p0.n003'))
        package=Mem0Codec(space=SPACE).encode(result.snapshot,NativeArchive(req.snapshot),
            AlgorithmContext(services=ServiceMap(),diagnostics=NullDiagnostics()))
        point=next(p for p in package.data['points'] if p['id']==str(UUID(int=4)))
        self.assertEqual(point['payload']['timestamp'],'1970-01-01T00:00:03+00:00')

    def test_stale_embeddings_and_wrong_clock_fail(self):
        req=fixture()
        with self.assertRaisesRegex(ContractError,'Stale content embedding'):
            replace(req.snapshot.records[0],parts=(ContentPart(modality='text',text='changed'),))
        node=replace(req.snapshot.records[0],parts=(ContentPart(modality='text',text='changed'),),embeddings=())
        stale=replace(req,snapshot=replace(req.snapshot,records=(node,*req.snapshot.records[1:])))
        with self.assertRaisesRegex(ContractError,'Missing/stale'):
            run(stale)
        node=replace(req.snapshot.records[0],time_ranges=(TimeRange(start=TimePoint(value=0,clock='other'),
                                                                 end=TimePoint(value=0,clock='other')),))
        mixed=replace(req,snapshot=replace(req.snapshot,records=(node,*req.snapshot.records[1:])))
        with self.assertRaisesRegex(ContractError,'comparable'):
            run(mixed)

    def test_explicit_iteration_limit_and_protected_nodes(self):
        with self.assertRaisesRegex(ContractError,'max_rounds'):
            run(fixture(),max_rounds=1)
        req=fixture(target=1)
        nodes=tuple(replace(n,retention=RetentionPolicy(may_merge=False)) if i<2 else n
                    for i,n in enumerate(req.snapshot.records))
        with self.assertRaisesRegex(ContractError,'Protected'):
            run(replace(req,snapshot=replace(req.snapshot,records=nodes)))

    def test_default_iteration_limit_scales_with_input_size(self):
        result,pairs,_,_=run(fixture(n=514,target=257))
        self.assertEqual(len(result.steps),257)
        self.assertEqual(len(pairs),257)
        self.assertEqual(len(result.snapshot.records),257)

    def test_configuration_default_and_legacy_variant_are_separate(self):
        temporal=assemble({'planner':{'plugin':'tome'},'operator':{'plugin':'tome-operator'},
                          'features':[{'plugin':'current-embeddings'}]})
        legacy=assemble({'planner':{'plugin':'tome-bsm'},'operator':{'plugin':'recordfolder-operator'}})
        self.assertIsInstance(temporal.engine.planner,TemporalTomePlanner)
        self.assertIsInstance(legacy.engine.planner,TomeRoundPlanner)
        self.assertNotEqual(temporal.config_fingerprint,legacy.config_fingerprint)

    def test_pair_writer_consumes_current_two_texts(self):
        class Chat:
            def __init__(self): self.requests=[]
            async def complete(self,request): self.requests.append(request); return 'actual merged text'
        chat,encoder=Chat(),Encoder()
        req=fixture(n=4)
        engine=CompressionEngine(TemporalTomePlanner(),
            TextOperator(writer=TomePairWriter(),record_builder=TomeEmbeddingBuilder()),(CurrentEmbeddings(),))
        result=asyncio.run(engine.run(req,services=ServiceMap({'chat':chat,'embeddings':encoder})))
        self.assertEqual(len(chat.requests),2)
        self.assertIn('Memory 1: memory0.1',chat.requests[1].prompt)
        self.assertIn('Memory 2: actual merged text',chat.requests[1].prompt)
        self.assertEqual(len(result.snapshot.records),2)

if __name__=='__main__': unittest.main()
