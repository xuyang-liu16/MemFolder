"""MemForest benchmark reader protocol, independent of compression method."""
from dataclasses import dataclass
from ..core.values import require
from ..planning.common import spec
from ..prompt_protocol import PROTOCOL_ID, render_qa, public_question_text


@dataclass(frozen=True)
class QAPrompt:
    instructions: str = ''
    legend: str = ''
    protocol_id: str = PROTOCOL_ID
    spec=spec('reader.memforest_prompt.v1','reader_prompt')
    def __post_init__(self):
        require(not self.instructions and not self.legend and self.protocol_id == PROTOCOL_ID,
                'Shared MemForest QA forbids method-specific instructions or decoder legends; use an explicit external protocol plugin for a separate experiment')
    def build(self,question,memory_context):
        groups=getattr(memory_context,'speaker_memories',())
        if not groups:
            groups=(('user',(memory_context.text,) if memory_context.text else ()),('assistant',()))
        return render_qa(public_question_text(question),groups)


@dataclass(frozen=True)
class ContextFolderPrompt(QAPrompt):
    """Legacy configuration alias: identical QA, with no appended legend."""
