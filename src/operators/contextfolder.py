"""ContextFolder: source-fact triage and blind verification.

Fact questions are generated from compression inputs. Benchmark questions and
ground truth are absent from this API. All five loop stages can be replaced.
"""
from __future__ import annotations
from ..planning.common import resolve

from dataclasses import dataclass
import json
from ..core import FrozenMap, fingerprint
from ..core.values import require
from ..planning.common import emit, spec
from . import contextfolder_prompts as prompts
from .types import ChatRequest, TextWriteResult, Fact, EncodingRound
from ..prompt_protocol import PROTOCOL_ID, render_merge, prompt_hash


def json_object(raw):
    if type(raw) is not str: return {}
    try:
        text=raw.strip().strip('`').strip()
        if text.startswith('json'): text=text[4:].strip()
        start=text.find('{'); end=text.rfind('}')
        value=json.loads(text[start:end+1])
        return value if isinstance(value,dict) else {}
    except (ValueError,TypeError):
        return {}


async def chat(context, service, role, prompt, max_tokens=None):
    result=await resolve(context.services.require(service).complete(ChatRequest(role=role,prompt=prompt,max_tokens=max_tokens)))
    require(type(result) is str,'Chat service must return text')
    return result


@dataclass(frozen=True)
class FactPlanner:
    service: str = 'chat'
    max_tokens: int = 1500
    spec = spec('contextfolder.fact_planner','fact_planner')
    async def extract(self,lines,context):
        payload=json_object(await chat(context,self.service,'fact_extract',prompts.FACT_EXTRACT.format(lines=lines),self.max_tokens))
        raw=payload.get('facts');facts=[]
        if not isinstance(raw,(list,tuple)): return ()
        for item in raw:
            if not isinstance(item,dict) or not item.get('question'): continue
            # Explicitly parse booleans: the string "false" is not a true verdict.
            inferable=item.get('inferable',False)
            if type(inferable) is not bool: inferable=False
            facts.append(Fact(str(item.get('fact','')),str(item['question']),str(item.get('answer','')),
                              str(item.get('importance','')).lower(),inferable))
        return tuple(facts)


@dataclass(frozen=True)
class FactTriage:
    strict_below_ratio: float = .65
    spec = spec('contextfolder.fact_triage','triage_policy')
    def required(self,facts,ratio,context):
        levels={'high'} if ratio<self.strict_below_ratio else {'high','med'}
        return frozenset(i for i,f in enumerate(facts) if f.importance in levels and not f.inferable)


@dataclass(frozen=True)
class ContextCompiler:
    service: str = 'chat'
    max_tokens: int = 1024
    spec = spec('contextfolder.compiler','compiler')
    async def compile(self,lines,n,facts,source_tokens,target,feedback,context):
        triage='\n'.join(f'{i+1}. {f.label} {f.fact}' for i,f in enumerate(facts))
        prompt=prompts.COMPRESS.format(n=n,src=source_tokens,target=target,facts_list=triage,lines=lines)
        return (await chat(context,self.service,'compile',prompt+feedback,self.max_tokens)).strip('`').strip()


@dataclass(frozen=True)
class BlindFactVerifier:
    service: str = 'chat'
    answer_tokens: int = 1500
    judge_tokens: int = 1400
    spec = spec('contextfolder.blind_verifier','verifier')
    async def verify(self,encoding,facts,context):
        questions='\n'.join(f'{i+1}. {f.question}' for i,f in enumerate(facts))
        # The answerer receives encoding + questions + decode legend ONLY.
        answered=json_object(await chat(context,self.service,'blind_answer',
            prompts.BLIND_FACT_ANSWER.format(enc=encoding,questions=questions,k=len(facts)),self.answer_tokens))
        answers=answered.get('answers',[])
        if not isinstance(answers,list): answers=[]
        block='\n'.join(f'{i+1}. {a}' for i,a in enumerate(answers))
        reference='\n'.join(f'{i+1}. fact: {f.fact} | expected: {f.answer}' for i,f in enumerate(facts))
        judged=json_object(await chat(context,self.service,'fact_judge',
            prompts.FACT_RECOVERY_JUDGE.format(facts=reference,answers=block,k=len(facts)),self.judge_tokens))
        ok=judged.get('ok',[])
        if not isinstance(ok,list): ok=[]
        # Invalid/missing verdicts are failure; never coerce arbitrary strings to True.
        return tuple(i<len(ok) and ok[i] is True for i in range(len(facts)))


