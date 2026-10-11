"""Functional offline experiments and extension/failure boundaries, never QA results."""
import asyncio
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from memfolder.core import *
from memfolder.catalog import default_registry
from memfolder.plugins import PluginRequest,BuildContext
from memfolder.experiment import assemble_experiment,verify_experiment
from memfolder.analysis import FileRunReader
from memfolder.initialization import HistoryInitializer,SummaryInitializer,BankInitializer
from memfolder.compression import ServiceMap
from memfolder.artifacts import ArtifactStore,PublicArtifacts,FileReportWriter
from memfolder.observation import TraceRecorder,Subscription,RegexRedactor
from memfolder.evaluation import *
from memfolder.evaluation.official import PersonaMemAccuracy
from memfolder.services import CachedService,CompatibleHTTP
from memfolder.benchmarks.raw import LoCoMoLoader,LongMemEvalLoader,PersonaMemLoader
from memfolder.matrix import configurations,run_matrix
from fixtures import sample,SPACE


CTX=AlgorithmContext(services=ServiceMap(),diagnostics=NullDiagnostics())
ROOT=Path(__file__).resolve().parents[1]
def run(value):return asyncio.run(value)
def json_file(root,name,value):
    path=root/name;path.write_text(json.dumps(value),encoding='utf-8');return path
def config(path,output):
    return {'dataset':{'plugin':'dataset-jsonl','parameters':{'path':str(path)}},
        'compression':{'planner':{'plugin':'random-prune'},'operator':{'plugin':'rule-operator'},
            'wrapper':{'plugin':'mem0-wrapper','parameters':{'output_dir':'unused'}}},
        'reader':{'plugin':'retrieval-reader','parameters':{'answerer':{'plugin':'context-echo-answerer'}}},
        'evaluator':{'plugin':'metric-evaluator'},'output_dir':str(output),
        'capture':{'profile':'cases','text_policy':'omit'},'run':{'seed':9,'budgets':[{'unit':'nodes','ratio':.5}]}}
def canonical(root):
    item=sample();item=replace(item,memory=replace(item.memory,initial_snapshot=replace(item.memory.initial_snapshot,
        records=tuple(replace(n,native=FrozenMap()) for n in item.memory.initial_snapshot.records))))
    path=root/'data.jsonl';path.write_text(dumps(item)+'\n',encoding='utf-8');return path,item


