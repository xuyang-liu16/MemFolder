"""Rate, current-text and official API witnesses; no model downloads or inference."""
import asyncio
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys

from memfolder.assembly import assemble
from memfolder.catalog import default_registry
from memfolder.compression import ServiceMap, DiagnosticCollector
from memfolder.core import ContractError, FrozenMap, RetentionPolicy
from memfolder.lingua_service import LLMLingua2Service
from memfolder.operators import TextOperator, ConcatWriter, TomeEmbeddingBuilder
from memfolder.operators.llmlingua2 import LLMLingua2Writer
from memfolder.plugins import BuildContext, PluginRequest
from memfolder.experiment import assemble_experiment
from test_temporal_tome import fixture, run as run_record

ROOT = Path(__file__).resolve().parents[1]


class Compressor:
    def __init__(self, empty=False): self.calls=[]; self.empty=empty
    def compress_prompt(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return {'compressed_prompt': '' if self.empty else 'compressed: '+text,
                'origin_tokens': 20, 'compressed_tokens': 11}


def service(empty=False):
    provider=LLMLingua2Service(device_map='cpu',dtype='float32')
    compressor=Compressor(empty)
    provider.__dict__['_compressor']=compressor
    return provider,compressor


def recipe(rate=.55):
    config=json.loads((ROOT/'examples/recipes/llmlingua2-post-record.json').read_text(encoding='utf-8'))
    config['operator']['parameters']['writer']['parameters']['rate']=rate
    return config


class LinguaTests(unittest.TestCase):
    def test_default_and_explicit_rate_are_forwarded_without_token_override(self):
        provider,compressor=service()
        for rate in (.55,.8):
            value=asyncio.run(provider.compress('current merged text',rate=rate))
            self.assertEqual(compressor.calls[-1],('current merged text',{'rate':rate,'use_context_level_filter':False}))
            self.assertEqual(value['input_text_sha256'],sha256(b'current merged text').hexdigest())
            self.assertEqual(value['input_view'],'current_record')
        self.assertEqual(LLMLingua2Writer().rate,.55)

    def test_rate_and_text_participate_in_request_and_assembly_identities(self):
        provider,_=service()
        values=[asyncio.run(provider.compress(text,rate=rate))['request_fingerprint']
                for text,rate in [('final record',.55),('final record',.8),('other record',.55)]]
        self.assertEqual(len(set(values)),3)
        self.assertNotEqual(assemble(recipe(.55)).config_fingerprint,assemble(recipe(.8)).config_fingerprint)
        self.assertNotEqual(LLMLingua2Service(dtype='float16').cache_identity,
                            LLMLingua2Service(dtype='float32').cache_identity)

    def test_invalid_rates_rejected_before_classifier_call(self):
        provider,compressor=service()
        for rate in (0,-.1,1.1,True,'0.55',float('nan'),float('inf')):
            with self.subTest(rate=rate):
                with self.assertRaises(ContractError):LLMLingua2Writer(rate=rate)
                with self.assertRaises(ContractError):asyncio.run(provider.compress('text',rate=rate))
        self.assertEqual(compressor.calls,[])

    def test_context_reads_final_record_text_once_and_keeps_latest_time_and_lineage(self):
        record,_,_,_=run_record(fixture(),operator=TextOperator(ConcatWriter(),TomeEmbeddingBuilder()))
        provider,compressor=service()
        request=replace(fixture(),snapshot=record.snapshot,budgets=(),state=None,mode='once')
        diagnostics=DiagnosticCollector()
        result=asyncio.run(assemble(recipe()).engine.run(request,
            services=ServiceMap({'llmlingua2':provider}),diagnostics=diagnostics))
        self.assertEqual([text for text,_ in compressor.calls],[n.text for n in record.snapshot.records])
        self.assertEqual(len(compressor.calls),3)
        self.assertEqual(len(result.snapshot.records),3)
        for before,after in zip(record.snapshot.records,result.snapshot.records):
            self.assertEqual(before.origins,after.origins)
            self.assertEqual(before.order,after.order)
            self.assertEqual(before.time_ranges,after.time_ranges)
            self.assertEqual(before.extensions.get('memfolder.event_timestamp'),after.extensions.get('memfolder.event_timestamp'))
            self.assertEqual(before.extensions.get('memfolder.timestamp_policy'),after.extensions.get('memfolder.timestamp_policy'))
            self.assertEqual(after.embeddings,())
            self.assertEqual(after.extensions['memfolder.writer']['rate'],.55)

    def test_protected_record_is_not_compressed(self):
        request=fixture(n=4)
        records=list(request.snapshot.records)
        records[0]=replace(records[0],retention=RetentionPolicy(may_rewrite=False))
        request=replace(request,snapshot=replace(request.snapshot,records=tuple(records)),budgets=(),mode='once')
        provider,compressor=service()
        result=asyncio.run(assemble(recipe()).engine.run(request,services=ServiceMap({'llmlingua2':provider})))
        self.assertEqual(len(compressor.calls),3)
        self.assertEqual(result.snapshot.records[0],records[0])

    def test_empty_classifier_output_is_explicit_source_preserving_fallback(self):
        provider,_=service(empty=True)
        request=replace(fixture(n=2),budgets=(),mode='once')
        result=asyncio.run(assemble(recipe()).engine.run(request,services=ServiceMap({'llmlingua2':provider})))
        self.assertEqual([n.text for n in result.snapshot.records],[n.text for n in request.snapshot.records])
        self.assertTrue(all(o.status=='fallback' and o.reason_code=='empty_classifier_output'
                            for o in result.steps[0].result.outcomes))

    def test_service_cannot_silently_return_different_rate_or_source(self):
        provider,_=service()
        correct=asyncio.run(provider.compress('current text',rate=.55))
        action=SimpleNamespace(kind='rewrite',input_view='current')
        member=SimpleNamespace(text='current text',node_id='n')
        for patch in ({'rate':.8},{'input_text_sha256':'stale'},{'input_view':'original'}):
            class Wrong:
                def compress(self,text,*,rate):return {**correct,**patch}
            context=SimpleNamespace(services=ServiceMap({'llmlingua2':Wrong()}))
            with self.assertRaises(ContractError):asyncio.run(LLMLingua2Writer().write((member,),action,context))
        with self.assertRaises(ContractError):
            asyncio.run(LLMLingua2Writer().write((member,),replace_action_original(),None))

    def test_service_can_be_assembled_without_loading_optional_model(self):
        registry=default_registry(discover=False)
        created=registry.create(PluginRequest.from_mapping({'plugin':'llmlingua2-service'}),
            role='service',context=BuildContext(base_path=ROOT,registry=registry),available=()).instance
        self.assertIsInstance(created,LLMLingua2Service)
        self.assertNotIn('_compressor',created.__dict__)

    def test_official_constructor_pins_version_revision_and_llmlingua2(self):
        calls=[]
        compressor=Compressor()
        def constructor(**kwargs):calls.append(kwargs);return compressor
        provider=LLMLingua2Service()
        with patch('memfolder.lingua_service.version',return_value='0.2.2'), patch.dict(sys.modules,{
                'llmlingua':SimpleNamespace(PromptCompressor=constructor),
                'torch':SimpleNamespace(float16='fake-float16')}):
            asyncio.run(provider.compress('record output',rate=.55))
        self.assertEqual(calls[0]['model_config']['revision'],provider.revision)
        self.assertTrue(calls[0]['use_llmlingua2'])
        self.assertEqual(calls[0]['model_config']['torch_dtype'],'fake-float16')
        asyncio.run(provider.close())
        self.assertNotIn('_compressor',provider.__dict__)

    def test_experiment_keeps_adaptive_default_and_explicit_round_limits(self):
        path=ROOT/'examples/experiments/offline-demo.json'
        config=json.loads(path.read_text(encoding='utf-8'))
        config['run'].pop('max_rounds',None)
        self.assertIsNone(assemble_experiment(config,base_path=path.parent).settings['max_rounds'])
        config['run']['max_rounds']=20
        self.assertEqual(assemble_experiment(config,base_path=path.parent).settings['max_rounds'],20)
        config['run']['max_rounds']=0
        with self.assertRaises(ContractError):assemble_experiment(config,base_path=path.parent)


def replace_action_original():
    return SimpleNamespace(kind='rewrite',input_view='original')


if __name__=='__main__':unittest.main()
