"""Check current source evidence, generated schemas and the built wheel."""
from hashlib import sha256
from pathlib import Path
import json
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import memfolder.core as core
import memfolder.loading as loading
import memfolder.wrappers as wrappers

proof = json.loads((ROOT / 'build/contract_validation.json').read_text(encoding='utf-8'))
current_hashes = {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
    for base in ('src', 'tests', 'examples') for p in sorted((ROOT / base).rglob('*.py'))}
assert proof['status'] == 'passed' and proof['source_sha256'] == current_hashes, 'Stale test evidence'
records = {v.schema_id: v for module in (core, loading, wrappers) for name in module.__all__ if isinstance(v := getattr(module, name), type)
           and issubclass(v, core.Contract) and v is not core.Contract}
for schema_id, cls in records.items():
    schema = json.loads((ROOT / 'schemas' / (schema_id + '.schema.json')).read_text(encoding='utf-8'))
    assert schema == core.json_schema(cls), 'Generated schema differs from implementation'
wheel = next((ROOT / 'build/wheels').glob('memfolder-*.whl'))
files = list((ROOT / 'src').rglob('*.py'))
with zipfile.ZipFile(wheel) as archive:
    assert all(archive.read(p.relative_to(ROOT / 'src').as_posix()) == p.read_bytes() for p in files), 'Stale wheel'
    assert 'memfolder/py.typed' in archive.namelist()
    metadata = archive.read(next(n for n in archive.namelist() if n.endswith('/METADATA'))).decode()
    dependencies = [line for line in metadata.splitlines() if line.startswith('Requires-Dist:')]
    assert all('extra ==' in line for line in dependencies), 'Core must have no mandatory numerical/model dependencies'
    assert archive.read('memfolder/licenses/StreamMeCo-MIT.txt') == (ROOT / 'src/memfolder/licenses/StreamMeCo-MIT.txt').read_bytes()
script = '''
import sys
sys.path.insert(0, sys.argv[1])
import memfolder
from memfolder.core import Snapshot, dumps, loads
snapshot = Snapshot(snapshot_id='wheel', records=())
assert loads(dumps(snapshot)) == snapshot
from memfolder.loading import Importer, Mem0Adapter, SourceDocument
library = Importer(adapter=Mem0Adapter()).load_documents((SourceDocument(
    source_id='wheel', sha256='a'*64, data={'results':[{'id':'original','memory':'fixture','user_id':'user'}]}),))
assert library.report.records_loaded == 1
assert loads(dumps(library)) == library
assert '.whl' in memfolder.__file__
'''
subprocess.run([sys.executable, '-c', script, str(wheel)], check=True, capture_output=True, text=True)
report = {'status': 'passed', 'contract_tests': proof['contract_tests'],
          'memory_loading_tests': proof['memory_loading_tests'], 'tests_skipped': proof['tests_skipped'],
          'python_version': proof['python_version'], 'schemas_match_implementation': len(records),
          'synthetic_shape_scenarios': proof['synthetic_shape_scenarios'],
          'wheel_file': wheel.name, 'wheel_sha256': sha256(wheel.read_bytes()).hexdigest(),
          'packaged_python_sources_match': len(files), 'wheel_import_roundtrip': 'passed',
          'runtime_dependencies': 0, 'optional_dependency_extras': ['algorithms', 'contextfolder', 'qdrant','evaluation'],
          'scientific_algorithm_ports': proof['scientific_algorithms_implemented'],
          'compression_behavior_tests': proof['compression_behavior_tests'],
          'source_characterization_tests': proof['source_characterization_tests'], 'benchmark_runs': 0}
storage = json.loads((ROOT / 'build/storage_validation.json').read_text(encoding='utf-8'))
loading_paths = {key for key in current_hashes if key.startswith(('src/memfolder/core/', 'src/memfolder/loading/'))}
assert storage['status'] == 'passed' and all(storage['source_sha256'].get(k) == current_hashes[k] for k in loading_paths), 'Native storage implementation differs from its SDK evidence'
report.update({'sdk_loading_tests': storage['loading_tests'],
               'real_qdrant_storage_records': storage['real_qdrant_records'], 'user_libraries_tested': 0,
               'original_storage_bytes_unchanged': storage['original_storage_bytes_unchanged'],
               'wheel_memory_import_roundtrip': 'passed'})
user_proof_path = ROOT / 'build/real_loading_validation_v2/user_library_validation.json'
if user_proof_path.exists():
    user_proof = json.loads(user_proof_path.read_text(encoding='utf-8'))
    # The existing real-bank acceptance report verifies native loading. Reuse
    # that evidence only when EVERY tested core/loading runtime file is unchanged.
    # Newly added algorithm modules were not exercised by that older report.
    assert user_proof['status'] == 'passed' and all(user_proof['source_sha256'].get(k) == current_hashes[k] for k in loading_paths), 'Native loading code changed since real-bank acceptance'
    report.update(user_libraries_tested=user_proof['user_libraries_tested'],
                  user_library_records=user_proof['records_loaded'],
                  user_library_edges=user_proof['edges_loaded'],
                  user_library_scope=user_proof['scope'],
                  user_sdk_cross_checks=len(user_proof['sdk_cross_checks']),
                  prior_bank_evidence_scope='unchanged core/loading modules; not new algorithm execution',
                  prior_bank_runtime_files_verified=len(loading_paths))