@dataclass(frozen=True)
class RepairFeedback:
    spec = spec('contextfolder.feedback','feedback_builder')
    def feedback(self,round_,target,context):
        issues=[]
        if round_.must_fix:
            issues.append('MUST-FIX (required facts the blind reader could not recover):\n'
                +'\n'.join('- '+round_.facts[i].fact for i in sorted(round_.must_fix))+'\nExpress THESE explicitly; clarity first for them.')
        if round_.tokens>target:
            issues.append(f'OVER BUDGET: {round_.tokens} vs {target} tokens. Tighten wording, merge lines, '
                f'or drop the {len(round_.optional_lost)} optional facts entirely.')
        elif round_.optional_lost:
            issues.append(f'Note: {len(round_.optional_lost)} optional (low/inferable) facts were dropped; that is acceptable.')
        return prompts.FEEDBACK.format(prev_tokens=round_.tokens,prev=round_.encoding,target=target,issues='\n'.join(issues))


@dataclass(frozen=True)
class ShortestCleanRound:
    spec = spec('contextfolder.round_selector','round_selector')
    def choose(self,rounds,context):
        clean=[r for r in rounds if not r.must_fix]
        return min(clean,key=lambda r:r.tokens) if clean else max(rounds,key=lambda r:(r.weighted_recovery,-r.tokens))


