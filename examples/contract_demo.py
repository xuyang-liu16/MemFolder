"""One declared merge and its analysis projection; no named baseline is executed."""
from dataclasses import replace
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from memfolder.core import (Action, ActionOutcome, ActionPlan, ContentPart, MemoryRecord,
    OperatorResult, OriginRef, ScopeRef, Snapshot, dumps, loads, project_snapshot,
    result_records, to_data, validate_projection, validate_result)

scope = ScopeRef(dataset_id='example', sample_id='sample_001', partition_id='conversation')
nodes = tuple(MemoryRecord(node_id=f'n{i}', scope=scope, order=i,
                          origins=(OriginRef(scope=scope, source_id=f'original_{i}'),),
                          parts=(ContentPart(modality='text', text=text),))
              for i, text in enumerate(('Alice likes tea.', 'Alice drinks tea every morning.')))
snapshot = Snapshot(snapshot_id='example.initial', records=nodes)
action = Action(action_id='merge_0', kind='merge', member_ids=('n0', 'n1'), output_ids=('summary_0',))
plan = ActionPlan(plan_id='example.plan', input_fingerprint=snapshot.fingerprint,
                  target_ids=('n0', 'n1'), actions=(action,))
summary = MemoryRecord(node_id='summary_0', scope=scope, order=1,
                       origins=tuple(origin for n in nodes for origin in n.origins),
                       parts=(ContentPart(modality='text', text='Alice likes tea and drinks it every morning.'),))
result = OperatorResult(plan_fingerprint=plan.fingerprint,
                        outcomes=(ActionOutcome(action_id='merge_0', status='success', outputs=(summary,)),))
validate_result(snapshot, plan, result)
projected = replace(snapshot, revision=1, records=result_records(snapshot, plan, result))
validate_projection(snapshot, plan, result, projected)
assert loads(dumps(plan)) == plan
folder = ROOT / 'build' / 'contract_demo'
folder.mkdir(parents=True, exist_ok=True)
for name, value in (('input', snapshot), ('plan', plan), ('result', result), ('projected', projected)):
    (folder / f'{name}.json').write_text(dumps(value, indent=2) + '\n', encoding='utf-8')
(folder / 'observation.json').write_text(json.dumps(to_data(project_snapshot(projected, include_text=True)), indent=2) + '\n', encoding='utf-8')
print(json.dumps({'scope': 'synthetic contract validation, no algorithm/model/benchmark run',
                  'input_nodes': len(snapshot.records), 'output_nodes': len(projected.records),
                  'original_members': len(summary.origins), 'output_embedding': 'absent; refresh provider is a later module'}))
