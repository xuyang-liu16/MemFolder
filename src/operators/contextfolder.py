"""ContextFolder: source-fact triage and blind verification."""

from __future__ import annotations
from dataclasses import dataclass
import json
from ..component_runtime import emit, resolve, spec
from .contracts import ChatRequest, EncodingRound, Fact, TextWriteResult
from ..core import FrozenMap, fingerprint
from ..core.values import require
from ..prompt_protocol import PROTOCOL_ID, prompt_hash, render_merge


FACT_EXTRACT = """From the memory entries below, extract the KEY facts as a numbered list, and for each fact write a short verification question with its expected answer. A reader should be able to answer the question IF AND ONLY IF the fact is recoverable from a compressed encoding.

Scale the fact count to the input size: about 1 atomic fact per 10 source tokens (min 2, max 12), one question per atomic fact. A short single memory deserves only 2-4 questions about its ONE core fact (e.g. who/what/when), not a decomposition into trivia. For each fact also provide:
- "importance": "high" for key events, final states, exact dates/numbers/names, entity bindings, negations; "med" for preferences, plans, relation directions, quantities; "low" for reasons, modifiers, emotional framing, superseded older states
- "inferable": true if a reader could infer this fact from the OTHER extracted facts or from common knowledge, else false
Do NOT include meta information such as the memory entries' own timestamps as facts. Keep each fact atomic.

Memories:
{lines}

Answer with JSON only: {{"facts": [{{"fact": "...", "question": "...", "answer": "...", "importance": "high|med|low", "inferable": true|false}}]}}"""


COMPRESS = """You are a memory compressor writing for another equally intelligent LLM, not for humans. Compress the {n} memory entries below into a compact token sequence that another LLM can decode WITHOUT any external codebook.

Fixed grammar (one fact per line):
- `@YYYY-MM-DD` ONLY when a fact itself contains time information; NEVER attach entry timestamps to timeless facts
- `A -> B` for state changes; `E: state` for attributes; `~` negation; `?` uncertain
- Exact entity full names; exact numbers/dates verbatim
- NEVER add `User:`/`She:` prefixes unless the source itself names the subject
- cl100k discipline: dotted fragments like `M.son.acc` are EXPENSIVE, never use them; common whole words are cheap
- Short single memories must come out strictly shorter than the source: keep verb + object, drop titles' authors, reasons, feelings. E.g. "Loved 'Becoming Nicole' by Amy Ellis Nutt" -> `loved 'Becoming Nicole'`

SOFT TOKEN BUDGET: about {target} tokens (source: {src}).

TRIAGE THE FACTS BEFORE ENCODING. The key facts are listed below with labels:
- MUST KEEP: [high] facts that are NOT inferable — key events, final states, exact names/dates/numbers, negations. These must survive verbatim-recoverable.
- DROP FIRST: facts marked [inferable] — the reader can re-derive them from the facts you keep or from common knowledge. Do not spend a single token on them.
- DROP IF TIGHT: [low] facts — reasons, modifiers, emotional framing, superseded older states.
- [med] facts: keep only while you are within budget.
Omitting a fact is allowed and expected; distorting or inventing one is not.

Key facts to triage:
{facts_list}

Output ONLY the encoding.

Memories:
{lines}"""


FEEDBACK = """

VERIFIER FEEDBACK on your previous attempt ({prev_tokens} tokens, budget {target}):
---
{prev}
---
{issues}
Re-encode by EDITING the previous encoding. Restore ONLY the facts listed as MUST-FIX; do not spend tokens on optional facts unless you are well under budget; if over budget, tighten wording or drop optional facts. Output ONLY the new encoding."""


BLIND_FACT_ANSWER = """You see ONLY a compact memory encoding and a list of questions. The encoding uses this grammar: `@YYYY-MM-DD` = the fact happened on that date; `A -> B` = A changed into / transferred to B; `E: x` = entity E has attribute/state x; `~` = negation; `?` = uncertain/rumored; `;` and newlines separate facts; filler words are dropped but entity names, numbers, dates and relation directions are preserved. First silently decode each line into plain facts, then answer each question using ONLY what can be inferred from the decoded facts. If a question cannot be answered from the encoding, answer exactly "UNKNOWN". Do not guess.

Encoding:
{enc}

Questions:
{questions}

Answer with JSON only: {{"answers": ["...", "..."]}} with exactly {k} entries."""


FACT_RECOVERY_JUDGE = """Reference key facts with expected answers:
{facts}

A blind reader who saw only the compressed encoding answered the verification questions as follows:
{answers}

For each item, decide whether the fact is recoverable from the encoding. Be LENIENT: accept semantically close or partial answers, accept answers that are reasonably inferable from the encoding even if wording differs; only exact numbers/dates/names must match. Mark false only when the answer is missing, "UNKNOWN", or contradicts the fact.
Answer with JSON only: {{"ok": [true, false, ...]}} with exactly {k} entries."""


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
        payload=json_object(await chat(context,self.service,'fact_extract',FACT_EXTRACT.format(lines=lines),self.max_tokens))
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
        prompt=COMPRESS.format(n=n,src=source_tokens,target=target,facts_list=triage,lines=lines)
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
            BLIND_FACT_ANSWER.format(enc=encoding,questions=questions,k=len(facts)),self.answer_tokens))
        answers=answered.get('answers',[])
        if not isinstance(answers,list): answers=[]
        block='\n'.join(f'{i+1}. {a}' for i,a in enumerate(answers))
        reference='\n'.join(f'{i+1}. fact: {f.fact} | expected: {f.answer}' for i,f in enumerate(facts))
        judged=json_object(await chat(context,self.service,'fact_judge',
            FACT_RECOVERY_JUDGE.format(facts=reference,answers=block,k=len(facts)),self.judge_tokens))
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
        return FEEDBACK.format(prev_tokens=round_.tokens,prev=round_.encoding,target=target,issues='\n'.join(issues))


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
        from ..services import MeteredServices
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
