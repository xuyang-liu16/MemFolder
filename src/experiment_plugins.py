"""Application-owned stage catalog; contributed stages use the same entry points."""
from dataclasses import fields
from .core.values import require
from .plugins import PluginRequest
from .method_plugins import Factory
from .benchmarks.raw import LoCoMoLoader,LongMemEvalLoader,PersonaMemLoader
from .benchmarks.m3 import M3BenchmarkLoader
from .benchmarks.composite import CompositeDatasetLoader
from .initialization import HistoryInitializer,SummaryInitializer,BankInitializer
from .evaluation import retrieval as rt,reader as rd,metrics as mt
from .evaluation.evaluator import MetricEvaluator,ProtocolEvaluator
from .evaluation.official import PersonaMemAccuracy
from .observation import EventReportObserver,RegexRedactor
from .services import CompatibleHTTP,CachedService,TiktokenCounter
from .lingua_service import LLMLingua2Service
from .lingua_historical import HistoricalLLMLingua2Service
from .planning.grounding import ChatGroundingFeatures
from .evaluation.native import QdrantRetriever,M3NativeRetriever,SDKRetriever
from .evaluation.prompts import QAPrompt,ContextFolderPrompt


class StageFactory(Factory):
    def __init__(self,cls,*,roles=None,paths=(),lists=None,maps=None):
        super().__init__(cls,roles=roles);self.paths=paths;self.lists=lists or {};self.maps=maps or {}
    def __call__(self,parameters,*,context):
        values=dict(parameters)
        for key in self.paths:
            if key in values:values[key]=context.path(values[key])
        for key,role in self.lists.items():
            if key in values:values[key]=tuple(context.registry.create(PluginRequest.from_mapping(v),role=role,context=context,available=context.available).instance for v in values[key])
        for key,role in self.maps.items():
            if key in values:values[key]=tuple((k,context.registry.create(PluginRequest.from_mapping(v),role=role,context=context,available=context.available).instance) for k,v in values[key].items())
        for key in ('sample_ids','question_ids','relations','patterns'):
            if key in values:
                require(isinstance(values[key],(tuple,list)) and all(type(v) is str for v in values[key]),'Expected string list')
                values[key]=tuple(values[key])
        return super().__call__(values,context=context)


def register_experiment_plugins(registry):
    factories={
        'locomo-dataset':StageFactory(LoCoMoLoader,paths=('path',)),
        'longmemeval-dataset':StageFactory(LongMemEvalLoader,paths=('path',)),
        'personamem-dataset':StageFactory(PersonaMemLoader,paths=('path','contexts_path')),
        'm3-dataset':StageFactory(M3BenchmarkLoader,paths=('path',),maps={'memory_loaders':'memory_loader'}),
        'composite-dataset':StageFactory(CompositeDatasetLoader,lists={'loaders':'data_loader'}),
        'history-initializer':StageFactory(HistoryInitializer),
        'summary-initializer':StageFactory(SummaryInitializer,roles={'chunker':'initializer'}),
        'bank-initializer':StageFactory(BankInitializer,roles={'fallback':'initializer'},maps={'loaders':'memory_loader'}),
        'lexical-retriever':StageFactory(rt.LexicalRetriever),'dense-retriever':StageFactory(rt.DenseRetriever),
        'qdrant-retriever':StageFactory(QdrantRetriever),'m3-native-retriever':StageFactory(M3NativeRetriever),'sdk-retriever':StageFactory(SDKRetriever),
        'graph-retriever':StageFactory(rt.GraphExpansion,roles={'retriever':'retriever'}),
        'time-decay-retriever':StageFactory(rt.TimeDecayRetriever,roles={'retriever':'retriever'}),
        'context-builder':StageFactory(rd.ContextBuilder),'chat-answerer':StageFactory(rd.ChatAnswerer,roles={'prompt_builder':'reader_prompt'}),
        'qa-prompt':StageFactory(QAPrompt),'memforest-qa-prompt':StageFactory(QAPrompt),
        'contextfolder-qa-prompt':StageFactory(ContextFolderPrompt),
        'retrieval-reader':StageFactory(rd.RetrievalReader,roles={'retriever':'retriever','context_builder':'context_builder','answerer':'answerer'}),
        'metric-evaluator':StageFactory(MetricEvaluator,lists={'metrics':'metric'}),
        'protocol-evaluator':StageFactory(ProtocolEvaluator,maps={'routes':'evaluator'},roles={'fallback':'evaluator'}),
        'exact-match':StageFactory(mt.ExactMatch),'token-f1':StageFactory(mt.TokenF1),
        'choice-accuracy':StageFactory(mt.ChoiceAccuracy),'evidence-recall':StageFactory(mt.EvidenceRecall),
        'locomo-f1':StageFactory(mt.LoCoMoF1),'chat-judge':StageFactory(mt.ChatJudge),
        'memforest-judge':StageFactory(mt.ChatJudge),
        'personamem-accuracy':StageFactory(PersonaMemAccuracy),
        'event-report-observer':StageFactory(EventReportObserver),'regex-redactor':StageFactory(RegexRedactor),
        'compatible-http':StageFactory(CompatibleHTTP),'cached-service':StageFactory(CachedService,roles={'provider':'service'},paths=('path',)),
        'tiktoken-counter':StageFactory(TiktokenCounter),'chat-grounding':StageFactory(ChatGroundingFeatures),
        'llmlingua2-service':StageFactory(LLMLingua2Service),
        'llmlingua2-historical-service':StageFactory(HistoricalLLMLingua2Service),
    }
    for name,factory in factories.items():registry.register(name,factory)