class ArtifactTests(unittest.TestCase):
    def test_checksum_and_exclusive_write(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ArtifactStore(Path(folder));ref=store.put('safe.json',FrozenMap({'x':3}))
            self.assertEqual(store.read(ref),{'x':3})
            with self.assertRaises(FileExistsError):store.put('safe.json',{})
            ref.resolve(store.root).write_text('{}')
            self.assertFalse(store.verify(ref))
            with self.assertRaises(ContractError):store.read(ref)
    def test_observer_artifacts_are_allowlisted(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ArtifactStore(Path(folder));private=store.put('private.json',{'secret':'not-public'})
            public=PublicArtifacts(store,set())
            self.assertFalse(public.verify(private))
            with self.assertRaises(ContractError):public.read_json(private)
            with self.assertRaises(ContractError):FileReportWriter(Path(folder)).write_json('../bad.json',FrozenMap())
    def test_nonfinite_and_duplicate_json_rejected(self):
        from memfolder.artifacts import parse_json
        for raw in ('{"x":1,"x":2}','{"x":NaN}'):
            with self.assertRaises(ContractError):parse_json(raw)


class RawBenchmarkTests(unittest.TestCase):
    def test_m3_robot_prefix_applied_before_compression_and_web_full_graph(self):
        from test_loading import m3_document
        from memfolder.benchmarks.m3 import M3BenchmarkLoader
        from memfolder.loading import load_m3
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);graph=json_file(root,'graph.json',m3_document())
            class Loader:
                source_paths=(graph,)
                def load(self):return load_m3(graph)
            annotations=json_file(root,'robot.json',{'v':{'mem_path':'ignored-untrusted-path','qa_list':[
                {'question_id':'q0','question':'who?','answer':'LABEL_ONLY_SECRET','before_clip':0,'reasoning':'LABEL_ONLY_REASON'},
                {'question_id':'q1','question':'drink?','answer':'tea','before_clip':1}]}})
            selected=list(M3BenchmarkLoader(annotations,(('v',Loader()),)).samples())
            self.assertEqual(len(selected),2)
            first=selected[0];self.assertEqual({n.native['id'] for n in first.memory.initial_snapshot.records},{'0','1','2','3'})
            self.assertNotIn('LABEL_ONLY_SECRET',dumps(first.memory));self.assertNotIn('LABEL_ONLY_REASON',dumps(first.memory))
            self.assertEqual(first.evaluation.cases[0].as_of.value,0.)
            annotations=json_file(root,'web.json',{'v':{'qa_list':[{'question_id':'q','question':'who?','answer':'Alice'}]}})
            web=list(M3BenchmarkLoader(annotations,(('v',Loader()),),variant='web').samples())[0]
            self.assertEqual(len(web.memory.initial_snapshot.records),5);self.assertEqual(web.memory.sample.dataset_id,'m3.web')
    def test_m3_missing_cutoff_refuses_full_graph_fallback(self):
        from test_loading import m3_document
        from memfolder.benchmarks.m3 import M3BenchmarkLoader
        from memfolder.loading import load_m3
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);graph=json_file(root,'graph.json',m3_document())
            class Loader:
                def load(self):return load_m3(graph)
            annotations=json_file(root,'qa.json',{'v':{'qa_list':[{'question_id':'q','question':'x','answer':'y','before_clip':99}]}})
            with self.assertRaises(ContractError):list(M3BenchmarkLoader(annotations,(('v',Loader()),)).samples())
    def test_locomo_numeric_session_order_evidence_and_no_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=json_file(root,'locomo.json',[{'sample_id':'s','conversation':{
                'session_10':[{'dia_id':'d10','speaker':'A','text':'last'}],
                'session_2':[{'dia_id':'d2','speaker':'A','text':'first'}],
                'session_2_date_time':'9:00 am on 4 May, 2023'},
                'event_summary':'LABEL_ONLY_SECRET','qa':[{'question':'which?','answer':'LABEL_ONLY_SECRET','category':1,'evidence':['d2']}]}])
            item=list(LoCoMoLoader(path,utc_offset_minutes=0).samples())[0]
            self.assertEqual([e.event_id for e in item.memory.history],['d2','d10'])
            self.assertNotIn('LABEL_ONLY_SECRET',dumps(item.memory));self.assertNotIn('LABEL_ONLY_SECRET',dumps(item.evaluation.reader_input()))
            self.assertEqual(item.evaluation.cases[0].evidence[0].source_id,'d2')
            self.assertEqual(item.memory.history[0].occurred_at.clock,'unix_seconds')
            with self.assertRaises(ContractError):list(LoCoMoLoader(path).samples())
    def test_locomo_bad_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=json_file(Path(folder),'l.json',[{'sample_id':'s','conversation':{'session_1':[{'dia_id':'d','text':'x'}]},'qa':[{'question':'q','answer':'x','category':2,'evidence':['unknown']}]}])
            with self.assertRaises(ContractError):list(LoCoMoLoader(path).samples())
    def test_locomo_unknown_evidence_preserved_without_reader_leak(self):
        with tempfile.TemporaryDirectory() as folder:
            path=json_file(Path(folder),'l.json',[{'sample_id':'s','conversation':{'session_1':[{'dia_id':'d','text':'x'}]},'qa':[{'question':'q','answer':'x','category':2,'evidence':['d','UNKNOWN_EVIDENCE']}]}])
            item=list(LoCoMoLoader(path,evidence_policy='preserve_unknown').samples())[0]
            self.assertEqual([o.source_id for o in item.evaluation.cases[0].evidence],['d'])
            self.assertEqual(item.evaluation.cases[0].ground_truth['unresolved_evidence'],('UNKNOWN_EVIDENCE',))
            self.assertNotIn('UNKNOWN_EVIDENCE',dumps(item.memory))
            self.assertNotIn('UNKNOWN_EVIDENCE',dumps(item.evaluation.reader_input()))
            case=item.evaluation.cases[0]
            prediction=Prediction(sample=case.sample,question_id=case.question_id,
                answer=(ContentPart(modality='text',text='x'),),
                retrieval=(RetrievalHit(node_id='known',rank=1,origins=case.evidence),))
            metric=EvidenceRecall().score(case,prediction,CTX)[0]
            self.assertEqual(metric.status,'not_run');self.assertIsNone(metric.value)
            self.assertEqual(metric.details['reason'],'unresolved_evidence_labels')
            known=replace(case,ground_truth=FrozenMap({'answer':'x','category':2}))
            self.assertEqual(EvidenceRecall().score(known,prediction,CTX)[0].value,1.)
    def test_longmemeval_labels_and_unanswerable_flags_separated(self):
        with tempfile.TemporaryDirectory() as folder:
            path=json_file(Path(folder),'lme.json',[{'question_id':'q_abs','question_type':'multi-session','question':'what?','answer':'LABEL_ONLY_SECRET',
                'question_date':'2023-06-01T00:00:00Z','haystack_session_ids':['s1'],'haystack_dates':['2023-05-01T00:00:00Z'],
                'haystack_sessions':[[{'role':'user','content':'safe history','has_answer':True}]],'answer_session_ids':['s1']}])
            item=list(LongMemEvalLoader(path).samples())[0]
            for text in ('LABEL_ONLY_SECRET','has_answer','answer_session_ids'):self.assertNotIn(text,dumps(item.memory))
            self.assertTrue(item.evaluation.cases[0].ground_truth['abstention'])
            self.assertEqual(item.evaluation.cases[0].evidence[0].source_id,'s1:0')
    def test_longmemeval_parallel_array_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            path=json_file(Path(folder),'lme.json',[{'question_id':'q','haystack_session_ids':['s'],'haystack_dates':[],'haystack_sessions':[]}])
            with self.assertRaises(ContractError):list(LongMemEvalLoader(path).samples())
    def persona(self,root,end='1'):
        context=root/'contexts.jsonl';context.write_text(json.dumps({'shared':[{'role':'user','content':'tea'},{'role':'user','content':'FUTURE_SECRET'}]})+'\n')
        import csv
        path=root/'questions.csv'
        row={'persona_id':'p','question_id':'q','question_type':'preference','user_question_or_message':'drink?','correct_answer':'(a)',
            'all_options':'(a) tea\n(b) coffee','shared_context_id':'shared','end_index_in_shared_context':end,'groundtruth_info':'LABEL_ONLY_SECRET'}
        with path.open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(row));writer.writeheader();writer.writerow(row)
        return PersonaMemLoader(path,context)
    def test_personamem_prefix_before_initialization(self):
        with tempfile.TemporaryDirectory() as folder:
            item=list(self.persona(Path(folder)).samples())[0]
            self.assertEqual(len(item.memory.history),1)
            self.assertNotIn('FUTURE_SECRET',dumps(item.memory));self.assertNotIn('groundtruth_info',dumps(item.memory))
            memory=HistoryInitializer().initialize(item.memory,CTX)
            self.assertNotIn('FUTURE_SECRET',dumps(memory));self.assertEqual(item.evaluation.cases[0].options['A'],'tea')
    def test_personamem_out_of_range_cutoff_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ContractError):list(self.persona(Path(folder),'99').samples())
    def test_personamem_select_no_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(list(replace(self.persona(Path(folder)),sample_ids=('absent',)).samples()),[])


