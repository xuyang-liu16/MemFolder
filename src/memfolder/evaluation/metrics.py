"""Explicit metric versions; deterministic surrogates are not LLM judges."""
from dataclasses import dataclass
from collections import Counter
import re
import string
from ..core import MetricResult,FrozenMap
from ..core.values import require
from ..planning.common import spec,resolve
from ..operators.types import ChatRequest


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
    spec=spec('metric.chat_judge','metric')
    async def score(self,case,prediction,context):
        task=str(case.ground_truth.get('question_type','general'))
        prompt='Judge correctness. Return exactly YES or NO. Require all essential facts, allow equivalent wording.\n'
        if case.ground_truth.get('abstention'):prompt+='This is unanswerable from the available history; a correct response must abstain.\n'
        elif task=='temporal-reasoning':prompt+='Accept equivalent dates or durations.\n'
        elif task=='knowledge-update':prompt+='Use the latest preference or corrected fact.\n'
        elif task=='single-session-preference':prompt+='The response should fit the user preference even if it does not quote it.\n'
        prompt+='TASK '+task+'\nQUESTION '+ '\n'.join(p.text or '' for p in case.question)+'\nGOLD '+ '\n'.join(golds(case))+'\nRESPONSE '+answer_text(prediction)
        label=await resolve(context.services.require(self.service).complete(ChatRequest(role='qa_judge',prompt=prompt,max_tokens=8)))
        require(type(label) is str and label.strip().upper() in ('YES','NO'),'Judge returned an invalid label')
        return (result(case,'judge_accuracy','memfolder-task-aware-judge.v1',label.strip().upper()=='YES',{'task':task,'chat_calls':1}),)
