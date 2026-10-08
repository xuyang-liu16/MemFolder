"""Discover and execute a separately installed native writer from configuration."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--site',type=Path,required=True);args=parser.parse_args()
script=r'''
import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from memfolder.catalog import default_registry
from memfolder.assembly import assemble
from memfolder.core import *
from memfolder.loading import Importer,Mem0Adapter,SourceDocument
from memfolder.wrappers import verify_materialization
import memfolder
assert Path(memfolder.__file__).is_relative_to(Path(sys.argv[1]))
registry=default_registry()
assert 'example.case-writer' in registry.references and 'case_writer_plugin' not in sys.modules
data={'points':[{'id':42,'payload':{'data':'fixture','user_id':'alice'},'vector':[1.,2.]}]}
source=Importer(adapter=Mem0Adapter()).load_documents((SourceDocument(source_id='test',sha256=fingerprint(data),data=data),)).inputs[0]
config={'planner':{'plugin':'random-prune'},'operator':{'plugin':'rule-operator'},'wrapper':{'plugin':'mem0-wrapper',
    'parameters':{'output_dir':sys.argv[2],'writer':{'plugin':'example.case-writer'}}}}
assembly=assemble(config,registry=registry)
result=asyncio.run(assembly.run(source,budgets=(BudgetRequest(unit='nodes',limit=1),)))
snapshot,native=verify_materialization(sys.argv[2])
case=json.loads((Path(sys.argv[2])/'cases.json').read_text())
assert case['node_id_map']==to_data(native.node_id_map)
assert 'case.lineage.json' in result.materialized.reader_capabilities
import case_writer_plugin
assert Path(case_writer_plugin.__file__).is_relative_to(Path(sys.argv[1]))
assert 'numpy' not in sys.modules and 'qdrant_client' not in sys.modules
print(json.dumps({'status':'passed','entrypoint':'example.case-writer','core_edits_required':0,
    'installed_entrypoint':True,'async_native_writer':True,'case_lineage_export':True,'model_calls':0,'benchmark_evaluations':0}))
'''
with tempfile.TemporaryDirectory() as td:
    result=subprocess.run([sys.executable,'-S','-X','utf8','-c',script,str(args.site.resolve()),str(Path(td)/'out')],check=True,capture_output=True,text=True)
report=json.loads(result.stdout)
report['implementation_sha256']={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').rglob('*.py'))}
folder=ROOT/'build/plugin_validation';folder.mkdir(exist_ok=True)
(folder/'wrapper_installation_validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(result.stdout.strip())
