"""Replaceable reader protocol: decoding instructions are explicit experimental inputs."""
from dataclasses import dataclass
import json
from ..core import to_data
from ..planning.common import spec


@dataclass(frozen=True)
class QAPrompt:
    instructions: str = 'Answer using the memory context. If it is insufficient, say you do not know. For a multiple-choice question, return the option label only.'
    legend: str = ''
    spec=spec('reader.prompt','reader_prompt')
    def build(self,question,memory_context):
        prompt=self.instructions+'\n'
        if self.legend:prompt+='DECODE LEGEND\n'+self.legend+'\n'
        if question.as_of is not None:
            prompt+='QUERY TIME\n'+json.dumps(to_data(question.as_of))+'\n'
        prompt+='MEMORY\n'+memory_context.text+'\nQUESTION\n'+'\n'.join(p.text or '' for p in question.parts)
        if question.options:prompt+='\nOPTIONS\n'+json.dumps(to_data(question.options),ensure_ascii=False)
        return prompt


@dataclass(frozen=True)
class ContextFolderPrompt(QAPrompt):
    legend: str = '@YYYY-MM-DD marks the fact date; A -> B marks change or transfer; E: x marks an entity attribute; ~ marks negation; ? marks uncertainty; semicolons and newlines separate facts. Decode compact facts before answering. Preserve names, dates, numbers and relation directions.'
    spec=spec('reader.contextfolder_prompt','reader_prompt')
