"""Protocol parity, API envelopes and cache isolation; no paid requests."""
import asyncio
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from memfolder.core import ContractError,FrozenMap,ContentPart,Prediction
from memfolder.compression import ServiceMap
from memfolder.operators import NativeSummaryWriter,MemForestPairWriter,TomePairWriter,Member,ContextFolderWriter
from memfolder.operators.types import ChatRequest
from memfolder.evaluation import QAPrompt,ContextFolderPrompt,ReaderContext,ChatAnswerer,ChatJudge
from memfolder.prompt_protocol import (PROTOCOL_ID,render_merge,render_qa,render_judge,
                                       protocol_manifest)
from memfolder.prompt_templates import (MEMFOREST_MERGE_PROMPT,MEMFOREST_QA_PROMPT,
                                        MEMFOREST_JUDGE_PROMPT)
from memfolder.services import CompatibleHTTP,CachedService
from fixtures import sample
from test_experiment import CTX,run


class RecordingChat:
    cache_identity='offline.prompt.protocol.test'
    def __init__(self,response='merged text'):
        self.requests=[];self.response=response
    def complete(self,request):
        self.requests.append(request)
        return self.response


class PromptProtocolTests(unittest.TestCase):
    def test_upstream_literal_digests_are_pinned(self):
        self.assertEqual(sha256(MEMFOREST_MERGE_PROMPT.encode()).hexdigest(),
                         '9e24917dbd537d43afeeffa0e6a506199108bcdbbe0820bee51de6ddff109a4c')
        self.assertEqual(sha256(MEMFOREST_QA_PROMPT.encode()).hexdigest(),
                         'f3c786104816bba61d03b7f41c2be45009e6c8c296a04d9712ab1a59e4ae2399')
        self.assertEqual(sha256(MEMFOREST_JUDGE_PROMPT.encode()).hexdigest(),
                         '62395dd312a631dfd9355026a0b69cc936018274c3198b6365b5c2a5c9bca9e0')
        # This prompt has different instructions from the old fact-preserving ToMe.
        self.assertIn('generate a concise and coherent summary paragraph',MEMFOREST_MERGE_PROMPT)
        self.assertNotIn('concrete atomic facts',MEMFOREST_MERGE_PROMPT)
    def test_all_three_record_writers_send_identical_pair_requests(self):
        members=(Member('a','Older {{question}} fact','2023-01-01'),Member('b','Newer fact','2023-02-01'))
        packets=[]
        for writer in (NativeSummaryWriter(),MemForestPairWriter(),TomePairWriter()):
            chat=RecordingChat();ctx=replace(CTX,services=ServiceMap({'chat':chat}))
            written=run(writer.write(members,None,ctx))
            packets.append(chat.requests[0])
            self.assertEqual(written.metadata['protocol_id'],PROTOCOL_ID)
        self.assertEqual(packets[0],packets[1]);self.assertEqual(packets[1],packets[2])
        self.assertEqual(packets[0].prompt,MEMFOREST_MERGE_PROMPT.format(
            members[0].text,members[0].time,members[1].text,members[1].time))
        self.assertEqual(packets[0].message_role,'user')
    def test_n_way_adapter_preserves_all_slots_and_shared_instructions(self):
        members=tuple(Member(str(i),'fact '+str(i),'time '+str(i)) for i in range(4))
        prompt=render_merge(members)
        self.assertIn('following 4 memory entries',prompt)
        for i in range(4):self.assertIn(f'Memory {i+1}: fact {i}, Timestamp {i+1}: time {i}',prompt)
        self.assertNotIn('concrete atomic facts',prompt)
        self.assertIn('concise and coherent summary paragraph',prompt)
    def test_singleton_record_stays_an_identity_operation(self):
        chat=RecordingChat();ctx=replace(CTX,services=ServiceMap({'chat':chat}))
        written=run(NativeSummaryWriter().write((Member('a','unchanged','now'),),None,ctx))
        self.assertEqual(written.text,'unchanged');self.assertEqual(chat.requests,[])
    def test_contextfolder_no_facts_summary_uses_the_shared_merge(self):
        class Counter:
            measurement_id='offline.words'
            def count(self,text):return len(text.split())
        class Chat(RecordingChat):
            def complete(self,request):
                self.requests.append(request)
                return '{"facts":[]}' if request.role=='fact_extract' else 'merged text'
        members=(Member('a','older memory','old'),Member('b','newer memory','new'))
        chat=Chat();ctx=replace(CTX,services=ServiceMap({'chat':chat,'tokenizer':Counter()}))
        written=run(ContextFolderWriter().write(members,SimpleNamespace(action_id='merge'),ctx))
        self.assertEqual(len(chat.requests),2)
        packet=chat.requests[-1]
        self.assertEqual(packet.prompt,render_merge(members))
        self.assertEqual(packet.prompt_id,PROTOCOL_ID+'.merge')
        self.assertEqual(packet.role,'memory_merge')
        self.assertEqual(written.metadata['protocol_id'],PROTOCOL_ID)
    def test_online_templates_select_identical_qa_and_judge_plugins(self):
        import json
        root=Path(__file__).resolve().parents[1]/'examples/experiments'
        for name in ('recordfolder-template.json','contextfolder-template.json'):
            config=json.loads((root/name).read_text(encoding='utf-8'))
            answerer=config['reader']['parameters']['answerer']
            self.assertEqual(answerer['parameters']['prompt_builder']['plugin'],'memforest-qa-prompt')
            self.assertEqual(config['evaluator']['parameters']['metrics'],[{'plugin':'memforest-judge'}])
            self.assertEqual(config['services']['judge'],config['services']['chat'])
    def test_qa_uses_memforest_owner_slots_and_does_not_rewrite_memory_braces(self):
        groups=(('Alice_1',('today: literal {{question}} and {{speaker_2_memories}}',)),
                ('Bob_1',('yesterday: another fact',)))
        question='What happened?';prompt=render_qa(question,groups)
        self.assertIn('Memories for user Alice:',prompt);self.assertIn('Memories for user Bob:',prompt)
        self.assertIn('literal {{question}} and {{speaker_2_memories}}',prompt)
        self.assertIn('Question: '+question,prompt)
    def test_contextfolder_alias_and_public_options_share_the_same_qa(self):
        question=sample().evaluation.reader_input().questions[0]
        question=replace(question,options=FrozenMap({'A':'tea','B':'coffee'}))
        context=ReaderContext('compact memory',(),())
        self.assertEqual(QAPrompt().build(question,context),ContextFolderPrompt().build(question,context))
        self.assertIn('OPTIONS',QAPrompt().build(question,context))
        for kwargs in ({'legend':'special decode'},{'instructions':'new grading'}):
            with self.assertRaises(ContractError):QAPrompt(**kwargs)
    def test_more_than_two_owners_are_retained_and_attributed(self):
        prompt=render_qa('q',(('Alice',('a',)),('Bob',('b',)),('Carol',('c',))))
        self.assertIn('[Bob] b',prompt);self.assertIn('[Carol] c',prompt)
    def test_qa_uses_system_message_and_provider_honors_request_fields(self):
        question=sample().evaluation.reader_input().questions[0]
        chat=RecordingChat('tea');ctx=replace(CTX,services=ServiceMap({'chat':chat}))
        run(ChatAnswerer().answer(question,ReaderContext('memory',(),()),ctx))
        request=chat.requests[0];self.assertEqual(request.message_role,'system')
        self.assertIsNone(request.max_tokens)
        provider=CompatibleHTTP('https://example.invalid/v1','offline-model')
        with patch.object(CompatibleHTTP,'_post',return_value={'choices':[{'message':{'content':'tea'}}]}) as post:
            run(provider.complete(request))
        self.assertEqual(post.call_args.args[1]['messages'][0]['role'],'system')
        judge_request=ChatRequest(role='memforest_judge',prompt='q',response_format='json_object')
        with patch.object(CompatibleHTTP,'_post',return_value={'choices':[{'message':{'content':'{"label":"CORRECT"}'}}]}) as post:
            run(provider.complete(judge_request))
        self.assertEqual(post.call_args.args[1]['response_format'],{'type':'json_object'})
    def test_judge_is_exact_memforest_with_strict_json_labels(self):
        case=replace(sample().evaluation.cases[0],as_of=None)
        pred=Prediction(question_id=case.question_id,sample=case.sample,
                        answer=(ContentPart(modality='text',text='tea'),))
        chat=RecordingChat('{"label":"CORRECT"}');ctx=replace(CTX,services=ServiceMap({'judge':chat}))
        metric=run(ChatJudge().score(case,pred,ctx))[0]
        expected=MEMFOREST_JUDGE_PROMPT.format(question=' '.join(p.text or '' for p in case.question),
            gold_answer=str(case.ground_truth['answer']),generated_answer='tea')
        self.assertEqual(chat.requests[0].prompt,expected);self.assertEqual(metric.value,1.)
        self.assertEqual(chat.requests[0].response_format,'json_object')
        for invalid in ('YES','CORRECT','{"label":"MAYBE"}','{"label":true}',
                        '{"label":"CORRECT","label":"WRONG"}'):
            chat.response=invalid
            with self.subTest(invalid=invalid),self.assertRaises(ContractError):
                run(ChatJudge().score(case,pred,ctx))
        chat.response='{"label":"WRONG"}'
        self.assertEqual(run(ChatJudge().score(case,pred,ctx))[0].value,0.)
    def test_cache_separates_role_json_and_protocol(self):
        async def exercise(path):
            provider=RecordingChat();service=CachedService(provider,path,'test')
            request=ChatRequest(role='memory_qa',prompt='identical text')
            variants=(request,replace(request,message_role='system'),
                      replace(request,response_format='json_object'),replace(request,prompt_id=PROTOCOL_ID))
            for variant in variants:await service.complete(variant)
            for variant in variants:await service.complete(variant)
            self.assertEqual(len(provider.requests),4)
        with tempfile.TemporaryDirectory() as folder:run(exercise(Path(folder)/'cache.sqlite'))
    def test_personamem_choice_is_reference_data_in_the_same_judge_template(self):
        case=replace(sample().evaluation.cases[0],ground_truth=FrozenMap({'choice':'B'}),
                     options=FrozenMap({'A':'tea','B':'coffee'}))
        pred=Prediction(question_id=case.question_id,sample=case.sample,
                        answer=(ContentPart(modality='text',text='B'),))
        chat=RecordingChat('{"label":"CORRECT"}');ctx=replace(CTX,services=ServiceMap({'judge':chat}))
        run(ChatJudge().score(case,pred,ctx))
        self.assertIn('Gold answer: coffee',chat.requests[0].prompt)
        self.assertIn('OPTIONS',chat.requests[0].prompt)
        self.assertNotIn('TASK ',chat.requests[0].prompt)
    def test_shared_protocol_manifest_has_no_method_specific_legend(self):
        manifest=protocol_manifest()
        self.assertFalse(manifest['qa']['decoder_legend'])
        self.assertEqual(manifest['judge']['labels'],['CORRECT','WRONG'])
        expected=manifest['templates']['MEMFOREST_QA_PROMPT']['prompt_sha256']
        manifest['templates']['MEMFOREST_QA_PROMPT']['prompt_sha256']='observer-local-edit'
        self.assertEqual(protocol_manifest()['templates']['MEMFOREST_QA_PROMPT']['prompt_sha256'],expected)


if __name__=='__main__':unittest.main()