class InitializerTests(unittest.TestCase):
    def test_history_chunks_preserve_origins_speakers_and_temporal_max(self):
        item=sample();source=replace(item.memory,initial_snapshot=None)
        result=HistoryInitializer(events_per_record=2).initialize(source,CTX)
        self.assertEqual(len(result.initial_snapshot.records),2)
        n=result.initial_snapshot.records[0]
        self.assertEqual(len(n.origins),2);self.assertEqual(n.available_at.value,1.)
        self.assertTrue(n.text.startswith('Alice: '))
    def test_existing_bank_is_not_reextracted(self):
        item=sample();self.assertIs(HistoryInitializer().initialize(item.memory,CTX),item.memory)
        self.assertIs(run(SummaryInitializer().initialize(item.memory,CTX)),item.memory)
    def test_initializer_rejects_labels(self):
        with self.assertRaises(ContractError):HistoryInitializer().initialize(sample(),CTX)
    def test_summary_extractor_has_no_labels(self):
        requests=[]
        class Chat:
            def complete(self,request):requests.append(request);return 'condensed fact'
        source=replace(sample().memory,initial_snapshot=None)
        output=run(SummaryInitializer().initialize(source,replace(CTX,services=ServiceMap({'chat':Chat()}))))
        self.assertEqual(len(requests),4);self.assertEqual(output.initial_snapshot.records[0].text,'condensed fact')
        self.assertNotIn('ground_truth',requests[0].prompt)
    def test_bank_initializer_enforces_sample_scope(self):
        item=sample();source=replace(item.memory,initial_snapshot=None)
        class Loader:
            def load(self):return type('Library',(),{'inputs':(item.memory,)})()
        result=run(BankInitializer(((source.sample.sample_id,Loader()),)).initialize(source,CTX))
        self.assertEqual(result.initial_snapshot,item.memory.initial_snapshot)
        bad=replace(source,sample=replace(source.sample,sample_id='other'),history=())
        with self.assertRaises(ContractError):run(BankInitializer((('other',Loader()),)).initialize(bad,CTX))


def view(item):
    return MaterializedView(framework_id='test',snapshot=item.memory.initial_snapshot,
        artifact=ArtifactRef(artifact_id='test',path='manifest.json',sha256='0'*64,media_type='application/json',schema_id='test'),
        node_id_map=FrozenMap({n.node_id:'native:'+n.node_id for n in item.memory.initial_snapshot.records}))


