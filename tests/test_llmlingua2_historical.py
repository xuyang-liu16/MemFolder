"""Recovered historical call/codec witnesses; no model, network, or paid API."""
import asyncio
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys

from memfolder.catalog import default_registry
from memfolder.core import AlgorithmContext, ContentPart, ContractError, FrozenMap, NullDiagnostics
from memfolder.compression import ServiceMap
from memfolder.lingua_historical import HistoricalLLMLingua2Service, PROFILE
from memfolder.lingua_service import LLMLingua2Service
from memfolder.plugins import BuildContext, PluginRequest
from memfolder.operators.llmlingua2 import LLMLingua2Writer
from memfolder.wrappers.lingua_historical import HistoricalLLMLinguaMem0Codec, HistoricalAllTextEmbeddings
from memfolder.wrappers.types import NativeArchive
from test_temporal_tome import fixture, SPACE


class Compressor:
    def __init__(self, output=' compressed text ', error=None):
        self.calls=[]; self.output=output; self.error=error

    def compress_prompt(self, text, **kwargs):
        self.calls.append((text,kwargs))
        if self.error:
            raise self.error
        return {'compressed_prompt':self.output}


def provider(*, tokens=23, output=' compressed text ', error=None):
    value=HistoricalLLMLingua2Service(device_map='cpu')
    value.__dict__['_counter']=SimpleNamespace(count=lambda text:tokens)
    value.__dict__['_compressor']=Compressor(output,error)
    return value


