"""Deterministic metrics, shared MemForest judge and evaluation aggregation."""

from collections import Counter
from dataclasses import dataclass
import re
import string
from ..artifacts import parse_json
from ..component_runtime import resolve, spec
from ..core import EvaluationReport, FrozenMap, MetricResult
from ..core.values import require
from ..operators.contracts import ChatRequest
from ..prompt_protocol import (
    MEMFOREST_JUDGE_PROMPT,
    PROTOCOL_ID,
    prompt_hash,
    question_text,
    render_judge,
)


def answer_text(prediction):return '\n'.join(p.text or '' for p in prediction.answer)


def golds(case):
    value=case.ground_truth.get('answers',case.ground_truth.get('answer'))
    require(value is not None,'Metric requires gold answer')
    return tuple(str(v) for v in value) if isinstance(value,(tuple,list)) else (str(value),)


def normalized(text):return ' '.join(re.sub(r'\b(a|an|the)\b',' ',''.join(c for c in text.casefold() if c not in string.punctuation)).split())


def result(case,name,version,value,details=None):return MetricResult(name=name,version=version,value=float(value),question_id=case.question_id,details=FrozenMap(details or {}))


@dataclass(frozen=True)
class ExactMatch:
    spec=spec('metric.exact_match','metric')
    def score(self,case,prediction,context):return (result(case,'exact_match','normalized-order-sensitive.v1',any(normalized(answer_text(prediction))==normalized(g) for g in golds(case))),)


@dataclass(frozen=True)
class TokenF1:
    spec=spec('metric.token_f1','metric')
    def score(self,case,prediction,context):
        p=normalized(answer_text(prediction)).split();values=[]
        for gold in golds(case):
            g=normalized(gold).split();common=sum((Counter(p)&Counter(g)).values())
            values.append(2*common/(len(p)+len(g)) if p or g else 1.)
        return (result(case,'token_f1','normalized-no-stemming.v1',max(values)),)


@dataclass(frozen=True)
class ChoiceAccuracy:
    spec=spec('metric.choice_accuracy','metric')
    def score(self,case,prediction,context):
        require(bool(case.options),'Choice metric requires public options')
        text=answer_text(prediction).strip();label=text.strip('(). \n').upper()
        # Whole option text is accepted; arbitrary mentions of letters are not.
        if label not in case.options:
            matches=[k for k,v in case.options.items() if normalized(str(v))==normalized(text)]
            label=matches[0] if len(matches)==1 else None
        gold=str(case.ground_truth.get('choice',case.ground_truth.get('answer',''))).strip().upper()
        require(gold in case.options,'Unknown gold choice')
        return (result(case,'choice_accuracy','exact-label-or-option-text.v1',label==gold,{'parsed_choice':label}),)


@dataclass(frozen=True)
class EvidenceRecall:
    spec=spec('metric.evidence_recall','metric')
    def score(self,case,prediction,context):
        if case.ground_truth.get('unresolved_evidence'):
            return (MetricResult(name='evidence_recall',version='origin-set.v2',value=None,status='not_run',question_id=case.question_id,details=FrozenMap({'reason':'unresolved_evidence_labels'})),)
        if not case.evidence:
            return (MetricResult(name='evidence_recall',version='origin-set.v2',value=None,status='not_run',question_id=case.question_id,details=FrozenMap({'reason':'no_evidence_labels'})),)
        retrieved={o for h in prediction.retrieval for o in h.origins}
        return (result(case,'evidence_recall','origin-set.v2',len(retrieved&set(case.evidence))/len(set(case.evidence))),)


@dataclass(frozen=True)
class LoCoMoF1:
    """Pinned official category rules; Porter stemming requires optional nltk."""
    spec=spec('metric.locomo_official','metric')
    def score(self,case,prediction,context):
        from nltk.stem import PorterStemmer
        stem=PorterStemmer().stem
        def norm(s):return ' '.join(re.sub(r'\b(a|an|the|and)\b',' ',''.join(c for c in s.lower().replace(',','') if c not in string.punctuation)).split())
        def f1(p,g):
            p=[stem(w) for w in norm(p).split()];g=[stem(w) for w in norm(g).split()];same=sum((Counter(p)&Counter(g)).values())
            return 2*same/(len(p)+len(g)) if same else 0.
        category=int(case.ground_truth['category']);prediction_text=answer_text(prediction)
        require(category in (1,2,3,4,5),'Unknown LoCoMo category')
        if category==5:value=float(any(t in prediction_text.lower() for t in ('no information available','not mentioned')))
        else:
            gold=golds(case)[0]
            if category==3:gold=gold.split(';')[0].strip()
            if category==1:
                answers=[g.strip() for g in gold.split(',')];parts=[p.strip() for p in prediction_text.split(',')]
                value=sum(max(f1(p,g) for p in parts) for g in answers)/len(answers)
            else:value=f1(prediction_text,gold)
        return (result(case,'locomo_f1','snap-release-porter-category.v1',value,{'category':category}),)