@dataclass(frozen=True)
class ContextFolderWriter:
    fact_planner: object = FactPlanner()
    triage: object = FactTriage()
    compiler: object = ContextCompiler()
    verifier: object = BlindFactVerifier()
    feedback: object = RepairFeedback()
    selector: object = ShortestCleanRound()
    target_ratio: float = .80
    max_rounds: int = 3
    budget_slack: float = 1.15
    tokenizer_service: str = 'tokenizer'
    fallback_service: str = 'chat'
    capture_text: bool = False
    capture_prompts: bool = False
    spec = spec('contextfolder.writer','text_writer', diagnostics=('memfolder.contextfolder.facts', 'memfolder.contextfolder.round', 'memfolder.contextfolder.selection'))

    async def write(self,members,action,context):
        require(0<self.target_ratio<=1 and type(self.max_rounds) is int and self.max_rounds>0 and self.budget_slack>=1,
                'Invalid ContextFolder compression configuration')
        from dataclasses import replace
        from .metering import MeteredServices
        meter=MeteredServices(context.services,context,capture_prompts=self.capture_prompts)
        context=replace(context,services=meter)
        tokenizer=context.services.require(self.tokenizer_service)
        measurement=getattr(tokenizer,'measurement_id',None)
        require(type(measurement) is str and bool(measurement),'Tokenizer must declare its measurement identity')
        def count(text):
            value=tokenizer.count(text)
            require(type(value) is int and value>=0,'Invalid token measurement')
            return value
        lines='\n'.join(f'Memory {i+1}: {m.text} | Timestamp: {m.time}' for i,m in enumerate(members))
        source_tokens=sum(count(m.text) for m in members);target=max(3,int(round(self.target_ratio*source_tokens)))
        facts=await resolve(self.fact_planner.extract(lines,context))
        required=await resolve(self.triage.required(facts,self.target_ratio,context))
        require(all(type(i) is int and 0<=i<len(facts) for i in required),'Triage returned invalid fact indices')
        emit(context,self.spec.plugin_id,'memfolder.contextfolder.facts',actions=(action.action_id,),
            required=sorted(required),weights=[f.weight for f in facts],
            facts=[{'question_hash':fingerprint(f.question),'importance':f.importance,'inferable':f.inferable,
                    **({'fact':f.fact,'question':f.question,'answer':f.answer} if self.capture_text else {})} for f in facts])
        if not facts:
            fallback_prompt=render_merge(members)
            text=(await resolve(context.services.require(self.fallback_service).complete(ChatRequest(
                role='memory_merge',prompt=fallback_prompt,prompt_id=PROTOCOL_ID+'.merge')))).strip()
            if not text:
                text='; '.join(m.text.strip() for m in members if m.text.strip());reason='empty_oneshot_source_fallback'
            else: reason='no_facts_oneshot'
            return TextWriteResult(text=text,status='fallback',reason_code=reason,
                usage=FrozenMap({'chat_calls':meter.calls,'source_tokens':source_tokens,'final_tokens':count(text)}),
                metadata=FrozenMap({'design':'contextfolder.triage_loop.v1','measurement_id':measurement,'status':'oneshot',
                    'protocol_id':PROTOCOL_ID,'prompt_id':PROTOCOL_ID+'.merge',
                    'prompt_sha256':prompt_hash(fallback_prompt)}))
        rounds=[];feedback=''
        for index in range(1,self.max_rounds+1):
            encoding=await resolve(self.compiler.compile(lines,len(members),facts,source_tokens,target,feedback,context))
            require(type(encoding) is str,'Compiler must return text')
            ok=await resolve(self.verifier.verify(encoding,facts,context))
            require(len(ok)==len(facts) and all(type(v) is bool for v in ok),'Verifier output must align with facts')
            current=EncodingRound(index,encoding,count(encoding),tuple(ok),tuple(facts),frozenset(required))
            rounds.append(current)
            emit(context,self.spec.plugin_id,'memfolder.contextfolder.round',actions=(action.action_id,),
                 round=index,tokens=current.tokens,target=target,ok=list(current.ok),must_fix=sorted(current.must_fix),
                 weighted_recovery=current.weighted_recovery,encoding_hash=fingerprint(encoding),
                 **({'encoding':encoding} if self.capture_text else {}))
            if not current.must_fix and current.tokens<=int(target*self.budget_slack) and encoding.strip(): break
            feedback=await resolve(self.feedback.feedback(current,target,context))
        best=await resolve(self.selector.choose(tuple(rounds),context))
        require(any(best is r for r in rounds),'Round selector returned an unrelated encoding')
        status='success';reason=None;text=best.encoding;chosen=best.index
        if best.tokens>=source_tokens:
            shortest=min(rounds,key=lambda r:r.tokens)
            if shortest.tokens<source_tokens: best=shortest;text=best.encoding;chosen=best.index
            else:
                text='; '.join(m.text.strip() for m in members if m.text.strip());status='fallback';reason='encoding_not_smaller';chosen=None
        if not text.strip():
            text='; '.join(m.text.strip() for m in members if m.text.strip());status='fallback';reason='empty_encoding_source_fallback';chosen=None
        # Measure actual stored text even when the separator adds tokens to source sums.
        metadata={'design':'contextfolder.triage_loop.v1','measurement_id':measurement,'target_ratio':self.target_ratio,
            'target_tokens':target,'chosen_round':chosen,'required_lost':len(best.must_fix) if chosen else None,
            'weighted_recovery':best.weighted_recovery if chosen else None}
        emit(context,self.spec.plugin_id,'memfolder.contextfolder.selection',actions=(action.action_id,),**metadata,status=status,reason=reason)
        return TextWriteResult(text=text,status=status,reason_code=reason,
            usage=FrozenMap({'chat_calls':meter.calls,'source_tokens':source_tokens,'final_tokens':count(text),'rounds':len(rounds)}),
            metadata=FrozenMap(metadata))
