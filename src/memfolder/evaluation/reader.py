"""Labels cannot enter this module: Reader accepts QuestionSet only."""
from dataclasses import dataclass
from ..core import Prediction,ContentPart,FrozenMap,to_data,fingerprint
from ..core.values import require
from ..planning.common import spec,resolve,emit
from ..operators.types import ChatRequest
from .retrieval import LexicalRetriever,visible
from .prompts import QAPrompt


@dataclass(frozen=True)
class ReaderContext:
    text: str
    parts: tuple
    node_ids: tuple


@dataclass(frozen=True)
class ContextBuilder:
    max_characters: int = 32000
    spec=spec('reader.context','context_builder')
    def build(self,question,view,retrieval,context):
        require(self.max_characters>0,'Invalid context budget')
        nodes={n.node_id:n for n in view.snapshot.records};lines=[];parts=[];used=0;included=[]
        for hit in retrieval:
            node=nodes[hit.node_id]
            line='['+node.node_id+'] '+(node.text or '<'+node.kind+' memory>')
            if used+len(line)>self.max_characters:continue
            lines.append(line);parts.extend(node.parts);included.append(node.node_id);used+=len(line)
        return ReaderContext('\n'.join(lines),tuple(parts),tuple(included))


@dataclass(frozen=True)
class ChatAnswerer:
    service: str = 'chat'
    max_tokens: int = 512
    prompt_builder: object = QAPrompt()
    spec=spec('reader.chat_answer','answerer')
    async def answer(self,question,memory_context,context):
        prompt=self.prompt_builder.build(question,memory_context)
        answer=await resolve(context.services.require(self.service).complete(ChatRequest(role='memory_qa',prompt=prompt,max_tokens=self.max_tokens)))
        require(type(answer) is str and bool(answer.strip()),'Reader returned empty/nontext answer')
        return (ContentPart(modality='text',text=answer),),FrozenMap({'chat_calls':1})


@dataclass(frozen=True)
class ContextAnswerer:
    """Deterministic context echo for offline infrastructure tests, not a QA model."""
    spec=spec('reader.context_echo','answerer')
    def answer(self,question,memory_context,context):
        return (ContentPart(modality='text',text=memory_context.text or 'I do not know'),),FrozenMap({'chat_calls':0,'test_only':True})


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
                    {'text':built.text,'parts':to_data(built.parts),'node_ids':built.node_ids},schema_id='memfolder.reader_context')
            prediction=Prediction(question_id=question.question_id,sample=question.sample,answer=tuple(answer),retrieval=found,reader_context=ref,usage=usage)
            predictions.append(prediction)
            emit(context,self.spec.plugin_id,'memfolder.reader.prediction',nodes=[h.node_id for h in found],
                questions=(question.question_id,),question_id=question.question_id,retrieval=to_data(found),answer=to_data(answer),context_fingerprint=fingerprint(built.text))
        return tuple(predictions)