class HistoricalTests(unittest.TestCase):
    def test_target_budget_digit_newline_strip_and_raw_binding(self):
        service=provider(tokens=23)
        raw='  born 1994\nlives in Boston  '
        result=asyncio.run(service.compress(raw,rate=.55))
        self.assertEqual(service._compressor.calls,[('born 1994\nlives in Boston',
            {'target_token':13,'force_reserve_digit':True,'force_tokens':['\n']})])
        self.assertEqual(result['text'],'compressed text')
        self.assertEqual(result['input_text_sha256'],sha256(raw.encode()).hexdigest())
        self.assertEqual(result['normalized_input_sha256'],sha256(raw.strip().encode()).hexdigest())
        self.assertEqual(result['profile'],PROFILE)

    def test_short_record_minimum_python_round_and_conditional_newline(self):
        for tokens,target in ((1,6),(10,6),(30,16),(50,28)):
            with self.subTest(tokens=tokens):
                service=provider(tokens=tokens)
                asyncio.run(service.compress('\n final Record \n',rate=.55))
                self.assertEqual(service._compressor.calls[0],('final Record',
                    {'target_token':target,'force_reserve_digit':True}))

    def test_constructor_pins_snapshot_and_preserves_constructor_defaults(self):
        downloads=[]; constructors=[]
        def download(**kwargs): downloads.append(kwargs); return '/pinned/checkpoint'
        def constructor(**kwargs): constructors.append(kwargs); return Compressor()
        service=HistoricalLLMLingua2Service(device_map='cpu')
        service.__dict__['_counter']=SimpleNamespace(count=lambda text:12)
        with patch('memfolder.lingua_historical.version',return_value='0.2.2'),patch.dict(sys.modules,{
            'huggingface_hub':SimpleNamespace(snapshot_download=download),
            'llmlingua':SimpleNamespace(PromptCompressor=constructor)}):
            asyncio.run(service.compress('final Record',rate=.55))
        self.assertEqual(downloads,[{'repo_id':service.model_name,'revision':service.revision}])
        self.assertEqual(constructors,[{'model_name':'/pinned/checkpoint',
                                      'use_llmlingua2':True,'device_map':'cpu'}])
        asyncio.run(service.close())
        self.assertNotIn('_compressor',service.__dict__)

    def test_profiles_rates_and_text_cannot_share_cache_identity(self):
        service=provider()
        self.assertNotEqual(service.cache_identity,LLMLingua2Service(device_map='cpu').cache_identity)
        ids=[asyncio.run(service.compress(text,rate=rate))['request_fingerprint']
             for text,rate in (('record',.55),('record',.8),('other record',.55))]
        self.assertEqual(len(set(ids)),3)

    def test_empty_output_explicit_and_other_model_failures_propagate(self):
        result=asyncio.run(provider(output=' ').compress('final Record',rate=.55))
        self.assertEqual(result['text'],'')
        self.assertTrue(result['source_preserved'])
        self.assertEqual(result['fallback_reason'],'empty_classifier_output')
        with self.assertRaisesRegex(RuntimeError,'CUDA out of memory'):
            asyncio.run(provider(error=RuntimeError('CUDA out of memory')).compress('text',rate=.55))

    def test_empty_fallback_retains_normalized_record_and_explicit_status(self):
        raw='  final Record\n '
        member=SimpleNamespace(text=raw,node_id='test-node')
        action=SimpleNamespace(kind='rewrite',input_view='current')
        context=AlgorithmContext(services=ServiceMap({'llmlingua2':provider(output='')}),
                                 diagnostics=NullDiagnostics())
        written=asyncio.run(LLMLingua2Writer().write((member,),action,context))
        self.assertEqual(written.text,'final Record')
        self.assertEqual(written.status,'fallback')
        self.assertEqual(written.reason_code,'empty_classifier_output')
        self.assertEqual(written.metadata['output_text_sha256'],sha256(written.text.encode()).hexdigest())

    def test_normalized_fallback_cannot_replace_input_with_unrelated_text(self):
        service=provider(output='')
        value=asyncio.run(service.compress('  final Record  ',rate=.55))
        value['fallback_text']='unrelated text'
        class Wrong:
            async def compress(self,*args,**kwargs):return value
        context=AlgorithmContext(services=ServiceMap({'llmlingua2':Wrong()}),diagnostics=NullDiagnostics())
        with self.assertRaises(ContractError):
            asyncio.run(LLMLingua2Writer().write((SimpleNamespace(text='  final Record  ',node_id='test-node'),),
                                                SimpleNamespace(kind='rewrite',input_view='current'),context))

    def test_invalid_input_never_calls_classifier(self):
        service=provider()
        for rate in (0,1.1,True,float('nan')):
            with self.assertRaises(ContractError):asyncio.run(service.compress('text',rate=rate))
        with self.assertRaises(ContractError):asyncio.run(service.compress(' ',rate=.55))
        self.assertEqual(service._compressor.calls,[])

    def test_plugins_assemble_lazily(self):
        registry=default_registry(discover=False)
        context=BuildContext(base_path=Path(__file__).parent,registry=registry)
        service=registry.create(PluginRequest.from_mapping({'plugin':'llmlingua2-historical-service'}),
                               role='service',context=context,available=()).instance
        codec=registry.create(PluginRequest.from_mapping({'plugin':'llmlingua2-historical-mem0-codec'}),
                              role='native_codec',context=context,available=()).instance
        self.assertIsInstance(service,HistoricalLLMLingua2Service)
        self.assertIsInstance(codec,HistoricalLLMLinguaMem0Codec)
        self.assertNotIn('_compressor',service.__dict__)

    def test_codec_uses_latest_contributor_not_retained_record_anchor(self):
        source=fixture(n=3).snapshot
        first,last=source.records[0],source.records[-1]
        merged=replace(first,origins=first.origins+last.origins,
                       parts=(ContentPart(modality='text',text='merged compressed text'),),embeddings=())
        merged=replace(merged,embeddings=(replace(first.embeddings[0],
                        source_fingerprint=merged.content_fingerprint),))
        snapshot=replace(source,records=(merged,source.records[1]))
        context=AlgorithmContext(services=ServiceMap(),diagnostics=NullDiagnostics())
        package=HistoricalLLMLinguaMem0Codec(SPACE).encode(snapshot,NativeArchive(source),context)
        self.assertEqual(package.node_id_map[merged.node_id],last.native['id'])
        payload=next(p['payload'] for p in package.data['points'] if p['id']==last.native['id'])
        self.assertEqual(payload['data'],'merged compressed text')
        self.assertEqual(payload['user_id'],'owner0')
        self.assertEqual(payload['timestamp'],'old-native-time')
        self.assertNotIn('memfolder',payload)

    def test_all_text_embeddings_reencode_unchanged_singletons(self):
        source=fixture(n=3).snapshot
        calls=[]
        class Encoder:
            async def encode(self,texts):
                calls.append(texts)
                return ((0.,1.),)*len(texts)
        context=AlgorithmContext(services=ServiceMap({'embeddings':Encoder()}),diagnostics=NullDiagnostics())
        result=asyncio.run(HistoricalAllTextEmbeddings(SPACE).refresh(source,context))
        self.assertEqual(calls,[tuple(n.text for n in source.records)])
        self.assertEqual([n.embeddings[0].values for n in result.records],[(0.,1.)]*3)
        for before,after in zip(source.records,result.records):
            self.assertEqual(replace(after,embeddings=before.embeddings),before)


if __name__=='__main__':unittest.main()