plugin_proof_path = ROOT / 'build/plugin_validation/installation_validation.json'
if plugin_proof_path.exists():
    plugin_proof = json.loads(plugin_proof_path.read_text(encoding='utf-8'))
    assert plugin_proof['status'] == 'passed' and plugin_proof['source_sha256'] == current_hashes, 'Stale installed-plugin evidence'
    report.update(plugin_tests=proof['plugin_tests'], benchmark_extension_tests=proof['benchmark_extension_tests'],
                  total_tests=proof['tests_run'], installed_benchmark_plugin=plugin_proof['plugin'],
                  installed_plugin_samples=plugin_proof['samples'], plugin_registry_implemented=True,
                  benchmark_plugin_driver_implemented=True, installed_plugin_discovery_and_cli='passed')
method_plugin_path = ROOT / 'build/plugin_validation/method_installation_validation.json'
method_plugin = json.loads(method_plugin_path.read_text(encoding='utf-8'))
runtime_hashes = {k:v for k,v in current_hashes.items() if k.startswith('src/')}
assert method_plugin['status'] == 'passed' and method_plugin['implementation_sha256'] == runtime_hashes
report.update(installed_method_plugin=method_plugin['entrypoint'], installed_method_plugin_parents=method_plugin['parents'])
compression_banks = []
for kind in ('mem0', 'm3'):
    data = json.loads((ROOT / 'build/compression_validation' / (kind + '.json')).read_text(encoding='utf-8'))
    assert data['status'] == 'passed' and data['original_bank_unchanged'] and data['implementation_sha256'] == runtime_hashes
    compression_banks.append({'format':kind, 'records':data['records_loaded'], 'method_configurations':len(data['methods'])})
report.update(real_bank_compression_wiring=compression_banks,
              real_bank_model_calls=0, compression_assembly_implemented=True, diagnostic_collector_implemented=True)
wrapper_banks=[]
for kind in ('mem0','m3'):
    data=json.loads((ROOT/'build/wrapper_validation'/(kind+'.json')).read_text(encoding='utf-8'))
    assert data['status']=='passed' and data['source_unchanged'] and data['implementation_sha256']==runtime_hashes
    wrapper_banks.append({k:data[k] for k in ('format','source_records','final_records','protected_records','edges_after','reader')})
wrapper_plugin=json.loads((ROOT/'build/plugin_validation/wrapper_installation_validation.json').read_text(encoding='utf-8'))
assert wrapper_plugin['status']=='passed' and wrapper_plugin['implementation_sha256']==runtime_hashes
report.update(wrapper_tests=proof['wrapper_tests'],wrapper_assembly_implemented=True,real_bank_native_wrapper_checks=wrapper_banks,
    installed_native_writer=wrapper_plugin['entrypoint'],native_wrapper_model_calls=0,native_wrapper_qa_evaluations=0,
    native_vector_verification_scope='Explicit TEST-ONLY encoder; native search wiring, not model quality',
    memos_live_neo4j_tested=False)
experiment_plugin=json.loads((ROOT/'build/plugin_validation/experiment_installation_validation.json').read_text(encoding='utf-8'))
assert experiment_plugin['status']=='passed' and experiment_plugin['source_sha256']==current_hashes
experiment_banks=[]
for kind in ('mem0','m3'):
    data=json.loads((ROOT/'build/experiment_validation'/(kind+'.json')).read_text(encoding='utf-8'))
    assert data['status']=='passed' and data['source_unchanged'] and data['implementation_sha256']==runtime_hashes
    experiment_banks.append({k:data[k] for k in ('format','source_records','final_records','native_retrieval','events','test_only_answers_and_vectors')})
report.update(experiment_tests=proof['experiment_tests'],experiment_assembly_implemented=proof['experiment_assembly_implemented'],
    reader_evaluator_implemented=proof['reader_evaluator_implemented'],observer_runtime_implemented=proof['observer_runtime_implemented'],
    official_raw_benchmark_families_implemented=4,official_raw_benchmark_variants_implemented=5,
    installed_experiment_plugins=experiment_plugin['plugins'],installed_full_experiment='passed',
    real_bank_full_pipeline_checks=experiment_banks,real_model_qa_runs=0,streaming_executor_implemented=False,
    experiment_validation_scope='Offline once/repeat pipeline, synthetic QA and test-only content vectors; not reproduced benchmark scores')
(ROOT / 'build/delivery_validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report))
