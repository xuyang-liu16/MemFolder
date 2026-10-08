"""Planner/operator behavior, plugin composition and failure boundaries.

All model responses here are scripted test data, never benchmark QA results.
"""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import random
import tempfile
import unittest

from memfolder.core import *
from memfolder.assembly import assemble
from memfolder.catalog import default_registry
from memfolder.compression import (CompressionEngine,ServiceMap,OriginalArchive,DiagnosticCollector,
    NodeProjection,PruneGraphProjection)
from memfolder.planning import *
from memfolder.operators import *
from memfolder.plugins import PluginRegistry,PluginRequest
from fixtures import sample,SPACE,BENCHMARKS,FRAMEWORKS

try:
    import numpy as np
    NUMPY=callable(getattr(np,'array',None))
    if NUMPY:
        import scipy,sklearn
except ImportError: NUMPY=False


def sync(value):
    from memfolder.compression import resolved
    return asyncio.run(resolved(value))


CTX=AlgorithmContext(services=ServiceMap(),diagnostics=NullDiagnostics())


def request(n=9,*,target=4,mode='once',seed=7,graph=False):
    scope=ScopeRef(dataset_id='test',sample_id='s',partition_id='p')
    rng=random.Random(23)
    nodes=[];vectors=[]
    space=EmbeddingSpace(provider='test',model='scripted',revision='1',dimension=3)
    for i in range(n):
        node=MemoryRecord(node_id=f'n{i:02}',scope=scope,order=i,origins=(OriginRef(scope=scope,source_id=f'o{i}'),),
            kind='episodic',parts=(ContentPart(modality='text',text=f'Original memory {i} has factual details.'),),
            time_ranges=(TimeRange(start=TimePoint(value=i,clock='unix_seconds'),end=TimePoint(value=i,clock='unix_seconds')),))
        vector=tuple(rng.uniform(-1,1) for _ in range(3));vectors.append(vector)
        nodes.append(replace(node,embeddings=(Embedding(space=space,source_fingerprint=node.content_fingerprint,values=vector),)))
    edges=()
    if graph:
        for i in range(2):
            nodes.append(MemoryRecord(node_id=f'media{i}',scope=scope,order=100+i,origins=(OriginRef(scope=scope,source_id=f'media{i}'),),
                kind='voice' if i else 'img',eligible=False,parts=(ContentPart(modality='structured',data=FrozenMap({'modality':'test'})),),
                retention=RetentionPolicy(may_drop=False,may_merge=False,may_rewrite=False)))
        edges=tuple(GraphEdge(edge_id=f'e{i}.{orientation}',source_id=f'n{i:02}' if orientation==0 else f'media{i%2}',
            target_id=f'media{i%2}' if orientation==0 else f'n{i:02}',relation='m3.connection',weight=float(i+1)) for i in range(n//2) for orientation in range(2))
    snapshot=Snapshot(snapshot_id='test.snapshot',records=tuple(nodes),edges=edges)
    semantic=FeatureBatch(name='semantic',input_fingerprint=snapshot.fingerprint,space=space,
        rows=tuple(FeatureRow(node_id=node.node_id,vector=vector) for node,vector in zip(nodes,vectors)))
    entities=FeatureBatch(name='entities',input_fingerprint=snapshot.fingerprint,
        rows=tuple(FeatureRow(node_id=node.node_id,values=FrozenMap({'entities':[f'entity{i%3}',f'entity{i%4}'],
            'event_time':float(i),'clock':'unix_seconds'})) for i,node in enumerate(nodes[:n])))
    temporal=replace(entities,name='temporal')
    budgets=(resolve_budget(snapshot,BudgetRequest(unit='nodes',limit=target)),) if target is not None else ()
    return PlanningRequest(run_id='test',snapshot=snapshot,budgets=budgets,features=(semantic,entities,temporal),mode=mode,seed=seed)


def apply(req,planner,writer=ConcatWriter()):
    plan=sync(planner.plan(req,CTX)).plan
    ctx=OperatorContext(services=ServiceMap(),diagnostics=NullDiagnostics(),originals=OriginalArchive(req.snapshot))
    result=sync(TextOperator(writer).apply(req.snapshot,plan,ctx))
    return plan,result,result_records(req.snapshot,plan,result)


class ScriptedChat:
    def __init__(self,responses):self.responses=list(responses);self.requests=[]
    def complete(self,req):
        self.requests.append(req)
        if not self.responses:raise AssertionError('Unexpected model call')
        value=self.responses.pop(0)
        if isinstance(value,Exception):raise value
        return value


class Words:
    measurement_id='test.whitespace.words'  # deliberately not cl100k
    def count(self,text):return len(text.split())


def operator_context(snapshot,chat=None):
    return OperatorContext(services=ServiceMap({'chat':chat,'tokenizer':Words()}),diagnostics=DiagnosticCollector(),
                           originals=OriginalArchive(snapshot))


class OperatorTests(unittest.TestCase):
    def test_native_one_call_original_prompt_and_no_embedding_reuse(self):
        req=request(n=2,target=1);plan=sync(PartitionPlanner(RandomGroups()).plan(req,CTX)).plan
        chat=ScriptedChat(['Actual combined summary.']);ctx=operator_context(req.snapshot,chat)
        result=sync(TextOperator().apply(req.snapshot,plan,ctx))
        self.assertEqual(len(chat.requests),1);self.assertEqual(chat.requests[0].temperature,0)
        self.assertIn('Memory 2:',chat.requests[0].prompt)
        output=result.outputs[0];self.assertEqual(output.text,'Actual combined summary.')
        self.assertEqual(output.embeddings,());self.assertEqual(len(output.origins),2)

    def test_keep_and_drop_do_not_use_any_model_service(self):
        req=request(n=4,target=2,graph=True);plan=sync(PrunePlanner().plan(req,CTX)).plan
        result=sync(RuleOperator().apply(req.snapshot,plan,operator_context(req.snapshot)))
        for a,o in zip(plan.actions,result.outcomes):
            if a.kind=='keep':self.assertIs(o.outputs[0],next(n for n in req.snapshot.records if n.node_id==a.member_ids[0]))
        projected=PruneGraphProjection().project(req.snapshot,plan,result,CTX)
        self.assertTrue(all(e.source_id in {n.node_id for n in projected.records} and e.target_id in {n.node_id for n in projected.records} for e in projected.edges))
        self.assertEqual(len([n for n in projected.records if not n.eligible]),2)

    def test_original_view_resolves_all_original_members_after_previous_merge(self):
        req=request(n=3,target=2);plan,result,_=apply(req,PartitionPlanner())
        projected=NodeProjection().project(req.snapshot,plan,result,CTX)
        merged=next(n for n in projected.records if len(n.origins)>1)
        final=ActionPlan(plan_id='second',input_fingerprint=projected.fingerprint,target_ids=tuple(n.node_id for n in projected.records),
            actions=(Action(action_id='merge',kind='merge',input_view='original',member_ids=tuple(n.node_id for n in projected.records),output_ids=(merged.node_id,)),))
        ctx=operator_context(req.snapshot,ScriptedChat(['Final summary.']))
        sync(TextOperator().apply(projected,final,ctx))
        self.assertIn('Memory 3:',ctx.services.require('chat').requests[0].prompt)
        self.assertNotIn('; ',ctx.services.require('chat').requests[0].prompt.split('Memory 1:')[1])

    def test_bad_original_archive_cannot_invent_origins(self):
        req=request(n=2,target=1);plan=sync(PartitionPlanner().plan(req,CTX)).plan
        bad=OriginalArchive(request(n=1,target=1).snapshot)
        with self.assertRaises(ContractError):sync(TextOperator(ConcatWriter()).apply(req.snapshot,plan,replace(operator_context(req.snapshot),originals=bad)))

    def test_merge_conserves_modality_and_retention_and_visibility(self):
        req=request(n=2,target=1);a,b=req.snapshot.records
        a=replace(a,parts=a.parts+(ContentPart(modality='image',data=FrozenMap({'image':'asset'})),),embeddings=(),
            retention=RetentionPolicy(may_drop=False,may_merge=True,may_rewrite=False),available_at=TimePoint(value=3,clock='unix_seconds'))
        b=replace(b,available_at=TimePoint(value=5,clock='unix_seconds'),expires_at=TimePoint(value=9,clock='unix_seconds'))
        snapshot=replace(req.snapshot,records=(a,b));plan=ActionPlan(plan_id='p',input_fingerprint=snapshot.fingerprint,target_ids=(a.node_id,b.node_id),
            actions=(Action(action_id='a',kind='merge',member_ids=(a.node_id,b.node_id),output_ids=(b.node_id,)),))
        output=sync(TextOperator(ConcatWriter()).apply(snapshot,plan,operator_context(snapshot))).outputs[0]
        self.assertFalse(output.retention.may_drop);self.assertFalse(output.retention.may_rewrite)
        self.assertEqual(output.available_at.value,5);self.assertEqual(output.expires_at.value,9)
        self.assertEqual(output.parts[1].modality,'image')

    def test_stale_plan_fails_before_model_call(self):
        req=request(n=2,target=1);plan=sync(PartitionPlanner().plan(req,CTX)).plan;chat=ScriptedChat([])
        with self.assertRaises(ContractError):sync(TextOperator().apply(replace(req.snapshot,revision=1),plan,operator_context(req.snapshot,chat)))
        self.assertEqual(chat.requests,[])

    def test_rule_operator_rejects_merge(self):
        req=request(n=2,target=1)
        with self.assertRaises(ContractError):sync(RuleOperator().apply(req.snapshot,sync(PartitionPlanner().plan(req,CTX)).plan,operator_context(req.snapshot)))

    def test_native_empty_output_is_explicit_failure(self):
        req=request(n=2,target=1)
        with self.assertRaises(ContractError):sync(TextOperator().apply(req.snapshot,sync(PartitionPlanner().plan(req,CTX)).plan,operator_context(req.snapshot,ScriptedChat(['']))))

    def test_memforest_failure_can_be_strict_or_explicit_legacy_fallback(self):
        req=request(n=2,target=1);plan=replace(sync(PartitionPlanner().plan(req,CTX)).plan,
            actions=(Action(action_id='pair',kind='merge',member_ids=tuple(n.node_id for n in req.snapshot.records),output_ids=('n01',)),))
        with self.assertRaises(ContractError):sync(TextOperator(MemForestPairWriter(attempts=1)).apply(req.snapshot,plan,operator_context(req.snapshot,ScriptedChat([RuntimeError('private')])) ))
        result=sync(TextOperator(MemForestPairWriter(attempts=1,failure_policy='keep_newer')).apply(req.snapshot,plan,operator_context(req.snapshot,ScriptedChat([RuntimeError('private')])) ))
        self.assertEqual(result.outcomes[0].status,'fallback');self.assertEqual(result.outputs[0].text,req.snapshot.records[1].text)


class ContextFolderTests(unittest.TestCase):
    def scenario(self,responses,writer=None):
        req=request(n=1,target=1);action=Action(action_id='rewrite',kind='rewrite',member_ids=('n00',),output_ids=('n00',),input_view='original')
        plan=ActionPlan(plan_id='p',input_fingerprint=req.snapshot.fingerprint,target_ids=('n00',),actions=(action,))
        chat=ScriptedChat(responses);ctx=operator_context(req.snapshot,chat)
        return sync(TextOperator(writer or ContextFolderWriter()).apply(req.snapshot,plan,ctx)),chat,ctx

    def fact(self,importance='high',inferable=False):
        return json.dumps({'facts':[{'fact':'SOURCE_PRIVATE_FACT_X','question':'Which event happened?',
            'answer':'SOURCE_PRIVATE_FACT_X','importance':importance,'inferable':inferable}]})

    def test_blind_answer_never_receives_source_or_reference_answer(self):
        result,chat,_=self.scenario([self.fact(),'compact event','{"answers":["event"]}','{"ok":[true]}'])
        self.assertEqual(result.outcomes[0].status,'success');self.assertEqual(len(chat.requests),4)
        blind=next(r.prompt for r in chat.requests if r.role=='blind_answer')
        self.assertNotIn('SOURCE_PRIVATE_FACT_X',blind);self.assertNotIn('Original memory',blind)
        self.assertEqual(result.outputs[0].extensions['memfolder.writer']['measurement_id'],Words.measurement_id)

    def test_missing_required_fact_triggers_feedback_then_shortest_clean_round(self):
        result,chat,ctx=self.scenario([self.fact(),'lost event','{"answers":[]}','{"ok":[false]}',
            'event','{"answers":["event"]}','{"ok":[true]}'])
        self.assertEqual(result.outputs[0].text,'event');self.assertEqual(len(chat.requests),7)
        self.assertIn('MUST-FIX',chat.requests[4].prompt)
        rounds=[r for r in ctx.diagnostics.records if r.schema=='memfolder.contextfolder.round']
        self.assertEqual([r.data['round'] for r in rounds],[1,2])

    def test_optional_loss_is_allowed_and_triage_threshold_is_preserved(self):
        self.assertEqual(FactTriage().required((Fact('f','q','a','med',False),),.6,CTX),frozenset())
        self.assertEqual(FactTriage().required((Fact('f','q','a','med',False),),.8,CTX),frozenset({0}))
        result,chat,_=self.scenario([self.fact('low'),'event','{"answers":[]}','{"ok":[false]}'])
        self.assertEqual(len(chat.requests),4);self.assertEqual(result.outputs[0].text,'event')

    def test_malformed_fact_json_uses_visible_oneshot_fallback(self):
        result,chat,_=self.scenario(['not JSON','fallback summary'])
        self.assertEqual(result.outcomes[0].status,'fallback');self.assertEqual(result.outcomes[0].reason_code,'no_facts_oneshot')
        self.assertEqual(len(chat.requests),2)

    def test_string_false_is_not_a_positive_verdict(self):
        result,_,_=self.scenario([self.fact(),'event','{"answers":[]}','{"ok":["false"]}'],ContextFolderWriter(max_rounds=1))
        self.assertEqual(result.outputs[0].extensions['memfolder.writer']['required_lost'],1)

    def test_empty_encoding_falls_back_to_source_without_claiming_zero_tokens(self):
        result,_,_=self.scenario([self.fact(),'','{"answers":[]}','{"ok":[false]}'],ContextFolderWriter(max_rounds=1))
        self.assertEqual(result.outcomes[0].reason_code,'empty_encoding_source_fallback')
        self.assertGreater(result.outcomes[0].usage['final_tokens'],0)

    def test_longer_encoding_keeps_actual_source_and_counts_stored_tokens(self):
        result,_,_=self.scenario([self.fact(),'long '+('word '*30),'{}','{"ok":[true]}'],ContextFolderWriter(max_rounds=1))
        self.assertEqual(result.outcomes[0].reason_code,'encoding_not_smaller')
        self.assertEqual(result.outputs[0].text,request(n=1,target=1).snapshot.records[0].text)

    def test_unclean_rounds_rank_weighted_fact_recovery_then_brevity(self):
        facts=(Fact('A','q','a','high',False),Fact('B','q','b','low',False))
        r1=EncodingRound(1,'a',3,(True,False),facts,frozenset({0,1}))
        r2=EncodingRound(2,'b',1,(False,True),facts,frozenset({0,1}))
        self.assertIs(ShortestCleanRound().choose((r1,r2),CTX),r1)

    def test_analysis_diagnostics_are_immutable_and_text_capture_is_opt_in(self):
        result,_,ctx=self.scenario([self.fact(),'event','{}','{"ok":[true]}'])
        fact=next(r for r in ctx.diagnostics.records if r.schema=='memfolder.contextfolder.facts')
        self.assertNotIn('fact',fact.data['facts'][0])
        with self.assertRaises(TypeError):fact.data['required'][0]=7
        with self.assertRaises(AttributeError):fact.component_id='changed'


@unittest.skipUnless(NUMPY,'optional numeric dependencies unavailable')
class PlannerTests(unittest.TestCase):
    def test_record_and_context_share_groups_but_context_rewrites_singletons(self):
        req=request(n=9,target=7)
        a=sync(RecordFolderPlanner().plan(req,CTX)).plan;b=sync(ContextFolderPlanner().plan(req,CTX)).plan
        self.assertEqual([a.member_ids for a in a.actions],[a.member_ids for a in b.actions])
        self.assertTrue(any(a.kind=='rewrite' for a in b.actions));self.assertFalse(any(a.kind=='rewrite' for a in a.actions))

    def test_mainline_requires_entity_features_instead_of_silent_empty_sets(self):
        req=request();req=replace(req,features=(req.features[0],))
        with self.assertRaisesRegex(ContractError,'entities'):sync(RecordFolderPlanner().plan(req,CTX))

    def test_semantic_only_ablation_is_explicit(self):
        req=request();req=replace(req,features=(req.features[0],))
        planner=RecordFolderPlanner(candidates=TemporalCandidates(use_entities=False,temporal_order='order'),scorer=FusedAffinity(mode='no_entity'))
        self.assertEqual(len(sync(planner.plan(req,CTX)).plan.actions),4)

    def test_all_partition_baselines_hit_exact_budget_and_conserve_members(self):
        req=request()
        for planner in [RecordFolderPlanner(),ContextFolderPlanner(),PartitionPlanner(RandomGroups()),
            PartitionPlanner(TomePooledGroups()),PartitionPlanner(AverageLinkageGroups()),PartitionPlanner(KmeansClusters())]:
            with self.subTest(method=type(planner).__name__,component=type(getattr(planner,'partitioner',None)).__name__):
                plan,result,records=apply(req,planner)
                self.assertEqual(len(records),4);self.assertEqual({o for n in records for o in n.origins},{o for n in req.snapshot.records for o in n.origins})

    def test_prune_baselines_keep_exact_count_and_real_nodes(self):
        req=request()
        for selector in [RandomSelector(),DartSelector(),DartSelector(variant='medoid_pivot'),ClusterRepresentatives()]:
            with self.subTest(selector=repr(selector)):
                plan,result,records=apply(req,PrunePlanner(selector))
                self.assertEqual(len(records),4);self.assertTrue(all(n in req.snapshot.records for n in records))

    def test_zero_budget_works_for_prune_and_is_rejected_for_merge(self):
        req=request(target=0)
        self.assertEqual(len(apply(req,PrunePlanner())[2]),0)
        with self.assertRaises(ContractError):sync(RecordFolderPlanner().plan(req,CTX))

    def test_identical_embeddings_kmeans_empty_cluster_repair_preserves_K(self):
        req=request();batch=replace(req.features[0],rows=tuple(replace(r,vector=(1.,0.,0.)) for r in req.features[0].rows))
        req=replace(req,features=(batch,*req.features[1:]))
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            self.assertEqual(len(apply(req,PartitionPlanner(KmeansClusters()))[2]),4)

    def test_protected_nodes_are_retained_and_not_merged(self):
        req=request();nodes=list(req.snapshot.records);nodes[0]=replace(nodes[0],retention=RetentionPolicy(may_drop=False,may_merge=False,may_rewrite=False))
        snapshot=replace(req.snapshot,records=tuple(nodes));features=tuple(replace(b,input_fingerprint=snapshot.fingerprint) for b in req.features)
        req=replace(req,snapshot=snapshot,features=features,budgets=(resolve_budget(snapshot,BudgetRequest(unit='nodes',limit=4)),))
        for planner in [RecordFolderPlanner(),ContextFolderPlanner(),PrunePlanner(DartSelector()),PartitionPlanner(KmeansClusters())]:
            plan,result,records=apply(req,planner);self.assertIn(nodes[0],records)

    def test_seeded_methods_reproduce_and_different_seed_can_change_selection(self):
        req=request(n=30,target=10)
        for selector in [RandomSelector(),DartSelector()]:
            a=sync(PrunePlanner(selector).plan(req,CTX)).plan;b=sync(PrunePlanner(selector).plan(req,CTX)).plan
            self.assertEqual(a,b);self.assertNotEqual(a,sync(PrunePlanner(selector).plan(replace(req,seed=req.seed+1),CTX)).plan)

    def test_streammeco_classifies_media_and_preserves_protected_nodes(self):
        req=request(n=20,target=None,graph=True)
        plan,result,records=apply(req,StreamMeCoPlanner())
        self.assertEqual(len([n for n in records if n.eligible]),14)
        self.assertEqual(len([n for n in records if not n.eligible]),2)
        self.assertTrue(all(a.kind in ('keep','drop') for a in plan.actions))

    def test_streammeco_rejects_incompatible_exact_scope_budget(self):
        with self.assertRaises(ContractError):sync(StreamMeCoPlanner().plan(request(n=20,target=10,graph=True),CTX))

    def test_fine_grained_case_hooks_include_all_mainline_decisions(self):
        sink=DiagnosticCollector();ctx=replace(CTX,diagnostics=sink)
        sync(RecordFolderPlanner().plan(request(n=20,target=5),ctx))
        schemas={r.schema for r in sink.records}
        self.assertTrue({'memfolder.planning.anchors','memfolder.planning.candidates','memfolder.planning.scores',
            'memfolder.planning.gates','memfolder.planning.matching'}<=schemas)

    def test_feature_space_and_snapshot_fingerprints_are_checked(self):
        req=request();stale=replace(req.features[0],input_fingerprint='a'*64)
        with self.assertRaises(ContractError):replace(req,features=(stale,))
        bad=replace(req.features[0],space=replace(req.features[0].space,metric='l2'))
        with self.assertRaises(ContractError):sync(RecordFolderPlanner().plan(replace(req,features=(bad,*req.features[1:])),CTX))


class ConfigurationTests(unittest.TestCase):
    def test_every_baseline_constructs_from_configuration(self):
        for name in ['recordfolder','contextfolder','memforest','memforest-proxy','tome','tome-pooled','dart',
            'streammeco','random-merge','random-prune','kmeans-merge','kmeans-prune']:
            with self.subTest(name=name):
                built=assemble({'planner':{'plugin':name},'operator':{'plugin':'contextfolder-operator'}})
                self.assertEqual(built.engine.planner.spec.role,'planner');self.assertTrue(built.source_manifest)

    def test_nested_module_factory_can_replace_scorer_without_editing_core(self):
        config={'planner':{'plugin':'recordfolder','parameters':{'scorer':{'plugin':'memfolder.method_plugins:build_test_scorer'}}},
                'operator':{'plugin':'recordfolder-operator'}}
        # An application registry can also register a factory from another package.
        registry=default_registry(discover=False)
        def factory(parameters,*,context):return FusedAffinity(mode='no_entity')
        factory.spec=FusedAffinity.spec;registry.register('lab.scorer',factory)
        config['planner']['parameters']['scorer']['plugin']='lab.scorer'
        assembly=assemble(config,registry=registry)
        self.assertEqual(assembly.engine.planner.scorer.mode,'no_entity')

    def test_wrong_role_and_unknown_subcomponent_parameter_fail_at_build(self):
        for params in [{'scorer':{'plugin':'random-selector'}},{'scorer':{'plugin':'fused-affinity','parameters':{'typo':7}}}]:
            with self.assertRaises(ContractError):assemble({'planner':{'plugin':'recordfolder','parameters':params},'operator':{'plugin':'text-operator'}})

    def test_new_baseline_is_an_external_partitioner_configuration(self):
        class Pairs:
            spec=PluginSpec(plugin_id='lab.pairs',role='partitioner')
            def partition(self,req,target,ctx):
                ids=req.extensions['memfolder.planning']['node_ids']
                self_check=len(ids)==target*2
                if not self_check:raise ContractError('pair recipe requires N=2K')
                return tuple(Group(ids[i],tuple(ids[i:i+2])) for i in range(0,len(ids),2))
        def factory(parameters,*,context):return Pairs()
        factory.spec=Pairs.spec;registry=default_registry(discover=False);registry.register('lab.pairs',factory)
        a=assemble({'planner':{'plugin':'partition-planner','parameters':{'partitioner':{'plugin':'lab.pairs'}}},
                    'operator':{'plugin':'text-operator','parameters':{'writer':{'plugin':'concat-writer'}}}},registry=registry)
        output=asyncio.run(a.engine.run(request(n=4,target=2)))
        self.assertEqual(len(output.snapshot.records),2)

    def test_native_snapshot_loader_contract_works_across_benchmark_framework_shapes(self):
        # Real selection/operation, not just constructing predefined shape plans.
        for benchmark in BENCHMARKS:
            for framework in FRAMEWORKS:
                snap=sample(benchmark,framework).memory.initial_snapshot
                req=PlanningRequest(run_id='shapes',snapshot=snap,budgets=(resolve_budget(snap,BudgetRequest(unit='nodes',limit=2)),))
                step=asyncio.run(CompressionEngine(PrunePlanner(),RuleOperator()).step(req))
                self.assertEqual(len(step.result.outputs),2)

    def test_analysis_callback_cannot_replace_decisions(self):
        seen=[];sink=DiagnosticCollector(callbacks=(lambda r:seen.append(r),))
        req=request(n=4,target=2)
        with_sink=asyncio.run(CompressionEngine(PrunePlanner(),RuleOperator()).step(req,diagnostics=sink))
        without=asyncio.run(CompressionEngine(PrunePlanner(),RuleOperator()).step(req))
        self.assertEqual(with_sink.result,without.result);self.assertGreater(len(seen),0)

    def test_dispatch_crosses_merge_and_rewrite_writers_from_config(self):
        config={'planner':{'plugin':'partition-planner','parameters':{'rewrite_singletons':True}},'operator':{'plugin':'operator-dispatch','parameters':{
            'routes':{'keep':{'plugin':'rule-operator'},'drop':{'plugin':'rule-operator'},
                'merge':{'plugin':'text-operator','parameters':{'writer':{'plugin':'concat-writer'}}},
                'rewrite':{'plugin':'text-operator','parameters':{'writer':{'plugin':'concat-writer','parameters':{'separator':' / '}}}}}}}}
        output=asyncio.run(assemble(config).engine.run(request(n=5,target=3)))
        self.assertEqual(len(output.snapshot.records),3)


@unittest.skipUnless(NUMPY,'optional numeric dependencies unavailable')
class ExecutionTests(unittest.TestCase):
    class Encode:
        def __init__(self):self.calls=0
        def encode(self,texts):
            self.calls+=1
            return tuple((1.,float(len(t)%7),float(len(t)%5)) for t in texts)

    def run_repeat(self,planner,req=None):
        req=req or request(n=17,target=3,mode='repeat');space=req.features[0].space
        req=replace(req,features=())
        encoder=self.Encode()
        providers=(SemanticEmbeddingFeatures(space),EventTimeFeatures())
        run=asyncio.run(CompressionEngine(planner,TextOperator(ConcatWriter()),providers).run(req,services=ServiceMap({'embeddings':encoder})))
        return run,encoder

    def test_tome_multiple_rounds_reembed_actual_new_text_and_hit_budget(self):
        run,encoder=self.run_repeat(TomeRoundPlanner())
        self.assertEqual(len(run.snapshot.records),3);self.assertGreater(len(run.steps),1)
        self.assertEqual(encoder.calls,len(run.steps));self.assertEqual(len({o for n in run.snapshot.records for o in n.origins}),17)

    def test_random_disjoint_rounds_hit_budget(self):
        run,_=self.run_repeat(TomeRoundPlanner(random_pairs=True))
        self.assertEqual(len(run.snapshot.records),3)

    def test_memforest_uses_new_text_features_between_mst_rounds(self):
        planner=MemForestPlanner(clusterer=JointClusters(cluster_ratio=.1),router=MstPairRouter())
        run,encoder=self.run_repeat(planner)
        self.assertEqual(len(run.snapshot.records),3);self.assertGreater(len(run.steps),1)
        self.assertEqual(encoder.calls,len(run.steps))

    def test_repeated_round_planners_reject_once_mode(self):
        with self.assertRaises(ContractError):asyncio.run(CompressionEngine(TomeRoundPlanner(),TextOperator(ConcatWriter())).step(request()))

    def test_graph_merge_requires_explicit_framework_projection(self):
        with self.assertRaisesRegex(ContractError,'graph projector'):
            asyncio.run(CompressionEngine(PartitionPlanner(),TextOperator(ConcatWriter())).run(request(graph=True)))

    def test_legacy_ceil_budget_mismatch_is_not_silently_adjusted(self):
        with self.assertRaisesRegex(ContractError,'ceil differs'):
            LegacyClusterCeil(.5).allocate((Group('a',('a','b','c')),Group('d',('d','e','f'))),3,CTX)

    def test_max_rounds_exhaustion_does_not_claim_completed_compression(self):
        req=replace(request(n=17,target=1,mode='repeat'),features=())
        with self.assertRaisesRegex(ContractError,'max_rounds'):
            asyncio.run(CompressionEngine(TomeRoundPlanner(random_pairs=True),TextOperator(ConcatWriter())).run(req,max_rounds=1))

if __name__=='__main__':unittest.main()
