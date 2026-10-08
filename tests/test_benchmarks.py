"""A new benchmark outside src plugs into the same stream and CLI."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from memfolder.benchmarks import load_benchmark, load_benchmark_config
from memfolder.catalog import default_registry
from memfolder.core import ContractError, DatasetSample, dumps, loads
from memfolder.plugins import BuildContext, PluginRequest

ROOT=Path(__file__).resolve().parents[1]
EXAMPLE=ROOT/'examples/plugins/new_benchmark'


class BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(EXAMPLE))
    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(EXAMPLE))

    def request(self):
        return PluginRequest(plugin='newbench_plugin:build',parameters={'path':'tiny-dialogue.json'})

    def stream(self,**kwargs):
        return load_benchmark(self.request(),registry=default_registry(discover=False),
                              context=BuildContext(base_path=EXAMPLE),**kwargs)

    def test_external_benchmark_needs_no_core_or_driver_edit(self):
        before={str(p):sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src').rglob('*.py')}
        samples=list(self.stream().samples())
        self.assertEqual(len(samples),2)
        self.assertEqual([s.memory.sample.sample_id for s in samples],['conversation-a','conversation-b'])
        self.assertEqual(samples[0].memory.history[0].event_id,samples[1].memory.history[0].event_id)
        self.assertNotEqual(samples[0].memory.history[0].scope,samples[1].memory.history[0].scope)
        self.assertIsNone(samples[0].memory.initial_snapshot)
        self.assertEqual(loads(dumps(samples[0])),samples[0])
        self.assertEqual(before,{str(p):sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src').rglob('*.py')})

    def test_memory_observer_and_reader_questions_do_not_receive_labels(self):
        class Observer:
            def __init__(self):
                self.memories=[];self.reports=[]
            def on_memory(self,memory):
                self.memories.append(memory)
            def on_report(self,report):
                self.reports.append(report)
        observer=Observer()
        samples=list(self.stream(observer=observer).samples())
        self.assertEqual(len(observer.memories),2)
        report=observer.reports[0]
        self.assertEqual((report.samples,report.history_events,report.memory_records,report.questions),(2,3,0,2))
        for sample in samples:
            self.assertNotIn('LABEL_ONLY_ANSWER',dumps(sample.memory))
            self.assertNotIn('LABEL_ONLY_ANSWER',dumps(sample.evaluation.reader_input()))
            self.assertIn('LABEL_ONLY_ANSWER',dumps(sample.evaluation))
        self.assertNotIn('LABEL_ONLY_ANSWER',json.dumps(report.to_dict()))
        with self.assertRaises(AttributeError):
            observer.memories[0].sample_id='mutated'

    def test_canonical_jsonl_reuses_benchmark_contracts_without_a_format_adapter(self):
        original=list(self.stream().samples())
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'dataset.jsonl'
            path.write_text('\n'.join(dumps(s) for s in original)+'\n',encoding='utf-8')
            config=root/'config.json'
            config.write_text(json.dumps({'plugin':'dataset-jsonl','parameters':{'path':'dataset.jsonl'}}))
            actual=list(load_benchmark_config(config,registry=default_registry(discover=False)).samples())
            self.assertEqual(actual,original)

    def test_duplicate_samples_and_wrong_yield_type_fail(self):
        original=list(self.stream().samples())[0]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'dataset.jsonl'
            path.write_text(dumps(original)+'\n'+dumps(original)+'\n',encoding='utf-8')
            stream=load_benchmark(PluginRequest(plugin='dataset-jsonl',parameters={'path':str(path)}),
                                  registry=default_registry(discover=False))
            with self.assertRaisesRegex(ContractError,'Duplicate benchmark sample'):
                list(stream.samples())
        from newbench_plugin import build,SPEC
        class BadLoader:
            spec=SPEC
            def samples(self):
                return iter([original.memory])
        def bad(parameters,*,context):return BadLoader()
        bad.spec=SPEC
        registry=default_registry(discover=False);registry.register('bad',bad)
        with self.assertRaisesRegex(ContractError,'yield DatasetSample'):
            list(load_benchmark(PluginRequest(plugin='bad'),registry=registry).samples())

    def test_empty_and_truncated_or_invalid_canonical_files_are_not_success(self):
        original=list(self.stream().samples())
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'dataset.jsonl';registry=default_registry(discover=False)
            path.write_text('')
            request=PluginRequest(plugin='dataset-jsonl',parameters={'path':str(path)})
            with self.assertRaisesRegex(ContractError,'no samples'):
                list(load_benchmark(request,registry=registry).samples())
            self.assertEqual(list(load_benchmark(request,registry=registry,allow_empty=True).samples()),[])
            path.write_text(dumps(original[0])+'\n'+'{"invalid":"PRIVATE_SOURCE"}')
            with self.assertRaises(ContractError) as error:
                list(load_benchmark(request,registry=registry).samples())
            self.assertNotIn('PRIVATE_SOURCE',str(error.exception))
            path.write_text('\n'.join(dumps(s) for s in original))
            request=PluginRequest(plugin='dataset-jsonl',parameters={'path':str(path),'max_samples':1})
            with self.assertRaisesRegex(ContractError,'sample limit'):
                list(load_benchmark(request,registry=registry).samples())

    def test_early_stop_and_observer_failure_close_source_without_completion_report(self):
        from newbench_plugin import SPEC
        original=list(self.stream().samples())[0]
        closed=[];reports=[]
        class Loader:
            spec=SPEC
            def samples(self):
                try:
                    yield original
                    yield original
                finally:
                    closed.append(True)
        def build(parameters,*,context):return Loader()
        build.spec=SPEC
        registry=default_registry(discover=False);registry.register('closable',build)
        class Observer:
            def on_memory(self,memory):pass
            def on_report(self,report):reports.append(report)
        stream=load_benchmark(PluginRequest(plugin='closable'),registry=registry,observer=Observer())
        iterator=stream.samples();next(iterator);iterator.close()
        self.assertEqual(closed,[True]);self.assertEqual(reports,[])
        class BrokenObserver(Observer):
            def on_memory(self,memory):raise RuntimeError('analysis failed')
        stream=load_benchmark(PluginRequest(plugin='closable'),registry=registry,observer=BrokenObserver())
        with self.assertRaises(RuntimeError):list(stream.samples())
        self.assertEqual(len(closed),2);self.assertEqual(reports,[])

    def test_benchmark_cli_exports_separate_labels_and_bad_stream_leaves_no_output(self):
        env={**os.environ,'PYTHONPATH':os.pathsep.join([str(ROOT/'src'),str(EXAMPLE)])}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config=root/'config.json';output=root/'export'
            config.write_text(json.dumps({'plugin':'newbench_plugin:build','parameters':{'path':str(EXAMPLE/'tiny-dialogue.json')}}))
            command=[sys.executable,'-m','memfolder.benchmarks','--config',str(config),'--output-dir',str(output)]
            result=subprocess.run(command,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertNotIn('LABEL_ONLY_ANSWER',(output/'memory.jsonl').read_text())
            self.assertIn('LABEL_ONLY_ANSWER',(output/'evaluation.jsonl').read_text())
            self.assertEqual(json.loads((output/'report.json').read_text())['samples'],2)
            self.assertNotIn('LABEL_ONLY_ANSWER',result.stdout+result.stderr)
            invalid=root/'invalid.jsonl'
            invalid.write_text(dumps(list(self.stream().samples())[0])+'\n{"invalid":"PRIVATE_TEXT"}')
            config.write_text(json.dumps({'plugin':'dataset-jsonl','parameters':{'path':str(invalid)}}))
            bad_output=root/'bad';command[-1]=str(bad_output)
            result=subprocess.run(command,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,2,result.stderr)
            self.assertFalse(bad_output.exists())
            self.assertNotIn('PRIVATE_TEXT',result.stdout+result.stderr)

    def test_benchmark_and_memory_roles_cannot_be_swapped(self):
        with self.assertRaisesRegex(ContractError,'role mismatch'):
            load_benchmark(PluginRequest(plugin='mem0',parameters={'path':'missing.json'}),registry=default_registry(discover=False))