class ReaderMetricTests(unittest.TestCase):
    def test_locomo_category_rules_and_stemming(self):
        try:import nltk
        except ImportError:self.skipTest('optional nltk')
        case=sample().evaluation.cases[0]
        fixtures=[(2,'running','runs',1.),(3,'Alice; additional info','Alice',1.),(1,'Alice, Bob','Bob, Alice',1.),(5,'','not mentioned',1.),(5,'','a fabricated response',0.)]
        for category,gold,predicted,expected in fixtures:
            q=replace(case,ground_truth=FrozenMap({'answer':gold,'category':category}))
            self.assertEqual(LoCoMoF1().score(q,self.prediction(predicted),CTX)[0].value,expected)
    def test_sdk_search_bridge_keeps_native_ids_and_visibility(self):
        from memfolder.evaluation.native import SDKRetriever
        item=sample();v=view(item);q=item.evaluation.reader_input().questions[0]
        class Search:
            def search(self,question,view,allowed,directory):return [{'id':allowed[0],'score':.7}]
        ctx=replace(CTX,services=ServiceMap({'memory_search':Search(),'materialized_root':Path('not-used')}))
        result=run(SDKRetriever().retrieve(q,v,ctx));self.assertEqual(result[0].backend_id,'native:n0')
        self.assertEqual(result[0].origins,item.memory.initial_snapshot.records[0].origins)
    def test_protocol_router_is_configuration_only(self):
        from memfolder.evaluation import ProtocolEvaluator
        item=sample();pred=self.prediction('tea')
        report=run(ProtocolEvaluator(((item.evaluation.protocol_id,MetricEvaluator((ExactMatch(),))),)).evaluate(item.evaluation,(pred,),CTX))
        self.assertEqual(len(report.metrics),1)
        with self.assertRaises(ContractError):run(ProtocolEvaluator(()).evaluate(item.evaluation,(pred,),CTX))
    def prediction(self,text,item=None):
        item=item or sample();case=item.evaluation.cases[0]
        return Prediction(sample=case.sample,question_id=case.question_id,answer=(ContentPart(modality='text',text=text),))
    def test_reader_checks_public_input(self):
        item=sample()
        with self.assertRaises(ContractError):run(RetrievalReader(answerer=ContextAnswerer()).predict(item.evaluation,view(item),CTX))
    def test_visibility_excludes_future(self):
        item=sample();question=replace(item.evaluation.reader_input().questions[0],as_of=TimePoint(value=1,clock='unix_seconds'))
        found=LexicalRetriever().retrieve(question,view(item),CTX)
        self.assertEqual({h.node_id for h in found},{'n0','n1'})
        with self.assertRaises(ContractError):LexicalRetriever().retrieve(replace(question,as_of=None),view(item),CTX)
        self.assertEqual(len(LexicalRetriever(require_as_of=False).retrieve(replace(question,as_of=None),view(item),CTX)),4)
    def test_visibility_expiry_and_clock_fail(self):
        item=sample();v=view(item);n=replace(v.snapshot.records[0],expires_at=TimePoint(value=2,clock='unix_seconds'));v=replace(v,snapshot=replace(v.snapshot,records=(n,*v.snapshot.records[1:])))
        q=item.evaluation.reader_input().questions[0]
        self.assertNotIn('n0',{h.node_id for h in LexicalRetriever().retrieve(q,v,CTX)})
        with self.assertRaises(ContractError):LexicalRetriever().retrieve(replace(q,as_of=TimePoint(value=3,clock='other')),v,CTX)
    def test_dense_and_graph_are_independent(self):
        item=sample();q=item.evaluation.reader_input().questions[0]
        class Encoder:
            def encode(self,texts):return ((1.,0.),)
        found=run(DenseRetriever(SPACE,top_k=1).retrieve(q,view(item),replace(CTX,services=ServiceMap({'embeddings':Encoder()}))))
        self.assertEqual(found[0].node_id,'n0')
        v=view(item);v=replace(v,snapshot=replace(v.snapshot,edges=(GraphEdge(edge_id='e',source_id='n0',target_id='n3',relation='r'),)))
        found=run(GraphExpansion(LexicalRetriever(top_k=1),relations=('r',)).retrieve(q,v,CTX))
        self.assertEqual([h.node_id for h in found],['n0','n3'])
    def test_dense_wrong_dimension_rejected(self):
        class Encoder:
            def encode(self,texts):return ((1.,),)
        item=sample()
        with self.assertRaises(ContractError):run(DenseRetriever(SPACE).retrieve(item.evaluation.reader_input().questions[0],view(item),replace(CTX,services=ServiceMap({'embeddings':Encoder()}))))
    def test_malicious_retriever_rejected(self):
        class Wrong:
            def retrieve(self,question,view,context):return (RetrievalHit(node_id='n0',rank=1,origins=(),backend_id='wrong'),)
        item=sample()
        with self.assertRaises(ContractError):run(RetrievalReader(retriever=Wrong(),answerer=ContextAnswerer()).predict(item.evaluation.reader_input(),view(item),CTX))
    def test_context_budget_and_artifact_provenance(self):
        item=sample()
        with tempfile.TemporaryDirectory() as folder:
            store=ArtifactStore(Path(folder));ctx=replace(CTX,services=ServiceMap({'artifacts':store}))
            pred=run(RetrievalReader(context_builder=ContextBuilder(max_characters=1),answerer=ContextAnswerer()).predict(item.evaluation.reader_input(),view(item),ctx))[0]
            self.assertEqual(pred.retrieval,());self.assertEqual(store.read(pred.reader_context)['node_ids'],[])
    def test_em_f1_evidence_not_run_and_prediction_coverage(self):
        item=sample();case=item.evaluation.cases[0];pred=self.prediction('The tea')
        report=run(MetricEvaluator().evaluate(item.evaluation,(pred,),CTX))
        self.assertEqual([m.value for m in report.metrics[:2]],[1.,1.])
        # Fixture carries evidence; retrieval is empty, therefore recall is zero.
        no_evidence=replace(case,evidence=())
        self.assertEqual(EvidenceRecall().score(no_evidence,pred,CTX)[0].status,'not_run')
        with self.assertRaises(ContractError):run(MetricEvaluator().evaluate(item.evaluation,(),CTX))
    def test_choice_and_official_personamem_parsing_differ_explicitly(self):
        item=sample();case=replace(item.evaluation.cases[0],ground_truth=FrozenMap({'choice':'B'}),options=FrozenMap({'A':'tea','B':'coffee'}))
        pred=self.prediction('Answer (b)')
        self.assertEqual(ChoiceAccuracy().score(case,pred,CTX)[0].value,0.)
        self.assertEqual(PersonaMemAccuracy().score(case,pred,CTX)[0].value,1.)
        self.assertEqual(PersonaMemAccuracy().score(case,self.prediction('(a) or (b)'),CTX)[0].value,0.)
    def test_metric_failure_is_absent_not_zero(self):
        class Bad:
            spec=PluginSpec(plugin_id='custom.bad',role='metric')
            def score(self,*args):raise ValueError('failure')
        report=run(MetricEvaluator(metrics=(Bad(),),strict=False).evaluate(sample().evaluation,(self.prediction('tea'),),CTX))
        self.assertEqual(report.metrics[0].status,'failed');self.assertIsNone(report.metrics[0].value)
        from memfolder.evaluation.evaluator import aggregate
        self.assertIsNone(aggregate((report,))['metrics'][0]['mean'])
    def test_judge_invalid_response_rejected(self):
        class Judge:
            def complete(self,request):return 'maybe'
        with self.assertRaises(ContractError):run(ChatJudge().score(sample().evaluation.cases[0],self.prediction('tea'),replace(CTX,services=ServiceMap({'judge':Judge()}))))
    def test_builtin_catalog_has_one_llm_judge_protocol(self):
        registry=default_registry();context=BuildContext(registry=registry,base_path=ROOT)
        for name in ('chat-judge','memforest-judge'):
            judge=registry.create(PluginRequest(plugin=name),role='metric',context=context).instance
            self.assertEqual(judge.spec.plugin_id,'memfolder.metric.memforest_judge.v1')
        for name in ('official-judge','longmemeval-judge-prompt','m3-judge-prompt'):
            with self.subTest(name=name),self.assertRaises(ContractError):
                registry.create(PluginRequest(plugin=name),role='metric',context=context)