@dataclass(frozen=True)
class ChatJudge:
    service: str = 'judge'
    spec=spec('metric.memforest_judge.v1','metric')
    async def score(self,case,prediction,context):
        if 'choice' in case.ground_truth:
            choice=str(case.ground_truth['choice']).strip('() ').upper()
            require(choice in case.options,'Judge received an unknown gold choice')
            gold=str(case.options[choice])
        else:
            gold='\n'.join(golds(case))
        prompt=render_judge(question_text(case.question,case.options,case.as_of),gold,answer_text(prediction))
        raw=await resolve(context.services.require(self.service).complete(ChatRequest(role='memforest_judge',
            prompt=prompt,response_format='json_object',prompt_id=PROTOCOL_ID+'.judge')))
        try:
            label=parse_json(raw)
        except (ValueError,TypeError):
            require(False,'Judge returned an invalid JSON label')
        require(type(label) is dict and label.get('label') in ('CORRECT','WRONG'),
                'Judge must return a JSON CORRECT/WRONG label')
        version=PROTOCOL_ID+'.judge:'+prompt_hash(MEMFOREST_JUDGE_PROMPT)+':strict-json-label.v1'
        return (result(case,'judge_accuracy',version,label['label']=='CORRECT',
            {'label':label['label'],'chat_calls':1,'protocol_id':PROTOCOL_ID,
             'prompt_id':PROTOCOL_ID+'.judge','prompt_sha256':prompt_hash(prompt)}),)


@dataclass(frozen=True)
class PersonaMemAccuracy:
    """Official option-set/final_answer parsing, kept separate from strict choices."""
    spec=spec('metric.personamem_official','metric')
    def score(self,case,prediction,context):
        require(set(case.options)<={'A','B','C','D'} and bool(case.options),'Official PersonaMem expects A-D choices')
        full=answer_text(prediction);text=full.strip()
        if '<final_answer>' in text:text=text.split('<final_answer>')[-1].strip()
        if text.endswith('</final_answer>'):text=text[:-len('</final_answer>')].strip()
        def options(value):
            found=re.findall(r'\(([a-d])\)',value.lower())
            return set(found if found else re.findall(r'\b([a-d])\b',value.lower()))
        gold=str(case.ground_truth['choice']).lower().strip('() ')
        return (result(case,'choice_accuracy','personamem-release-option-set.v1',options(text)=={gold} or options(full)=={gold}),)


@dataclass(frozen=True)
class MetricEvaluator:
    metrics: tuple = (ExactMatch(),TokenF1(),EvidenceRecall())
    strict: bool = True
    spec=spec('evaluation.metrics','evaluator')
    async def evaluate(self,questions,predictions,context):
        require(len({p.question_id for p in predictions})==len(predictions),'Duplicate predictions')
        require(all(p.sample.identity==questions.sample.identity for p in predictions),'Prediction sample mismatch')
        ids={q.question_id for q in questions.cases};by_id={p.question_id:p for p in predictions}
        require(set(by_id)==ids,'Missing or unexpected predictions')
        measured=[]
        for case in questions.cases:
            for metric in self.metrics:
                try:
                    values=await resolve(metric.score(case,by_id[case.question_id],context))
                    require(all(type(v) is MetricResult and v.question_id==case.question_id for v in values),'Metric escaped question identity')
                    measured.extend(values)
                except Exception:
                    if self.strict:raise
                    measured.append(MetricResult(name=metric.spec.plugin_id,version='plugin-failure.v1',value=None,status='failed',question_id=case.question_id))
        require(len({(m.name,m.version,m.question_id) for m in measured})==len(measured),'Duplicate metric identity')
        return EvaluationReport(sample=questions.sample,protocol_id=questions.protocol_id,predictions=tuple(predictions),metrics=tuple(measured))


def aggregate(reports):
    groups={}
    for report in reports:
        synthetic=any(p.usage.get('test_only',False) for p in report.predictions)
        for m in report.metrics:groups.setdefault((report.protocol_id,m.name,m.version,synthetic),[]).append(m)
    return FrozenMap({'metrics':[{'protocol_id':protocol,'name':name,'version':version,'test_only':synthetic,'mean':sum(v.value for v in values if v.status=='measured')/sum(v.status=='measured' for v in values) if any(v.status=='measured' for v in values) else None,
        'measured':sum(v.status=='measured' for v in values),'not_run':sum(v.status=='not_run' for v in values),'failed':sum(v.status=='failed' for v in values)} for (protocol,name,version,synthetic),values in sorted(groups.items())]})


@dataclass(frozen=True)
class ProtocolEvaluator:
    routes: tuple
    fallback: object | None = None
    spec=spec('evaluation.protocol_router','evaluator')
    async def evaluate(self,questions,predictions,context):
        evaluator=dict(self.routes).get(questions.protocol_id,self.fallback)
        require(evaluator is not None,'No evaluator configured for this protocol')
        return await resolve(evaluator.evaluate(questions,predictions,context))
