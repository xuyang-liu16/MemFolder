"""Verify real entry-point discovery from separately installed wheels, not mocks."""
from hashlib import sha256
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--site',type=Path,required=True,help='Isolated install directory containing both wheels')
args=parser.parse_args()
site=args.site.resolve()
config=(ROOT/'examples/plugins/new_benchmark/config.json').resolve()
script=r'''
import json,sys
from pathlib import Path
site=Path(sys.argv[1]);sys.path.insert(0,str(site))
import memfolder
assert Path(memfolder.__file__).is_relative_to(site)
from memfolder.catalog import default_registry
from memfolder.benchmarks import load_benchmark_config
from memfolder.core import dumps
registry=default_registry()
assert 'example.newbench' in registry.references
assert 'newbench_plugin' not in sys.modules
stream=load_benchmark_config(sys.argv[2],registry=registry)
samples=list(stream.samples())
assert len(samples)==2
assert sum(len(s.memory.history) for s in samples)==3
assert sum(len(s.evaluation.cases) for s in samples)==2
assert all('LABEL_ONLY_ANSWER' not in dumps(s.memory)+dumps(s.evaluation.reader_input()) for s in samples)
import newbench_plugin
assert Path(newbench_plugin.__file__).is_relative_to(site)
assert 'qdrant_client' not in sys.modules and 'numpy' not in sys.modules
print(json.dumps({'plugin':stream.binding.plugin_id,'samples':2,'history_events':3,'questions':2,
                 'installed_package_imports':True,'lazy_discovery':True,'labels_separated':True}))
'''
first=subprocess.run([sys.executable,'-S','-X','utf8','-c',script,str(site),str(config)],
                     capture_output=True,text=True,check=True)
result=json.loads(first.stdout)
with tempfile.TemporaryDirectory(prefix='memfolder-plugin-install-') as folder:
    output=Path(folder)/'export'
    command=r'''
import sys
sys.path.insert(0,sys.argv[1])
from memfolder.benchmarks.__main__ import main
raise SystemExit(main(['--config',sys.argv[2],'--output-dir',sys.argv[3]]))
'''
    subprocess.run([sys.executable,'-S','-X','utf8','-c',command,str(site),str(config),str(output)],
                   capture_output=True,text=True,check=True)
    assert 'LABEL_ONLY_ANSWER' not in (output/'memory.jsonl').read_text(encoding='utf-8')
    assert 'LABEL_ONLY_ANSWER' in (output/'evaluation.jsonl').read_text(encoding='utf-8')
    assert json.loads((output/'report.json').read_text())['samples']==2
result.update(status='passed',data_kind='synthetic third-party benchmark',benchmark_evaluations=0,
              installed_entrypoint_and_cli='passed',core_edits_required=0)
result['source_sha256']={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest()
    for base in ('src','tests','examples') for p in sorted((ROOT/base).rglob('*.py'))}
(ROOT/'build/plugin_validation').mkdir(exist_ok=True)
(ROOT/'build/plugin_validation/installation_validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='source_sha256'}))