class ExperimentTests(unittest.TestCase):
    def test_offline_raw_history_to_native_memos_experiment(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);raw=json_file(root,'raw.json',[{'sample_id':'s','conversation':{'session_1':[
                {'dia_id':'d1','text':'Alice likes tea.'},{'dia_id':'d2','text':'Alice likes green tea.'}]},
                'qa':[{'question':'What does Alice like?','answer':'tea','category':2,'evidence':['d1']}]}])
            cfg=config(raw,root/'run');cfg['dataset']={'plugin':'locomo-dataset','parameters':{'path':str(raw)}}
            cfg['compression']['wrapper']={'plugin':'memos-wrapper','parameters':{'output_dir':'unused'}}
            result=run(assemble_experiment(cfg).run());self.assertEqual(result.samples[0].statistics.input_nodes,2)
            self.assertTrue(result.aggregate['compressed']['metrics'][0]['test_only'])
            verify_experiment(root/'run')
    def test_cli_runs_and_verifies_configuration_relative_paths(self):
        import subprocess,sys,os
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_=canonical(root);cfg=config(Path('data.jsonl'),Path('run'));config_file=json_file(root,'config.json',cfg)
            env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
            first=subprocess.run([sys.executable,'-X','utf8','-S','-m','memfolder','run',str(config_file)],capture_output=True,text=True,encoding='utf8',env=env)
            self.assertEqual(first.returncode,0,first.stdout+first.stderr)
            second=subprocess.run([sys.executable,'-X','utf8','-S','-m','memfolder','verify',str(root/'run')],capture_output=True,text=True,encoding='utf8',env=env)
            self.assertEqual(second.returncode,0,second.stdout+second.stderr)
    def test_native_m3_pipeline_and_real_class_search(self):
        try:
            import numpy as np
            from sklearn.metrics.pairwise import cosine_similarity
            if not hasattr(np,'array'):raise ImportError
        except ImportError:self.skipTest('optional numpy/sklearn')
        import logging
        from test_wrappers import m3,Encoder,SPACE as space,upstream_class
        env={'np':np,'cosine_similarity':cosine_similarity,'logger':logging.getLogger('experiment-test')}
        graph_type=upstream_class(ROOT/'build/upstream/m3/mmagent/videograph.py','VideoGraph',env)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);memory=m3();times=[n.available_at for n in memory.initial_snapshot.records if n.available_at]
            qa=EvaluationCase(question_id='q',sample=memory.sample,question=(ContentPart(modality='text',text='Alice tea'),),ground_truth=FrozenMap({'answer':'tea'}),as_of=max(times,key=lambda t:t.value))
            item=DatasetSample(memory=memory,evaluation=EvaluationSet(sample=memory.sample,cases=(qa,),protocol_id='test.m3'))
            path=root/'dataset.jsonl';path.write_text(dumps(item)+'\n',encoding='utf8');cfg=config(path,root/'run')
            cfg['compression']['wrapper']={'plugin':'m3-wrapper','parameters':{'output_dir':'unused','embedding_provider':{'plugin':'content-embeddings','parameters':{'space':to_data(space)}}}}
            cfg['reader']['parameters']['retriever']={'plugin':'m3-native-retriever','parameters':{'space':to_data(space)}}
            result=run(assemble_experiment(cfg).run(services={'embeddings':Encoder(),'m3.graph_type':graph_type}))
            self.assertTrue(result.samples[0].evaluation.predictions[0].retrieval);verify_experiment(root/'run')
            self.assertGreater(result.samples[0].usage['services']['embeddings']['calls']['encode'],0)
    def test_native_qdrant_reader_pipeline(self):
        try:import qdrant_client
        except ImportError:self.skipTest('optional Qdrant')
        class Encoder:
            cache_identity='test-only-query-v1'
            def encode(self,texts):return tuple((1.,0.) for _ in texts)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_=canonical(root);cfg=config(path,root/'run')
            cfg['compression']['wrapper']['parameters']['writer']={'plugin':'qdrant-writer'}
            cfg['reader']['parameters']['retriever']={'plugin':'qdrant-retriever','parameters':{'space':to_data(SPACE)}}
            assembly=assemble_experiment(cfg);result=run(assembly.run(services={'embeddings':Encoder()}))
            self.assertTrue(result.samples[0].evaluation.predictions[0].retrieval)
            self.assertEqual(run(assembly.run(services={'embeddings':Encoder()},resume=True)),result)
    def test_prediction_artifact_references_are_run_root_relative(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_=canonical(root);result=run(assemble_experiment(config(path,root/'run')).run())
            ref=result.samples[0].evaluation.predictions[0].reader_context
            self.assertTrue(ArtifactStore(root/'run').verify(ref))
    def test_failure_can_be_queried_by_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,item=canonical(root);cfg=config(path,root/'run');cfg['reader']={'plugin':'retrieval-reader'}
            with self.assertRaises(ContractError):run(assemble_experiment(cfg).run())
            reader=FileRunReader(root/'run');self.assertTrue(reader.by_origin(item.memory.initial_snapshot.records[0].origins[0]).events)
    def test_entire_pipeline_resume_and_case_queries(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,item=canonical(root);cfg=config(path,root/'run');cfg['observers']=[{'plugin':'event-report-observer'}]
            assembly=assemble_experiment(cfg);result=run(assembly.run())
            self.assertEqual(result.manifest.compression_status,'completed');self.assertEqual(result.manifest.evaluation_status,'completed')
            self.assertEqual(result.samples[0].statistics.output_nodes,2);self.assertEqual(loads(dumps(result)),result)
            self.assertEqual(run(assembly.run(resume=True)),result)
            self.assertEqual(verify_experiment(root/'run'),result)
            reader=FileRunReader(root/'run');origin=item.memory.initial_snapshot.records[0].origins[0]
            self.assertEqual(reader.by_origin(origin).status,'complete_for_capture')
            qcase=reader.by_question(item.memory.sample,item.evaluation.cases[0].question_id)
            self.assertTrue(qcase.events)
            action=next(e.action_id for e in reader.events if e.action_id)
            self.assertTrue(reader.by_action(item.memory.sample,action).origins)
            self.assertEqual(reader.compare(reader,(origin,)).alignment,'matched')
            exported=reader.export(qcase,root/'case');self.assertTrue(exported.is_file())
            self.assertTrue((root/'run/reports/0/events.json').is_file())
    def test_native_memos_pipeline(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_=canonical(root);cfg=config(path,root/'run');cfg['compression']['wrapper']={'plugin':'memos-wrapper','parameters':{'output_dir':'unused'}}
            result=run(assemble_experiment(cfg).run());self.assertEqual(result.samples[0].statistics.output_nodes,2)
            directory=result.samples[0].materialized.resolve(root/'run').parent
            from memfolder.wrappers import verify_materialization
            _,native=verify_materialization(directory);self.assertEqual(native.framework_id,'memos')
    def test_compression_only_has_no_quality_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_=canonical(root);cfg=config(path,root/'run');cfg.pop('reader');cfg.pop('evaluator');cfg['capture']={'profile':'off'}
            result=run(assemble_experiment(cfg).run())
            self.assertEqual(result.manifest.evaluation_status,'not_run');self.assertIsNone(result.samples[0].evaluation)
            self.assertFalse((root/'run/trace').exists());self.assertEqual(result.aggregate['compressed']['metrics'],())
    def test_evaluate_source_has_separate_context_and_branches(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,item=canonical(root);cfg=config(path,root/'run');cfg['run']['evaluate_source']=True
            result=run(assemble_experiment(cfg).run())
            self.assertIsNotNone(result.samples[0].baseline_evaluation)
            reader=FileRunReader(root/'run');qid=item.evaluation.cases[0].question_id
            self.assertTrue(reader.by_question(item.memory.sample,qid,branch='uncompressed').events)
            self.assertTrue(reader.by_question(item.memory.sample,qid,branch='compressed').events)
            verify_experiment(root/'run')
    def test_resume_rejects_changed_input_and_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_=canonical(root);cfg=config(path,root/'run');assembly=assemble_experiment(cfg);run(assembly.run())
            changed={**cfg,'run':{**cfg['run'],'seed':10}}
            with self.assertRaises(ContractError):run(assemble_experiment(changed).run(resume=True))
            path.write_text(path.read_text()+'\n',encoding='utf-8')
            with self.assertRaises(ContractError):run(assembly.run(resume=True))
    def test_resume_rejects_changed_trace_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_=canonical(root);cfg=config(path,root/'run');run(assemble_experiment(cfg).run())
            artifact=next((root/'run/trace/artifacts').glob('*.json'));artifact.write_text('{}')
            with self.assertRaises(ContractError):verify_experiment(root/'run')
            self.assertFalse(FileRunReader(root/'run').coverage.complete_for_capture)
    def test_required_reader_evaluator_and_capture_redactor_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_=canonical(root);cfg=config(path,root/'run');cfg.pop('evaluator')
            with self.assertRaises(ContractError):assemble_experiment(cfg)
            cfg=config(path,root/'run');cfg['capture']={'profile':'full','text_policy':'redacted'}
            with self.assertRaises(ContractError):assemble_experiment(cfg)
    def test_no_gold_in_trace_or_reader_context(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,item=canonical(root);item=replace(item,evaluation=replace(item.evaluation,cases=(replace(item.evaluation.cases[0],ground_truth=FrozenMap({'answer':'LABEL_ONLY_SECRET'})),)))
            path.write_text(dumps(item)+'\n',encoding='utf-8');cfg=config(path,root/'run');cfg['capture']={'profile':'full','text_policy':'full'}
            run(assemble_experiment(cfg).run())
            for file in (root/'run/trace').rglob('*'):
                if file.is_file():self.assertNotIn('LABEL_ONLY_SECRET',file.read_text(encoding='utf-8'))
            for file in (root/'run/samples').rglob('reader/*.json'):self.assertNotIn('LABEL_ONLY_SECRET',file.read_text(encoding='utf-8'))
    def test_failure_manifest_and_no_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_=canonical(root);cfg=config(path,root/'run');cfg['reader']={'plugin':'retrieval-reader'}
            with self.assertRaises(ContractError):run(assemble_experiment(cfg).run())
            manifest=loads((root/'run/run.manifest.json').read_text(encoding='utf8'))
            self.assertEqual(manifest.compression_status,'failed');self.assertFalse((root/'run/completion.json').exists())
    def test_async_dataset_extension_without_driver_edits(self):
        item=sample();item=replace(item,memory=replace(item.memory,initial_snapshot=replace(item.memory.initial_snapshot,records=tuple(replace(n,native=FrozenMap()) for n in item.memory.initial_snapshot.records))))
        class Loader:
            spec=PluginSpec(plugin_id='custom.async_dataset',role='data_loader')
            async def samples(self):yield item
        def build(parameters,*,context):return Loader()
        build.spec=Loader.spec
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_=canonical(root);cfg=config(path,root/'run');cfg['dataset']={'plugin':'async-test'}
            registry=default_registry(discover=False);registry.register('async-test',build)
            result=run(assemble_experiment(cfg,registry=registry).run());self.assertEqual(len(result.samples),1)
    def test_multi_sample_outputs_are_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,item=canonical(root);other=sample('longmemeval');other=replace(other,memory=replace(other.memory,initial_snapshot=replace(other.memory.initial_snapshot,records=tuple(replace(n,native=FrozenMap()) for n in other.memory.initial_snapshot.records))));path.write_text(dumps(item)+'\n'+dumps(other)+'\n',encoding='utf-8')
            result=run(assemble_experiment(config(path,root/'run')).run());self.assertEqual(len(result.samples),2)
            self.assertNotEqual(result.samples[0].materialized.path,result.samples[1].materialized.path)
            verify_experiment(root/'run')
    def test_matrix_seeds_bound_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,_=canonical(root);cfg=config(path,root/'unused')
            matrix=run(run_matrix(cfg,root/'matrix',seeds=(1,2)))
            self.assertEqual(matrix['count'],2);self.assertEqual(run(run_matrix(cfg,root/'matrix',seeds=(1,2),resume=True)),matrix)
            with self.assertRaises(ContractError):list(configurations(cfg,seeds=(1,2),max_runs=1))
            with self.assertRaises(ContractError):list(configurations(cfg,axes=({'path':'run.no_such_field','values':[1]},)))


class MainlineExperimentTests(unittest.TestCase):
    def test_recordfolder_and_contextfolder_complete_experiment(self):
        from test_compression import request,Words
        req=request(n=6,target=3)
        ref=SampleRef(dataset_id='test',sample_id='s',split='fixture',dataset_fingerprint='a'*64)
        question=EvaluationCase(question_id='q',sample=ref,question=(ContentPart(modality='text',text='What details?'),),ground_truth=FrozenMap({'answers':['details']}))
        item=DatasetSample(memory=MemoryInput(sample=ref,initial_snapshot=req.snapshot),evaluation=EvaluationSet(sample=ref,protocol_id='mainline.fixture',cases=(question,)))
        class Chat:
            cache_identity='scripted-mainline-fixture'
            def complete(self,request):
                return {'fact_extract':'{"facts":[{"fact":"details","question":"what?","answer":"details","importance":"high","inferable":false}]}',
                    'compile':'compact details','blind_answer':'{"answers":["details"]}','fact_judge':'{"ok":[true]}'} .get(request.role,'compact details')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'dataset.jsonl';path.write_text(dumps(item)+'\n',encoding='utf-8')
            for method in ('recordfolder','contextfolder'):
                cfg=config(path,root/method);cfg['compression']={'planner':{'plugin':method,'parameters':{'candidates':{'plugin':'temporal-candidates','parameters':{'temporal_feature':'temporal'}}}},'operator':{'plugin':method+'-operator'},
                    'features':[{'plugin':'stored-embeddings','parameters':{'space':to_data(req.features[0].space)}},
                        {'plugin':'event-time-features'},{'plugin':'grounding-features','parameters':{'grounding':{'nodes':[{'node_id':n.node_id,'entities':[{'key':'alice','canonical':'Alice'}]} for n in req.snapshot.records]},'require_time':False}}],
                    'wrapper':{'plugin':'memos-wrapper','parameters':{'output_dir':'unused'}}}
                result=run(assemble_experiment(cfg).run(services={'chat':Chat(),'tokenizer':Words()}))
                self.assertEqual(result.samples[0].statistics.output_eligible,3)
                final=loads(result.samples[0].final.resolve(root/method).read_text(encoding='utf-8'))
                self.assertEqual({o for n in final.records for o in n.origins},{o for n in req.snapshot.records for o in n.origins})
                self.assertGreater(result.samples[0].usage['services']['chat']['calls']['complete'],0)
                self.assertTrue(result.samples[0].evaluation.predictions[0].usage['test_only'])
                events=FileRunReader(root/method).events
                starts={e.span_id:e for e in events if e.phase=='started'}
                self.assertTrue(any(e.parent_span_id is not None for e in events))
                self.assertTrue(all(e.span_id in starts for e in events if e.phase=='completed' and e.stage in ('plan','apply')))
    def test_online_grounding_aliases_and_time_from_memory_only(self):
        from memfolder.planning.grounding import ChatGroundingFeatures
        from test_compression import request
        snapshot=request(n=2,target=1).snapshot
        class Chat:
            def complete(self,req):
                self.assert_text=req.prompt;return '{"entities":["ALICE","Ali"]}'
        chat=Chat();ctx=replace(CTX,services=ServiceMap({'grounding':chat}))
        features=run(ChatGroundingFeatures(aliases=FrozenMap({'ali':'alice'}),require_time=True).extract(snapshot,ctx))
        self.assertEqual(features.rows[0].values['entities'],('alice',));self.assertEqual(features.rows[1].values['event_time'],1.)
        self.assertNotIn('QUESTION',chat.assert_text)
    def test_contextfolder_reader_prompt_is_shared_and_public(self):
        from memfolder.evaluation.prompts import ContextFolderPrompt,QAPrompt
        question=sample().evaluation.reader_input().questions[0]
        prompt=ContextFolderPrompt().build(question,ReaderContext(text='@2023-01-01 Alice -> tea',parts=(),node_ids=()))
        self.assertEqual(prompt,QAPrompt().build(question,ReaderContext(text='@2023-01-01 Alice -> tea',parts=(),node_ids=())))
        self.assertNotIn('DECODE LEGEND',prompt)
        self.assertNotIn('ground_truth',prompt)
    def test_composite_datasets_and_protocol_routing_without_runner_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);one,item=canonical(root);two=root/'second.jsonl'
            other=replace(sample('longmemeval'),memory=replace(sample('longmemeval').memory,initial_snapshot=replace(sample('longmemeval').memory.initial_snapshot,records=tuple(replace(n,native=FrozenMap()) for n in sample('longmemeval').memory.initial_snapshot.records))))
            two.write_text(dumps(other)+'\n',encoding='utf-8');cfg=config(one,root/'run')
            cfg['dataset']={'plugin':'composite-dataset','parameters':{'loaders':[cfg['dataset'],{'plugin':'dataset-jsonl','parameters':{'path':str(two)}}]}}
            cfg['evaluator']={'plugin':'protocol-evaluator','parameters':{'routes':{item.evaluation.protocol_id:{'plugin':'metric-evaluator','parameters':{'metrics':[{'plugin':'exact-match'}]}},other.evaluation.protocol_id:{'plugin':'metric-evaluator','parameters':{'metrics':[{'plugin':'token-f1'}]}}}}}
            result=run(assemble_experiment(cfg).run());self.assertEqual(len(result.samples),2)
            self.assertEqual({m.name for r in result.samples for m in r.evaluation.metrics},{'exact_match','token_f1'})


class ObservationTests(unittest.TestCase):
    def test_optional_and_required_observer_failures(self):
        class Bad:
            def open(self,context):self.context=context
            def on_event(self,event,context):raise RuntimeError('observer-error')
            def close(self,context):pass
        async def exercise(root,required):
            observer=Bad();trace=TraceRecorder(root,'r',capture=CapturePolicy(profile='summary'),subscriptions=(Subscription(observer,required),))
            await trace.open();trace.event('test','completed')
            if required:
                with self.assertRaises(RuntimeError):await trace.flush()
            else:await trace.flush()
            await trace.close();self.assertFalse(trace.coverage.complete_for_capture)
            self.assertFalse(hasattr(observer.context,'services'));self.assertFalse(hasattr(observer.context,'pipeline'))
        with tempfile.TemporaryDirectory() as folder:
            run(exercise(Path(folder)/'optional',False));run(exercise(Path(folder)/'required',True))
    def test_redacted_text_and_scope_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,item=canonical(root);cfg=config(path,root/'run');scope=item.memory.initial_snapshot.records[0].scope
            cfg['capture']={'profile':'full','text_policy':'redacted','scopes':[to_data(scope)]}
            cfg['redactor']={'plugin':'regex-redactor','parameters':{'patterns':['Alice']}}
            run(assemble_experiment(cfg).run())
            for file in (root/'run/trace/artifacts').glob('*.json'):self.assertNotIn('Alice',file.read_text(encoding='utf-8'))
    def test_uncaptured_sample_is_not_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,item=canonical(root);cfg=config(path,root/'run');cfg['capture']['sample_ids']=['different']
            run(assemble_experiment(cfg).run());reader=FileRunReader(root/'run')
            self.assertEqual(reader.by_origin(item.memory.initial_snapshot.records[0].origins[0]).status,'not_recorded')


class ServiceTests(unittest.TestCase):
    def test_cached_chat_and_embedding_requests_reuse_content(self):
        class Provider:
            calls=0;embeds=0;cache_identity='test-model-v1'
            def complete(self,request):self.calls+=1;return 'test response'
            def encode(self,texts):self.embeds+=1;return tuple((float(len(t)),1.) for t in texts)
        from memfolder.operators.types import ChatRequest
        async def exercise(path):
            provider=Provider();service=CachedService(provider,path,'test')
            req=ChatRequest(role='test',prompt='input');self.assertEqual(await service.complete(req),await service.complete(req));self.assertEqual(provider.calls,1)
            first=await service.encode(('one','two'));second=await service.encode(('two','one'))
            self.assertEqual(first,tuple(reversed(second)));self.assertEqual(provider.embeds,1)
            await service.complete(replace(req,temperature=.5));self.assertEqual(provider.calls,2)
        with tempfile.TemporaryDirectory() as folder:run(exercise(Path(folder)/'cache.sqlite'))
    def test_http_provider_missing_env_and_invalid_url(self):
        with self.assertRaises(ContractError):CompatibleHTTP('https://user:secret@example.com','model')
        service=CompatibleHTTP('https://example.invalid/v1','model',api_key_env='MEMFOLDER_TEST_MISSING_KEY')
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(ContractError):service._post('chat/completions',{})
    def test_provider_embedding_reorders_indices(self):
        service=CompatibleHTTP('https://example.invalid/v1','model')
        with patch.object(CompatibleHTTP,'_post',return_value={'data':[{'index':1,'embedding':[0.,1.]},{'index':0,'embedding':[1.,0.]}]}):
            self.assertEqual(run(service.encode(('a','b'))),((1.,0.),(0.,1.)))


if __name__=='__main__':unittest.main()
