"""Execute a separately installed selector entry point in two parent planners."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--site', type=Path, required=True)
args = parser.parse_args()
script = r'''
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import memfolder
assert Path(memfolder.__file__).is_relative_to(Path(sys.argv[1]))
from memfolder.catalog import default_registry
from memfolder.assembly import assemble
from memfolder.core import *
registry = default_registry()
assert 'example.recency' in registry.references
assert 'recency_plugin' not in sys.modules
scope = ScopeRef(dataset_id='synthetic',sample_id='s',partition_id='p')
snapshot = Snapshot(snapshot_id='installed.selector',records=tuple(MemoryRecord(node_id=f'n{i}',scope=scope,order=i,
    origins=(OriginRef(scope=scope,source_id=f'o{i}'),),parts=(ContentPart(modality='text',text='fixture'),)) for i in range(6)))
config = {'planner':{'plugin':'prune-planner','parameters':{'selector':{'plugin':'example.recency'}}},
          'operator':{'plugin':'rule-operator'}}
assembly = assemble(config,registry=registry)
request = PlanningRequest(run_id='installed',snapshot=snapshot,budgets=(resolve_budget(snapshot,BudgetRequest(unit='nodes',limit=3)),))
run = asyncio.run(assembly.engine.run(request))
assert {n.node_id for n in run.snapshot.records} == {'n3','n4','n5'}
config['planner'] = {'plugin':'recordfolder','parameters':{'anchors':{'plugin':'example.recency'}}}
config['operator'] = {'plugin':'text-operator'}
request = PlanningRequest(run_id='installed.anchors',snapshot=snapshot,budgets=(resolve_budget(snapshot,BudgetRequest(unit='nodes',limit=6)),))
run = asyncio.run(assemble(config,registry=registry).engine.run(request))
assert run.snapshot.records == snapshot.records
assert 'numpy' not in sys.modules and 'qdrant_client' not in sys.modules
import recency_plugin
assert Path(recency_plugin.__file__).is_relative_to(Path(sys.argv[1]))
print(json.dumps({'status':'passed','entrypoint':'example.recency','parents':['prune-planner','recordfolder'],
    'async_selector_executed':True,'core_edits_required':0,'optional_numerical_imports':False,'model_calls':0,'benchmark_evaluations':0}))
'''
result = subprocess.run([sys.executable, '-S', '-X', 'utf8', '-c', script, str(args.site.resolve())],
    check=True, capture_output=True, text=True)
report = json.loads(result.stdout)
report['implementation_sha256'] = {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
    for p in sorted((ROOT / 'src').rglob('*.py'))}
(ROOT / 'build/plugin_validation/method_installation_validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(result.stdout.strip())
