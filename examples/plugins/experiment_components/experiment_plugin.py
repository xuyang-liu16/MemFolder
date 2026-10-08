"""Contributor modules using public protocols; no framework/runner imports."""
from dataclasses import dataclass
from memfolder.core import ContentPart,FrozenMap,MetricResult,PluginSpec,ContractError


@dataclass(frozen=True)
class FixtureAnswerer:
    """Synthetic answer only: useful for extension tests, never a QA model."""
    text: str = 'fixture answer'
    spec=PluginSpec(plugin_id='example.fixture_answerer',role='answerer')
    def answer(self,question,memory_context,context):
        return (ContentPart(modality='text',text=self.text),),FrozenMap({'test_only':True,'chat_calls':0})


@dataclass(frozen=True)
class AnswerLength:
    spec=PluginSpec(plugin_id='example.answer_length',role='metric')
    def score(self,case,prediction,context):
        return (MetricResult(name='answer_characters',version='example.v1',value=float(sum(len(p.text or '') for p in prediction.answer)),question_id=case.question_id),)


@dataclass(frozen=True)
class TraceObserver:
    spec=PluginSpec(plugin_id='example.trace_observer',role='observer')
    def open(self,context):object.__setattr__(self,'_state',{'events':0,'verified_public_artifacts':0})
    def on_event(self,event,context):
        self._state['events']+=1
        for ref in event.artifact_refs:
            if not context.artifacts.verify(ref):raise ContractError('Missing published artifact')
            context.artifacts.read_json(ref)
            self._state['verified_public_artifacts']+=1
    def close(self,context):context.reports.write_json('external-observer.json',FrozenMap(self._state))


def answerer_factory(parameters,*,context):
    if set(parameters)-{'text'}:raise ContractError('Unknown answerer parameter')
    return FixtureAnswerer(**dict(parameters))
answerer_factory.spec=FixtureAnswerer.spec

def metric_factory(parameters,*,context):
    if parameters:raise ContractError('AnswerLength has no parameters')
    return AnswerLength()
metric_factory.spec=AnswerLength.spec

def observer_factory(parameters,*,context):
    if parameters:raise ContractError('TraceObserver has no parameters')
    return TraceObserver()
observer_factory.spec=TraceObserver.spec
