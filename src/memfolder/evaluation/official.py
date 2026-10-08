"""Use user-supplied, hash-pinned official judge prompts without upstream imports."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import ast
import re
from ..core.values import require
from ..core import FrozenMap
from ..planning.common import spec,resolve
from ..operators.types import ChatRequest
from .metrics import answer_text,golds,result


def source(path,expected):
    path=Path(path);require(path.is_file() and path.stat().st_size<8*1024*1024,'Missing/oversized official prompt source')
    raw=path.read_bytes();require(sha256(raw).hexdigest()==expected,'Official prompt source checksum mismatch')
    return ast.parse(raw.decode('utf-8-sig'))


@dataclass(frozen=True)
class LongMemEvalPrompt:
    path: Path
    sha256: str
    spec=spec('judge_prompt.longmemeval','judge_prompt')
    @property
    def source_paths(self):return (self.path,)
    def build(self,case,prediction):
        tree=source(self.path,self.sha256)
        fn=next((n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='get_anscheck_prompt'),None)
        require(fn is not None,'Official LongMemEval prompt function missing')
        # Only the release's string formatting function, no imports or script body.
        allowed=(ast.FunctionDef,ast.arguments,ast.arg,ast.If,ast.UnaryOp,ast.Not,ast.Compare,ast.In,ast.Eq,
            ast.Name,ast.Load,ast.Store,ast.Constant,ast.List,ast.Assign,ast.Call,ast.Attribute,ast.Return,ast.Raise)
        require(all(isinstance(n,allowed) for n in ast.walk(fn)),'Unsupported official prompt syntax')
        require(all(not isinstance(n,ast.Call) or isinstance(n.func,ast.Attribute) and n.func.attr=='format' for n in ast.walk(fn)),'Unsupported prompt function call')
        scope={'__builtins__':{'NotImplementedError':NotImplementedError}}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(self.path),'exec'),scope)
        return scope['get_anscheck_prompt'](case.ground_truth['question_type'],'\n'.join(p.text or '' for p in case.question),golds(case)[0],answer_text(prediction),bool(case.ground_truth.get('abstention')))


@dataclass(frozen=True)
class M3Prompt:
    path: Path
    sha256: str
    spec=spec('judge_prompt.m3','judge_prompt')
    @property
    def source_paths(self):return (self.path,)
    def build(self,case,prediction):
        tree=source(self.path,self.sha256)
        value=next((n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prompt_agent_verify_answer_referencing' for t in n.targets)),None)
        require(value is not None,'Official M3 prompt constant missing')
        template=ast.literal_eval(value);require(type(template) is str,'Official M3 prompt must be a string')
        return template.format(question='\n'.join(p.text or '' for p in case.question),ground_truth_answer=golds(case)[0],agent_answer=answer_text(prediction))


@dataclass(frozen=True)
class OfficialJudge:
    prompt: object
    service: str = 'judge'
    max_tokens: int = 10
    spec=spec('metric.official_judge','metric')
    async def score(self,case,prediction,context):
        text=self.prompt.build(case,prediction)
        label=await resolve(context.services.require(self.service).complete(ChatRequest(role='qa_judge',prompt=text,max_tokens=self.max_tokens)))
        require(type(label) is str,'Invalid judge response')
        # Keep official release yes-substring parsing; its identity differs from
        # our strict task-aware judge. Model/revision is recorded by service binding.
        version=self.prompt.spec.plugin_id+':'+self.prompt.sha256+':yes-substring.v1'
        return (result(case,'judge_accuracy',version,'yes' in label.lower(),{'chat_calls':1}),)


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
