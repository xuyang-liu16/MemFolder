"""Build uncompressed native MemOS memory and evaluate the LoCoMo questions."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time

from .native import ROOT, UPSTREAM, PROTOCOL, batches, build_batch, new_native, prompts, judge_messages, retrieve, save
from .transport import MemOSTransport
from .postgres import postgres_service
from .providers import digest
from .runtime import PACKAGE, CHAT_URL, EMBED_URL

REPORT=ROOT/'reports/memos_locomo'
RUN=ROOT/'runs/memos_locomo'
STATUS=REPORT/'status.json'
LOCK=threading.Lock()
START=time.monotonic()
STATE={'status':'starting','phase':'initialization','target_questions':1540,'compression':False,'agpr':False,
       'built_batches':0,'completed_questions':0,'total_batches':6022,
       'configuration_basis':'packaged native MemOS protocol'}

def status(**fields):
    with LOCK:
        STATE.update(fields)
        STATE.update(updated_at=time.strftime('%Y-%m-%d %H:%M:%S'),elapsed_seconds=time.monotonic()-START,pid=os.getpid())
        save(STATUS,STATE)

def validate_judge(content):
    match=re.search(r'\{\s*"label"\s*:\s*["\x27]([^"\x27]*)["\x27]\s*\}',content)
    if not match or match.group(1).upper() not in ['CORRECT','WRONG']:raise RuntimeError('Invalid official judge label')
    return match.group(1).upper()=='CORRECT'

def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def profile():
    code_names=[p.name for p in sorted(PACKAGE.glob('*.py'))]
    code={name:file_hash(PACKAGE/name) for name in code_names}
    protocol={**PROTOCOL,'actual_execution':{'embedding_provider':PROTOCOL['embedding']['backend'], 'chat_endpoint':CHAT_URL, 'execution_mode':'native_live',
        'native_components':['SimpleStructMemReader.fast','TreeTextMemory.add','AdvancedSearcher.search','PostgresGraphDB','HTTPBGEReranker','native API formatters'],
        'memory_read_mode':'fast raw, two messages per official ingestion request',
        'chat_window_max_tokens':PROTOCOL['memory']['chat_window_max_tokens'],'reorganize':False,'scheduler':False,'internet':False,'bm25':False,'cot':False,
        'reranker_boost_weights':{},'strict_provider_failure':True,'qa_uses_only_retrieved_context':True},
        'code_sha256':code,'packaged_resource_sha256':{name:file_hash(PACKAGE/name) for name in ['protocol.json','prompts.json','judge_parts.json','upstream.json','model.json','embedding_model.json']},'dataset_sha256':file_hash(ROOT/'inputs/locomo10.json'),
        'official_prompt_sha256':file_hash(UPSTREAM/'evaluation/scripts/locomo/prompts.py'),
        'official_judge_sha256':file_hash(UPSTREAM/'evaluation/scripts/locomo/locomo_eval.py')}
    identity=digest(protocol)
    save(REPORT/'execution_profile.json',{'identity':identity,'protocol':protocol})
    return identity

def questions(dataset):
    return [(c,qidx,qa) for c,row in enumerate(dataset) for qidx,qa in enumerate(row['qa']) if qa['category']!=5]

def evaluate(tree,transport,dataset,item,identity,templates):
    c,qidx,qa=item
    question=qa['question']
    destination=RUN/'qa'/f'c{c:02d}_q{qidx:04d}.json'
    if destination.exists():
        row=json.loads(destination.read_text(encoding='utf-8'))
        if row['identity']!=identity or row['question']!=question or row['gold_answer']!=qa['answer']:raise RuntimeError('QA checkpoint belongs to a different protocol/case')
        return row
    trace_path=RUN/'retrieval'/f'c{c:02d}_q{qidx:04d}.json'
    if trace_path.exists():
        trace=json.loads(trace_path.read_text(encoding='utf-8'))
        if trace['identity']!=identity or trace['question']!=question:raise RuntimeError('Retrieval checkpoint belongs to different case')
    else:
        speakers={}
        for side in ['a','b']:
            uid=f'locomo_{c}_speaker_{side}'
            result=retrieve(tree,question,uid)
            memories=result['text_mem'][0]['memories']
            if len(memories)!=PROTOCOL['search']['top_k_per_speaker']:raise RuntimeError('Native search returned an unexpected number of records: '+uid)
            speakers[side]={'user_name':uid,'result':result}
        trace={'identity':identity,'question':question,'speakers':speakers,'retrieved_at':time.strftime('%Y-%m-%d %H:%M:%S')}
        save(trace_path,trace)
    contexts={side:'\n'.join(mem['memory'] for mem in trace['speakers'][side]['result']['text_mem'][0]['memories'])+f"\n{trace['speakers'][side]['result'].get('pref_string','')}" for side in ['a','b']}
    conv=dataset[c]['conversation']
    context=templates['TEMPLATE_MEMOS'].format(speaker_1=conv['speaker_a'],speaker_1_memories=contexts['a'],speaker_2=conv['speaker_b'],speaker_2_memories=contexts['b'])
    messages=[{'role':'system','content':templates['ANSWER_PROMPT_MEMOS'].format(context=context,question=question)}]
    nonce=f'{identity}/c{c}/q{qidx}/qa_once'
    answer=transport.chat(kind='memos_qa',messages=messages,nonce=nonce,temperature=0).choices[0].message.content
    # Gold answer is passed solely to the official judge, after QA is complete.
    judge=transport.chat(kind='memos_judge_once',messages=judge_messages(question,qa['answer'],answer),nonce=f'{identity}/c{c}/q{qidx}/judge_once',validate=validate_judge,temperature=0).choices[0].message.content
    row={'identity':identity,'conv_idx':c,'qa_index':qidx,'category':qa['category'],'question':question,'gold_answer':qa['answer'],'answer':answer,'judge':judge,'correct':validate_judge(judge),'context':context,'context_sha256':digest(context),'context_words':len(context.split()),'retrieval_file':str(trace_path),'qa_runs':1,'judge_runs':1,'agpr':False,'finished_at':time.strftime('%Y-%m-%d %H:%M:%S')}
    save(destination,row)
    return row

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--build-workers',type=int,default=12)
    parser.add_argument('--qa-workers',type=int,default=4)
    args=parser.parse_args()
    identity=profile()
    dataset=json.loads((ROOT/'inputs/locomo10.json').read_text(encoding='utf-8'))
    all_batches=batches(dataset);cases=questions(dataset);templates=prompts()
    assert len(all_batches)==6022 and len(cases)==1540
    status(status='running',phase='building_raw_uncompressed_memory',identity=identity,build_workers=args.build_workers,qa_workers=args.qa_workers)
    transport=MemOSTransport(24)
    with postgres_service() as pg:
        reader,tree=new_native(transport)
        try:
            with ThreadPoolExecutor(max_workers=args.build_workers) as ex:
                futures={ex.submit(build_batch,reader,tree,batch):batch for batch in all_batches}
                for done,future in enumerate(as_completed(futures),1):
                    future.result()
                    status(built_batches=done,last_built_user=futures[future]['uid'])
            # Check actual persisted native rows, coverage, vector dimensions and tenant IDs.
            import psycopg2
            from .runtime import PORT,USER,DATABASE
            with psycopg2.connect(host='127.0.0.1',port=PORT,user=USER,dbname=DATABASE) as db:
                with db.cursor() as cursor:
                    cursor.execute('SELECT user_name,count(*),min(vector_dims(embedding)),max(vector_dims(embedding)) FROM memos.memories GROUP BY user_name ORDER BY user_name')
                    persisted=cursor.fetchall()
                    counts=Counter(batch['uid'] for batch in all_batches)
                    if {row[0]:row[1] for row in persisted}!=dict(counts) or any(row[2:]!=(1024,1024) for row in persisted):raise RuntimeError('Native persisted count/dimension/tenant audit failed')
            save(REPORT/'library_audit.json',{'status':'passed','identity':identity,'native_storage':'MemOS PostgresGraphDB + pgvector','nodes':6022,'tenants':20,'tenant_rows':persisted,'expected_nodes_per_user':counts,'compression':False,'source_turns':5882})
            status(phase='full_qa_and_judge',completed_questions=0)
            results=[]
            with ThreadPoolExecutor(max_workers=args.qa_workers) as ex:
                futures={ex.submit(evaluate,tree,transport,dataset,case,identity,templates):case for case in cases}
                for done,future in enumerate(as_completed(futures),1):
                    results.append(future.result())
                    status(completed_questions=done)
            results.sort(key=lambda row:(row['conv_idx'],row['qa_index']))
            if len(results)!=1540 or len({(r['conv_idx'],r['qa_index']) for r in results})!=1540:raise RuntimeError('Question coverage audit failed')
            category_counts=Counter(r['category'] for r in results)
            if dict(category_counts)!={1:282,2:321,3:96,4:841}:raise RuntimeError('Unexpected category coverage')
            correct=sum(r['correct'] for r in results)
            summary={'status':'complete','identity':identity,'questions':1540,'correct':correct,'judge_percent':100*correct/1540,
                'categories':{str(cat):{'n':n,'correct':sum(r['correct'] for r in results if r['category']==cat),'judge_percent':100*sum(r['correct'] for r in results if r['category']==cat)/n} for cat,n in sorted(category_counts.items())},
                'context_words_mean':sum(r['context_words'] for r in results)/1540,'qa_runs':1,'judge_runs':1,'agpr':False,
                'execution_mode':'native_live','completed_at':time.strftime('%Y-%m-%d %H:%M:%S')}
            save(REPORT/'full_results.json',results)
            save(REPORT/'full_summary.json',summary)
            status(status='complete',phase='complete',completed_questions=1540,judge_percent=summary['judge_percent'])
            print(json.dumps(summary,ensure_ascii=False),flush=True)
        finally:
            tree.graph_store.close()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        status(status='failed',error_type=type(exc).__name__,error=str(exc))
        raise
