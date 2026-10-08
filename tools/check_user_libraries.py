"""Repeatable local acceptance checks; emits counts/hashes, never memory content.

The inventory contains private local paths and is deliberately not bundled.
These checks load real memory banks; they do not run retrieval or QA evaluation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import gc
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--inventory-dir', type=Path, required=True)
parser.add_argument('--sdk-path', type=Path)
parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/real_loading_validation')
parser.add_argument('--resume', action='store_true', help='Recheck source/data hashes and continue an interrupted acceptance run')
args = parser.parse_args()
if args.sdk_path:
    import site
    site.addsitedir(str(args.sdk_path.resolve()))
    sys.path.insert(0, str(args.sdk_path.resolve()))
sys.path.insert(0, str(ROOT / 'src'))

from memfolder.core import ContractError, FrozenMap, dumps, loads
from memfolder.loading import (
    LoadOptions, load_m3, load_mem0_qdrant, load_mem0_sqlite, native_vector_sets,
    read_qdrant_sqlite,
)
from memfolder.loading.m3_pickle import read_m3_pickle


def digest(path):
    value = sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def files(root):
    return {p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


def read_inventory(name):
    return json.loads((args.inventory_dir / name).read_text(encoding='utf-8-sig'))


report = {'status': 'running', 'checked_at': datetime.now(timezone.utc).isoformat(),
          'scope': 'stratified real-bank loading, not full-corpus loading or benchmark evaluation',
          'benchmark_runs': 0, 'cases': [], 'sdk_cross_checks': [],
          'not_available': ['MemOS memory bank', 'PersonaMem memory bank', 'M3 web memory bank']}
args.output_dir.mkdir(parents=True, exist_ok=True)
output = args.output_dir / 'user_library_validation.json'
if args.resume:
    prior = json.loads(output.read_text(encoding='utf-8'))
    assert prior['status'] in ('running','failed'), 'Resume is only for incomplete acceptance runs'
    reference = prior.get('source_sha256')
    if reference is None:
        sdk_reference = json.loads((ROOT/'build/storage_validation.json').read_text(encoding='utf-8'))
        assert sdk_reference['status'] == 'passed'
        reference = sdk_reference['source_sha256']
    runtime_sources = {p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest()
                       for p in sorted((ROOT/'src').rglob('*.py'))}
    assert runtime_sources == {k:v for k,v in reference.items() if k.startswith('src/')}, 'Runtime source changed; start a fresh run'
    for case in prior['cases']:
        if case['status'] == 'passed':
            assert digest(Path(case['path'])) == case['source_sha256'], 'Previously tested bank changed'
    report = prior
    report['status'] = 'running'
    report.setdefault('runtime_notes',[]).append({'action':'resume after interrupted process',
        'python_version':sys.version.split()[0], 'runtime_source_hashes_verified':True,
        'previously_passed_bank_hashes_verified':True})


def save():
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(case, function):
    for old in report['cases']:
        if old['status']=='passed' and (old['benchmark'],old['variant'],old['sample']) == (case['benchmark'],case['variant'],case['sample']):
            return
    report['cases'] = [old for old in report['cases'] if
        (old['benchmark'],old['variant'],old['sample']) != (case['benchmark'],case['variant'],case['sample'])]
    started = time.monotonic()
    try:
        case.update(function())
        case['status'] = 'passed'
    except Exception as error:
        case.update(status='failed', error_type=type(error).__name__,
                    error=str(error) if isinstance(error, ContractError) else 'Validation failed; no source values emitted')
    case['seconds'] = round(time.monotonic() - started, 3)
    case['python_version'] = sys.version.split()[0]
    report['cases'].append(case)
    save()
    print(json.dumps({k: case[k] for k in ('benchmark', 'variant', 'sample', 'status', 'records', 'edges', 'seconds')
                      if k in case}), flush=True)
    gc.collect()


findings = read_inventory('local_memory_store_findings.json')
report['inventory_scope'] = {'nonempty_mem0_databases': findings['nonempty_point_databases'],
                           'variants_and_path_groups': len(findings['groups'])}

# Explicit, inspected LoCoMo roster. No implicit suffix-to-sample behavior in the loader.
roster = [('Caroline_0', 'Melanie_0'), ('Gina_1', 'Jon_1'), ('John_2', 'Maria_2'),
          ('Joanna_3', 'Nate_3'), ('John_4', 'Tim_4'), ('Andrew_5', 'Audrey_5'),
          ('James_6', 'John_6'), ('Deborah_7', 'Jolene_7'), ('Evan_8', 'Sam_8'), ('Calvin_9', 'Dave_9')]
sample_map = {f'user_id:{owner}': f's{i}' for i, pair in enumerate(roster) for owner in pair}
report['locomo_sample_mapping'] = {'basis': 'explicit inspected owner roster', 'samples': 10, 'owners': 20}


def check_sqlite(path, options, *, roundtrip=False, selected=False):
    original_root = path.parents[2]
    before_files, before_hash = files(original_root), digest(path)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as connection:
        expected_count = connection.execute('SELECT count(*) FROM points').fetchone()[0]
    native = read_qdrant_sqlite(path, options=options).data['points']
    library = load_mem0_sqlite(path, options=options)
    assert len(native) == expected_count == library.report.records_loaded
    indexed = {str(row['id']): row for row in native}
    nodes = [node for memory in library.inputs for node in memory.initial_snapshot.records]
    dimensions, owners = Counter(), Counter()
    for node in nodes:
        row = indexed.pop(node.native['id'])
        assert node.text == row['payload']['data']
        assert node.native['record'] == FrozenMap(row)
        assert node.origins[0].source_id == str(row['id']) and node.origins[0].scope == node.scope
        vector = native_vector_sets(node)[0]
        assert vector.slot == 'default' and vector.vectors == (tuple(row['vector']),)
        assert vector.space is None  # dimensions alone never identify an embedding model
        dimensions.update([len(row['vector'])])
        owner = row['payload']['user_id']
        owners.update([owner])
        if options.sample_map:
            assert node.scope.sample_id == options.sample_map['user_id:' + owner]
    assert not indexed and len({n.node_id for n in nodes}) == expected_count
    assert len({n.origins[0] for n in nodes}) == expected_count
    extra = {}
    if roundtrip:
        assert loads(dumps(library)) == library
        extra['canonical_roundtrip'] = 'passed'
    if selected:
        selected_options = LoadOptions(dataset_id='locomo', sample_id='s0',
                                       selectors={'user_id': roster[0]})
        chosen = load_mem0_sqlite(path, options=selected_options)
        assert chosen.report.samples_loaded == 1
        expected_selected = sum(owners[owner] for owner in roster[0])
        assert chosen.report.records_loaded == expected_selected
        assert chosen.report.records_filtered == expected_count - expected_selected
        assert {n.native['record']['payload']['user_id'] for n in chosen.inputs[0].initial_snapshot.records} == set(roster[0])
        extra.update(selected_sample='s0', selected_records=expected_selected,
                     other_sample_records_filtered=chosen.report.records_filtered)
    assert digest(path) == before_hash and files(original_root) == before_files
    return dict(records=expected_count, edges=0, samples=library.report.samples_loaded,
                partitions=len({n.scope.partition_id for n in nodes}),
                vector_dimensions=dict(dimensions), issues=dict(Counter(i.code for i in library.report.issues)),
                source_sha256=before_hash, original_bytes_and_file_inventory_unchanged=True,
                exact_payload_and_vectors='passed', origins_and_sample_boundaries='passed', **extra)


for group in findings['groups']:
    example = Path(group['example_database'])
    samples = ('s000', 's249', 's499') if group['benchmark'] == 'longmemeval' else ('s0',)
    for sample in samples:
        path = Path(re.sub(r'([\\/])s000([\\/])', lambda m: m[1] + sample + m[2], str(example))) if group['benchmark'] == 'longmemeval' else example
        options = LoadOptions(dataset_id=group['benchmark'], sample_id=sample) if group['benchmark'] == 'longmemeval' else LoadOptions(dataset_id='locomo', sample_map=sample_map)
        run({'benchmark': group['benchmark'], 'variant': group['variant'], 'sample': sample, 'path': str(path),
             'metadata_available_elsewhere': bool(group['example_meta']), 'reader': 'mem0-sqlite'},
            lambda p=path, o=options, g=group, s=sample: check_sqlite(p, o,
                roundtrip=g is findings['groups'][0] and s == 's000',
                selected=g is findings['groups'][5] or g is findings['groups'][9]))


if args.sdk_path:
    # Exercise both split layouts using the public SDK reader's metadata overlay.
    for index in (0, 9):
        group = findings['groups'][index]
        if any(c['status']=='passed' and c['variant']==group['variant'] for c in report['sdk_cross_checks']):
            continue
        path, meta = Path(group['example_database']), Path(group['example_meta'])
        before, meta_hash, inventory = digest(path), digest(meta), files(path.parents[2])
        started = time.monotonic()
        native, sdk = None, None
        result = {'benchmark': group['benchmark'], 'variant': group['variant']}
        try:
            sdk = load_mem0_qdrant(path.parents[2], metadata_path=meta, page_size=127)
            native = read_qdrant_sqlite(path, options=LoadOptions()).data['points']
            indexed = {str(r['id']): r for r in native}
            nodes = [n for i in sdk.inputs for n in i.initial_snapshot.records]
            assert len(nodes) == len(native)
            max_delta = 0.0
            for node in nodes:
                row = indexed.pop(node.native['id'])
                assert node.native['record']['payload'] == FrozenMap(row['payload'])
                vector = native_vector_sets(node)[0].vectors[0]
                assert len(vector) == len(row['vector'])
                max_delta = max(max_delta, max(abs(a-b) for a,b in zip(vector, row['vector'])))
            # SDK cosine normalization/float32 conversion may change last bits.
            assert max_delta < 1e-6 and not indexed
            assert before == digest(path) and meta_hash == digest(meta) and inventory == files(path.parents[2])
            result.update(status='passed', records=len(nodes), exact_payload_and_ids='passed',
                          sdk_vector_max_abs_difference_from_stored=max_delta, original_unchanged=True)
        except Exception as error:
            result.update(status='failed', error_type=type(error).__name__)
        result['seconds'] = round(time.monotonic()-started,3)
        report['sdk_cross_checks'].append(result)
        save()
        print('SDK ' + json.dumps(result), flush=True)
        del native, sdk
        gc.collect()


archive_info = read_inventory('local_m3_memory_archive.json')
archive_path = Path(archive_info['archive'])
members = [m for m in archive_info['members'] if m['name'].endswith('.pkl')]
chosen = {m['name']: m for m in sorted(members, key=lambda m: m['bytes'])[:3]}
for member in (max(members, key=lambda m: m['bytes']), next(m for m in members if m['name'] == 'robot50/bedroom_01.pkl')):
    chosen[member['name']] = member
report['m3_archive'] = {'path': str(archive_path), 'graphs_available': len(members), 'graphs_selected': len(chosen),
                      'selection': 'three smallest, largest, and bedroom_01', 'sha256_before': digest(archive_path)}
m3_root = (args.output_dir / 'm3').resolve()
m3_root.mkdir(parents=True, exist_ok=True)
remaining = set(chosen)
with tarfile.open(archive_path, 'r|gz') as archive:
    for member in archive:
        if member.name not in remaining:
            continue
        assert member.isfile() and member.size == chosen[member.name]['bytes']
        target = m3_root / Path(member.name).name
        assert target.resolve().is_relative_to(m3_root)
        with archive.extractfile(member) as stream:
            expected = sha256()
            if target.exists():
                while chunk := stream.read(1024 * 1024):
                    expected.update(chunk)
                assert target.stat().st_size == member.size and digest(target) == expected.hexdigest()
            else:
                with target.open('xb') as dest:
                    shutil.copyfileobj(stream, dest)
        remaining.remove(member.name)
        if not remaining:
            break
assert not remaining


def check_m3(path):
    before = digest(path)
    options = LoadOptions(dataset_id='m3-robot')
    document = read_m3_pickle(path, options=options).data
    lib = load_m3(path, options=options)
    nodes = [n for i in lib.inputs for n in i.initial_snapshot.records]
    edges = [e for i in lib.inputs for e in i.initial_snapshot.edges]
    assert len(nodes) == len(document['nodes']) and len(edges) == len(document['edges'])
    indexed = {str(n['id']): n for n in document['nodes']}
    kinds, dimensions, clocks = Counter(), Counter(), set()
    for node in nodes:
        row = indexed[node.native['id']]
        assert node.native['record'] == FrozenMap(row)
        assert node.origins[0].source_id == str(row['id'])
        if row['type'] in ('episodic', 'semantic'):
            assert tuple(p.text for p in node.parts) == tuple(row['metadata']['contents'])
        elif row['metadata']['contents']:
            assert tuple(p.data['native_content'] for p in node.parts) == tuple(row['metadata']['contents'])
        kinds.update([node.kind])
        for vector in native_vector_sets(node):
            assert vector.vectors == tuple(tuple(v) for v in row['embeddings'])
            dimensions.update(len(v) for v in vector.vectors)
        if row['type'] in ('img', 'voice'):
            assert not node.eligible and not node.retention.may_drop
        else:
            assert node.available_at.value == row['metadata']['timestamp']
            clocks.add(node.available_at.clock)
    native_ids = {n.node_id: n.native['id'] for n in nodes}
    assert [(native_ids[e.source_id], native_ids[e.target_id], e.weight) for e in edges] == [
        (str(e['source']), str(e['target']), e['weight']) for e in document['edges']]
    assert len(lib.inputs) == 1 and digest(path) == before
    return dict(records=len(nodes), edges=len(edges), samples=1, node_kinds=dict(kinds),
                vector_dimensions=dict(dimensions), clip_partitions=len({n.scope.partition_id for n in nodes}),
                visibility_clocks=sorted(clocks), eligible=lib.report.eligible_records,
                issues=dict(Counter(i.code for i in lib.report.issues)), source_sha256=before,
                original_bytes_and_file_inventory_unchanged=True,
                exact_native_nodes_vectors_and_edges='passed', multimodal_protection_and_clip_visibility='passed')


for member in chosen.values():
    path = m3_root / Path(member['name']).name
    run({'benchmark':'m3-robot', 'variant':'robot_keep50', 'sample':path.stem,
         'path':str(path), 'archive_member':member['name'], 'reader':'m3'}, lambda p=path: check_m3(p))
report['m3_archive']['original_unchanged'] = digest(archive_path) == report['m3_archive']['sha256_before']
report['source_sha256'] = {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
    for base in ('src', 'tests', 'examples') for p in sorted((ROOT / base).rglob('*.py'))}
report.update(user_libraries_tested=len(report['cases']),
              records_loaded=sum(c.get('records',0) for c in report['cases']),
              edges_loaded=sum(c.get('edges',0) for c in report['cases']),
              real_bank_variants_and_path_groups=len({c['variant'] for c in report['cases']}),
              failures=sum(c['status'] != 'passed' for c in report['cases'] + report['sdk_cross_checks']))
report['status'] = 'passed' if report['failures'] == 0 and report['m3_archive']['original_unchanged'] else 'failed'
save()
print(json.dumps({k:report[k] for k in ('status','user_libraries_tested','records_loaded','edges_loaded','failures')}, ensure_ascii=False))
raise SystemExit(0 if report['status'] == 'passed' else 1)
