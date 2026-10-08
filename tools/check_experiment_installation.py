"""Run the installed full architecture with independent contributor wheels."""
from pathlib import Path
from hashlib import sha256
import argparse,json,subprocess,sys,tempfile

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--site',type=Path,required=True);args=parser.parse_args()
script=r'''
import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import memfolder
assert Path(memfolder.__file__).is_relative_to(Path(sys.argv[1]))
from memfolder import assemble_experiment,FileRunReader
from memfolder.core import to_data
from memfolder.experiment import verify_experiment
from memfolder.catalog import default_registry
registry=default_registry()
for name in ('example.newbench','example.recency','example.case-writer','example.fixture-answerer','example.answer-length','example.trace-observer'):
    assert name in registry.references
assert 'experiment_plugin' not in sys.modules
config={'dataset':{'plugin':'example.newbench','parameters':{'path':sys.argv[2]}},
    'compression':{'planner':{'plugin':'prune-planner','parameters':{'selector':{'plugin':'example.recency'}}},
        'operator':{'plugin':'rule-operator'},'wrapper':{'plugin':'memos-wrapper','parameters':{'output_dir':'unused',
            'writer':{'plugin':'example.case-writer','parameters':{'base_writer':{'plugin':'memos-writer'}}}}}},
    'reader':{'plugin':'retrieval-reader','parameters':{'answerer':{'plugin':'example.fixture-answerer'}}},
    'evaluator':{'plugin':'metric-evaluator','parameters':{'metrics':[{'plugin':'example.answer-length'}]}},
    'capture':{'profile':'cases','text_policy':'omit'},'observers':[{'plugin':'example.trace-observer','required':True}],
    'output_dir':sys.argv[3],'run':{'budgets':[{'unit':'nodes','ratio':.5,'minimum':1,'rounding':'ceil'}]}}
result=asyncio.run(assemble_experiment(config,registry=registry).run())
assert len(result.samples)==2 and result.manifest.observation_status=='complete'
assert all(row.evaluation.predictions[0].usage['test_only'] for row in result.samples)
assert all(row.evaluation.metrics[0].name=='answer_characters' for row in result.samples)
assert verify_experiment(sys.argv[3])==result
assert asyncio.run(assemble_experiment(config,registry=registry).run(resume=True))==result
reader=FileRunReader(sys.argv[3])
case=reader.by_question(result.samples[0].sample,result.samples[0].evaluation.predictions[0].question_id)
assert case.status=='complete_for_capture'
reader.export(case,Path(sys.argv[3])/'case_export')
assert 'LABEL_ONLY_ANSWER' not in ''.join(p.read_text(encoding='utf-8') for p in (Path(sys.argv[3])/'trace').rglob('*.json'))
reports=list((Path(sys.argv[3])/'reports').rglob('external-observer.json'))
assert reports and json.loads(reports[0].read_text())['verified_public_artifacts']>0
import experiment_plugin
assert Path(experiment_plugin.__file__).is_relative_to(Path(sys.argv[1]))
assert 'numpy' not in sys.modules and 'qdrant_client' not in sys.modules
print(json.dumps({'status':'passed','plugins':['example.newbench','example.recency','example.case-writer','example.fixture-answerer','example.answer-length','example.trace-observer'],
    'samples':len(result.samples),'full_pipeline':True,'public_case_export':True,'verified_resume':True,'core_edits_required':0,
    'test_only_answers':True,'model_calls':0,'scientific_benchmark_runs':0}))
'''
with tempfile.TemporaryDirectory(prefix='memfolder-installed-experiment-') as folder:
    result=subprocess.run([sys.executable,'-X','utf8','-S','-c',script,str(args.site.resolve()),str((ROOT/'examples/plugins/new_benchmark/tiny-dialogue.json').resolve()),str(Path(folder)/'run')],check=True,capture_output=True,text=True)
report=json.loads(result.stdout)
report['source_sha256']={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for base in ('src','tests','examples') for p in sorted((ROOT/base).rglob('*.py'))}
(ROOT/'build/plugin_validation/experiment_installation_validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(result.stdout.strip())
