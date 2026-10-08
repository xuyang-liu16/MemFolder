"""Read-only real-bank wiring checks, with explicit native feature pooling.

Concat is a test writer, not a text compression result. Full ContextFolder model
behavior is tested separately with synthetic scripted responses. No QA/model
calls, original-bank writes or native backend materialization happen here.
"""
from pathlib import Path
from hashlib import sha256
from dataclasses import replace
import argparse
import asyncio
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--input', type=Path, required=True)
parser.add_argument('--format', choices=('mem0', 'm3'), required=True)
parser.add_argument('--dependency-path', type=Path, action='append', default=[])
parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/compression_validation')
args = parser.parse_args()
for directory in args.dependency_path:
    import site
    site.addsitedir(str(directory.resolve()))
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
from memfolder.core import *
from memfolder.loading import load_mem0_sqlite, load_m3, LoadOptions, native_vector_sets
from memfolder.assembly import assemble
from memfolder.compression import DiagnosticCollector, PruneGraphProjection


def digest(path):
    value = sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def features(snapshot):
    rows = []
    dimensions = set()
    for n in snapshot.records:
        if not n.eligible:
            continue
        sets = [v for v in native_vector_sets(n) if v.vectors]
        if len(sets) != 1:
            raise ContractError('This acceptance check requires one explicit dense native slot')
        vectors = np.asarray(sets[0].vectors, dtype=np.float64)
        dimensions.add(vectors.shape[1])
        rows.append(FeatureRow(node_id=n.node_id, vector=tuple(float(x) for x in vectors.mean(axis=0))))
    if len(dimensions) != 1:
        raise ContractError('This acceptance check rejects mixed eligible vector dimensions')
    space = EmbeddingSpace(provider='local.acceptance', model='unverified-native-mean-pool',
        revision=digest(args.input), dimension=next(iter(dimensions)), metric='cosine')
    return FeatureBatch(name='semantic', input_fingerprint=snapshot.fingerprint,
        space=space, vector_semantics='pooled_feature', rows=tuple(rows))


async def check():
    before = digest(args.input)
    if args.format == 'mem0':
        library = load_mem0_sqlite(args.input, options=LoadOptions(dataset_id='longmemeval', sample_id='s000'))
    else:
        library = load_m3(args.input, options=LoadOptions(dataset_id='m3-robot'))
    report = {'status': 'running', 'data': 'real local memory bank', 'format': args.format,
        'source_sha256': before, 'records_loaded': library.report.records_loaded,
        'eligible_records': library.report.eligible_records, 'samples': len(library.inputs),
        'feature_policy': 'mean of all vectors in the single native dense slot; explicit unverified model; cosine',
        'methods': [], 'model_calls': 0, 'benchmark_evaluations': 0, 'native_materialization': False}
    recipes = ['random-prune', 'dart-random_anchor_farthest', 'dart-medoid_pivot', 'kmeans-prune']
    if args.format == 'mem0':
        recipes += ['recordfolder-semantic-only', 'random-merge', 'kmeans-merge']
    else:
        recipes += ['streammeco-official']
    for memory in library.inputs:
        snapshot = memory.initial_snapshot
        batch = features(snapshot)
        budget = resolve_budget(snapshot, BudgetRequest(unit='nodes', ratio=.5, minimum=1, rounding='ceil'))
        for name in recipes:
            started = time.monotonic()
            config = json.loads((ROOT / 'examples/recipes' / (name + '.json')).read_text(encoding='utf-8'))
            if args.format == 'mem0' and not name.endswith('prune') and not name.startswith('dart'):
                config['operator'] = {'plugin': 'text-operator', 'parameters': {'writer': {'plugin': 'concat-writer'}}}
            assembly = assemble(config)
            diagnostics = DiagnosticCollector()
            req = PlanningRequest(run_id='acceptance.' + name, snapshot=snapshot, features=(batch,), seed=7,
                budgets=() if name == 'streammeco-official' else (budget,))
            run = await assembly.engine.run(req, diagnostics=diagnostics,
                projector=PruneGraphProjection() if snapshot.edges else None)
            planned = run.steps[-1].planning.plan
            before_origins = {o for n in snapshot.records for o in n.origins}
            after_origins = {o for n in run.snapshot.records for o in n.origins}
            merging = any(a.kind == 'merge' for a in planned.actions)
            assert after_origins <= before_origins
            if merging:
                assert after_origins == before_origins
            ineligible = {n.node_id: n for n in snapshot.records if not n.eligible}
            assert all(n == next(x for x in run.snapshot.records if x.node_id == i) for i, n in ineligible.items())
            assert all(e.source_id in {n.node_id for n in run.snapshot.records} and e.target_id in {n.node_id for n in run.snapshot.records}
                for e in run.snapshot.edges)
            report['methods'].append({'recipe': name, 'status': 'passed', 'eligible_before': sum(n.eligible for n in snapshot.records),
                'eligible_after': sum(n.eligible for n in run.snapshot.records), 'edges_before': len(snapshot.edges),
                'edges_after': len(run.snapshot.edges), 'protected_noneligible_unchanged': len(ineligible),
                'writer': 'concat wiring test' if merging else 'keep/drop on real records',
                'diagnostic_events': len(diagnostics.records), 'seconds': round(time.monotonic() - started, 3)})
    report.update(status='passed', original_bank_unchanged=digest(args.input) == before)
    assert report['original_bank_unchanged']
    report['implementation_sha256'] = {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted((ROOT / 'src').rglob('*.py'))}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / (args.format + '.json')).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'implementation_sha256'}))


asyncio.run(check())
