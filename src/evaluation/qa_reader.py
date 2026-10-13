"""Labels cannot enter this module: Reader accepts QuestionSet only."""

from dataclasses import dataclass
from ..component_runtime import emit, resolve, spec
from ..core import ContentPart, FrozenMap, Prediction, fingerprint, to_data
from ..core.values import require
from ..operators.contracts import ChatRequest
from ..operators.record_operations import timestamp
from ..prompt_protocol import PROTOCOL_ID, prompt_hash, public_question_text, render_qa
from .retrieval import LexicalRetriever, visible


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
    """Configuration alias: identical QA, with no appended legend."""


@dataclass(frozen=True)
class ReaderContext:
    text: str
    parts: tuple
    node_ids: tuple
    speaker_memories: tuple = ()


@dataclass(frozen=True)
class ContextBuilder:
    max_characters: int = 32000
    spec=spec('reader.context','context_builder')
    def build(self,question,view,retrieval,context):
        require(self.max_characters>0,'Invalid context budget')
        nodes={n.node_id:n for n in view.snapshot.records};lines=[];parts=[];used=0;included=[];groups={}
        for hit in retrieval:
            node=nodes[hit.node_id]
            line='['+node.node_id+'] '+(node.text or '<'+node.kind+' memory>')
            if used+len(line)>self.max_characters:continue
            lines.append(line);parts.extend(node.parts);included.append(node.node_id);used+=len(line)
            owner=str(node.native.get('user_id') or node.scope.partition_id)
            groups.setdefault(owner,[]).append(f'{timestamp(node,"latest")}: {node.text or "<"+node.kind+" memory>"}')
        return ReaderContext('\n'.join(lines),tuple(parts),tuple(included),
                             tuple((owner,tuple(memories)) for owner,memories in groups.items()))


@dataclass(frozen=True)
class ChatAnswerer:
    service: str = 'chat'
    max_tokens: int | None = None
    prompt_builder: object = QAPrompt()
    spec=spec('reader.chat_answer','answerer')
    async def answer(self,question,memory_context,context):
        prompt=self.prompt_builder.build(question,memory_context)
        answer=await resolve(context.services.require(self.service).complete(ChatRequest(role='memory_qa',
            prompt=prompt,max_tokens=self.max_tokens,message_role='system',prompt_id=self.prompt_builder.spec.plugin_id)))
        require(type(answer) is str and bool(answer.strip()),'Reader returned empty/nontext answer')
        return (ContentPart(modality='text',text=answer),),FrozenMap({'chat_calls':1,
            'prompt_id':self.prompt_builder.spec.plugin_id,'prompt_sha256':prompt_hash(prompt),
            'protocol_id':getattr(self.prompt_builder,'protocol_id','external')})


@dataclass(frozen=True)
class RetrievalReader:
    retriever: object = LexicalRetriever()
    context_builder: object = ContextBuilder()
    answerer: object = ChatAnswerer()
    require_as_of: bool = True
    spec=spec('reader.retrieval','reader',diagnostics=('memfolder.reader.prediction',))
    async def predict(self,questions,memory,context):
        from ..core import QuestionSet
        require(type(questions) is QuestionSet,'Reader accepts public QuestionSet, never evaluation labels')
        nodes={n.node_id:n for n in memory.snapshot.records};predictions=[]
        for question in questions.questions:
            found=await resolve(self.retriever.retrieve(question,memory,context))
            require(len({h.node_id for h in found})==len(found) and [h.rank for h in found]==list(range(1,len(found)+1)),'Invalid retrieval ranks or duplicates')
            for hit in found:
                require(hit.node_id in nodes and hit.origins==nodes[hit.node_id].origins and hit.backend_id==memory.node_id_map[hit.node_id], 'Retriever returned unrelated memory provenance')
                require(visible(nodes[hit.node_id],question,require_as_of=self.require_as_of),'Retriever escaped query visibility')
            built=await resolve(self.context_builder.build(question,memory,found,context))
            require(set(built.node_ids)<={h.node_id for h in found},'Context builder introduced unretrieved nodes')
            found=tuple(__import__('dataclasses').replace(h,rank=i+1) for i,h in enumerate(h for h in found if h.node_id in built.node_ids))
            answer,usage=await resolve(self.answerer.answer(question,built,context))
            ref=None
            try:store=context.services.require('artifacts')
            except ValueError:store=None
            if store is not None:
                ref=store.put('reader/'+fingerprint((question.sample.identity,question.question_id))[:24]+'.json',
                    {'text':built.text,'parts':to_data(built.parts),'node_ids':built.node_ids,
                     'speaker_memories':getattr(built,'speaker_memories',())},schema_id='memfolder.reader_context')
            prediction=Prediction(question_id=question.question_id,sample=question.sample,answer=tuple(answer),retrieval=found,reader_context=ref,usage=usage)
            predictions.append(prediction)
            emit(context,self.spec.plugin_id,'memfolder.reader.prediction',nodes=[h.node_id for h in found],
                questions=(question.question_id,),question_id=question.question_id,retrieval=to_data(found),answer=to_data(answer),context_fingerprint=fingerprint(built.text))
        return tuple(predictions)
