"""Offline wiring example: synthetic records, random grouping, concatenation.

No models, framework SDKs, NumPy or benchmark questions are used. Concatenation
demonstrates data flow and lineage; it does not establish token compression.
"""
from pathlib import Path
import argparse
import asyncio
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from memfolder.assembly import assemble
from memfolder.compression import DiagnosticCollector
from memfolder.core import (BudgetRequest, ContentPart, MemoryRecord, OriginRef,
    PlanningRequest, ScopeRef, Snapshot, resolve_budget, dumps)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    config = {'planner': {'plugin': 'random-merge'},
              'operator': {'plugin': 'text-operator', 'parameters': {'writer': {'plugin': 'concat-writer'}}}}
    assembly = assemble(config)
    scope = ScopeRef(dataset_id='synthetic', sample_id='demo', partition_id='memory')
    snapshot = Snapshot(snapshot_id='demo', records=tuple(MemoryRecord(
        node_id=f'n{i}', scope=scope, order=i, origins=(OriginRef(scope=scope, source_id=f'original{i}'),),
        parts=(ContentPart(modality='text', text=f'Demo fact {i}.'),)) for i in range(9)))
    request = PlanningRequest(run_id='offline.demo', snapshot=snapshot, seed=7,
        budgets=(resolve_budget(snapshot, BudgetRequest(unit='nodes', limit=4)),))
    diagnostics = DiagnosticCollector()
    run = await assembly.engine.run(request, diagnostics=diagnostics)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        diagnostics.write_jsonl(args.output_dir / 'diagnostics.jsonl')
        with (args.output_dir / 'snapshot.json').open('x', encoding='utf-8') as stream:
            stream.write(dumps(run.snapshot) + '\n')
    print(json.dumps({'data': 'synthetic', 'initial_nodes': len(snapshot.records),
        'final_nodes': len(run.snapshot.records), 'origin_references': sum(len(n.origins) for n in run.snapshot.records),
        'diagnostics': len(diagnostics.records), 'bindings': len(assembly.bindings),
        'config_fingerprint': assembly.config_fingerprint, 'model_calls': 0, 'benchmark_evaluations': 0}))


if __name__ == '__main__':
    asyncio.run(main())
