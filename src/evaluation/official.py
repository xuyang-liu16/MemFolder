"""Deterministic official PersonaMem option parsing; LLM judges use MemForest."""
from dataclasses import dataclass
import re
from ..core.values import require
from ..planning.common import spec
from .metrics import answer_text,result


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
