"""Real memory banks through the entire architecture, with synthetic QA only."""
from pathlib import Path
from hashlib import sha256
import argparse,ast,asyncio,json,logging,sys

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--input',type=Path,required=True)
parser.add_argument('--format',choices=('mem0','m3'),required=True)
parser.add_argument('--dependency-path',type=Path,action='append',default=[])
parser.add_argument('--output-dir',type=Path,required=True)
args=parser.parse_args()
for directory in args.dependency_path:
    import site
    site.addsitedir(str(directory.resolve()));sys.path.insert(0,str(directory.resolve()))
sys.path.insert(0,str(ROOT/'src'))
from memfolder.core import *
from memfolder.catalog import default_registry
from memfolder.experiment import assemble_experiment,verify_experiment
from memfolder.loading import load_mem0_sqlite,load_m3,LoadOptions
from memfolder.analysis import FileRunReader
from memfolder.wrappers.io import file_digest

SPACE=EmbeddingSpace(provider='acceptance-test-only',model='synthetic-content-vector',revision='1',dimension=3)
class Encoder:
    cache_identity='fixture.content.v1'
    def encode(self,texts):return [(float(len(t)),float(sum(map(ord,t))%101),1.) for t in texts]

async def check():
    before=file_digest(args.input)
    library=load_mem0_sqlite(args.input,options=LoadOptions(dataset_id='fixture.longmemeval',sample_id='s000')) if args.format=='mem0' else load_m3(args.input,options=LoadOptions(dataset_id='fixture.m3'))
    assert len(library.inputs)==1
    memory=library.inputs[0];snapshot=memory.initial_snapshot
    times=[n.available_at for n in snapshot.records if n.available_at is not None]
    as_of=max(times,key=lambda t:t.value) if times else None
    case=EvaluationCase(question_id='fixture-question',sample=memory.sample,question=(ContentPart(modality='text',text='What information is stored about this person?'),),as_of=as_of,
        ground_truth=FrozenMap({'answers':['LABEL_ONLY_ACCEPTANCE_SENTINEL']}))
    item=DatasetSample(memory=memory,evaluation=EvaluationSet(sample=memory.sample,protocol_id='infrastructure.fixture.v1',cases=(case,)))
    class BankDataset:
        spec=PluginSpec(plugin_id='acceptance.bank',role='data_loader')
        source_paths=(args.input,)
        def samples(self):yield item
    def build(parameters,*,context):return BankDataset()
    build.spec=BankDataset.spec
    registry=default_registry();registry.register('acceptance-bank',build)
    writer='qdrant-writer' if args.format=='mem0' else 'm3-json-writer'
    cfg={'dataset':{'plugin':'acceptance-bank'},'compression':{'planner':{'plugin':'random-merge'},
        'operator':{'plugin':'text-operator','parameters':{'writer':{'plugin':'concat-writer'}}},
        'wrapper':{'plugin':args.format+'-wrapper','parameters':{'output_dir':'unused',
            'codec':{'plugin':args.format+'-codec','parameters':{'space':to_data(SPACE)}},'writer':{'plugin':writer},
            'embedding_provider':{'plugin':'content-embeddings','parameters':{'space':to_data(SPACE)}}}}},
        'reader':{'plugin':'retrieval-reader','parameters':{'retriever':{'plugin':('qdrant-retriever' if args.format=='mem0' else 'm3-native-retriever'),'parameters':{'space':to_data(SPACE)}},
            'answerer':{'plugin':'context-echo-answerer'}}},'evaluator':{'plugin':'metric-evaluator'},
        'capture':{'profile':'cases','text_policy':'omit'},'observers':[{'plugin':'event-report-observer','required':True}],
        'output_dir':str(args.output_dir.resolve()),'run':{'seed':7,'evaluate_source':True,'budgets':[{'unit':'nodes','ratio':.5,'minimum':1,'rounding':'ceil'}]}}
    services={'embeddings':Encoder()}
    if args.format=='m3':
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity
        path=ROOT/'build/upstream/m3/mmagent/videograph.py'
        provenance=json.loads((ROOT/'docs/LOADING_SOURCES.json').read_text())['official_sources']['m3']['sources'][0]
        assert file_digest(path)==provenance['sha256']
        cls=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='VideoGraph')
        env={'np':np,'cosine_similarity':cosine_similarity,'logger':logging.getLogger('acceptance')}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),str(path),'exec'),env)
        services['m3.graph_type']=env['VideoGraph']
    result=await assemble_experiment(cfg,registry=registry).run(services=services)
    assert verify_experiment(args.output_dir)==result
    row=result.samples[0];assert row.evaluation and row.baseline_evaluation
    assert all(p.usage['test_only'] for report in (row.evaluation,row.baseline_evaluation) for p in report.predictions)
    assert row.evaluation.predictions[0].retrieval
    final=loads(row.final.resolve(args.output_dir).read_text(encoding='utf-8'))
    assert {o for n in final.records for o in n.origins}=={o for n in snapshot.records for o in n.origins}
    reader=FileRunReader(args.output_dir)
    captured=reader.by_question(memory.sample,'fixture-question',branch='compressed')
    assert captured.status=='complete_for_capture'
    reader.export(captured,args.output_dir/'case_export')
    assert all('LABEL_ONLY_ACCEPTANCE_SENTINEL' not in p.read_text(encoding='utf-8') for p in (args.output_dir/'trace').rglob('*.json'))
    assert file_digest(args.input)==before
    report={'status':'passed','format':args.format,'source_sha256':before,'source_records':len(snapshot.records),'final_records':len(final.records),
        'edges_after':len(final.edges),'source_unchanged':True,'full_pipeline':True,'uncompressed_branch':True,'case_export':True,
        'native_retrieval':'actual Qdrant local query' if args.format=='mem0' else 'pinned official VideoGraph search',
        'events':len(reader.events),'test_only_answers_and_vectors':True,'model_calls':0,'scientific_benchmark_runs':0,
        'implementation_sha256':{p.relative_to(ROOT).as_posix():file_digest(p) for p in sorted((ROOT/'src').rglob('*.py'))}}
    reportdir=ROOT/'build/experiment_validation';reportdir.mkdir(exist_ok=True)
    (reportdir/(args.format+'.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='implementation_sha256'}))

asyncio.run(check())
