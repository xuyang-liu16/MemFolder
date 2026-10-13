"""Builtin plugin catalogs and configurable component factories."""

from __future__ import annotations
from .benchmarks.dataset_loaders import (
    CompositeDatasetLoader,
    LoCoMoLoader,
    LongMemEvalLoader,
    M3BenchmarkLoader,
    PersonaMemLoader,
)
from .core.values import require
from .evaluation import metrics as mt, qa_reader as rd, retrieval as rt
from .evaluation.metrics import MetricEvaluator, PersonaMemAccuracy, ProtocolEvaluator
from .evaluation.qa_reader import ContextFolderPrompt, QAPrompt
from .evaluation.retrieval import M3NativeRetriever, QdrantRetriever, SDKRetriever
from .initialization import BankInitializer, HistoryInitializer, SummaryInitializer
from .observation import EventReportObserver, RegexRedactor
from .operators import contextfolder as cf, record_operations as tx
from .operators.llmlingua2 import CurrentRecordRewriteBuilder, LLMLingua2Writer
from .operators.record_operations import MemForestPairWriter, TomeEmbeddingBuilder, TomePairWriter
from .planning import (
    feature_extraction as ft,
    memforest as mf,
    record_selection as bl,
    recordfolder as rf,
    streammeco as sm,
)
from .planning.feature_extraction import ChatGroundingFeatures
from .planning.memforest import AverageLinkageGroups
from .planning.record_selection import CurrentRecordRewritePlanner
from .planning.tome import TemporalTomePlanner, TomePooledGroups, TomeRoundPlanner
from .plugins import Factory, PluginRegistry, PluginRequest
from .services import (
    CachedService,
    CompatibleHTTP,
    TokenBudgetLLMLingua2Service,
    LLMLingua2Service,
    TiktokenCounter,
)


def factories():
    record_roles={'anchors':'anchor_selector','assignment':'group_assigner','candidates':'candidate_generator','scorer':'affinity_scorer',
                  'gate':'gate_policy','matcher':'matcher','hosting':'group_router'}
    context_roles={'fact_planner':'fact_planner','triage':'triage_policy','compiler':'compiler','verifier':'verifier',
                   'feedback':'feedback_builder','selector':'round_selector'}
    return {
        'recordfolder':Factory(rf.RecordFolderPlanner,roles=record_roles),
        'contextfolder':Factory(rf.ContextFolderPlanner,roles=record_roles),
        'density-peaks':Factory(rf.DensityPeakAnchors), 'temporal-candidates':Factory(rf.TemporalCandidates),
        'nearest-anchor-assignment':Factory(rf.NearestAnchorAssignment),
        'fused-affinity':Factory(rf.FusedAffinity),'anchor-gate':Factory(rf.AnchorGate),
        'chain-matcher':Factory(rf.ChainMatcher),'chain-hosting':Factory(rf.ChainHosting),
        'partition-planner':Factory(bl.PartitionPlanner,roles={'partitioner':'partitioner'}),
        'prune-planner':Factory(bl.PrunePlanner,roles={'selector':'anchor_selector'}),
        'random-selector':Factory(bl.RandomSelector),'dart-selector':Factory(bl.DartSelector),
        'random-prune':Factory(bl.PrunePlanner,roles={'selector':'anchor_selector'}),
        'dart':Factory(bl.PrunePlanner,defaults={'selector':{'plugin':'dart-selector'}},roles={'selector':'anchor_selector'}),
        'random-groups':Factory(bl.RandomGroups),
        'random-merge':Factory(bl.PartitionPlanner,roles={'partitioner':'partitioner'}),
        'random-merge-round':Factory(TomeRoundPlanner,defaults={'random_pairs':True}),
        'tome':Factory(TemporalTomePlanner),
        'tome-temporal':Factory(TemporalTomePlanner),
        'tome-bsm':Factory(TomeRoundPlanner),
        'current-record-rewrite':Factory(CurrentRecordRewritePlanner),
        'tome-pooled-groups':Factory(TomePooledGroups),
        'tome-pooled':Factory(bl.PartitionPlanner,defaults={'partitioner':{'plugin':'tome-pooled-groups'}},roles={'partitioner':'partitioner'}),
        'average-linkage-groups':Factory(AverageLinkageGroups),
        'memforest-proxy':Factory(bl.PartitionPlanner,defaults={'partitioner':{'plugin':'average-linkage-groups'}},roles={'partitioner':'partitioner'}),
        'kmeans-clusters':Factory(bl.KmeansClusters),
        'cluster-representatives':Factory(bl.ClusterRepresentatives,roles={'clusterer':'partitioner'}),
        'kmeans-prune':Factory(bl.PrunePlanner,defaults={'selector':{'plugin':'cluster-representatives'}},roles={'selector':'anchor_selector'}),
        'kmeans-merge':Factory(bl.PartitionPlanner,defaults={'partitioner':{'plugin':'kmeans-clusters'}},roles={'partitioner':'partitioner'}),
        'joint-clusters':Factory(mf.JointClusters),'capacity-allocator':Factory(mf.CapacityAllocator),
        'per-cluster-ceil':Factory(mf.PerClusterCeilAllocator),'mst-pair':Factory(mf.MstPairRouter),
        'memforest':Factory(mf.MemForestPlanner,roles={'clusterer':'partitioner','allocator':'budget_allocator','router':'pair_router'}),
        'media-connectivity':Factory(sm.MediaConnectivity),'spherical-coverage':Factory(sm.SphericalCoverage),
        'importance-diversity':Factory(sm.ImportanceDiversity),
        'streammeco':Factory(sm.StreamMeCoPlanner,roles={'classifier':'graph_classifier','first_selector':'graph_selector','second_selector':'graph_selector'}),
        'native-summary':Factory(tx.NativeSummaryWriter),'concat-writer':Factory(tx.ConcatWriter),
        'tome-pair-writer':Factory(TomePairWriter),
        'tome-embedding-builder':Factory(TomeEmbeddingBuilder,roles={'builder':'record_builder'}),
        # Compatibility selector for the ordinary text executor. The common
        # feature-provider lifecycle refreshes semantics before each match.
        'tome-operator':Factory(tx.TextOperator,
            roles={'writer':'text_writer','record_builder':'record_builder','member_resolver':'member_resolver'}),
        'record-builder':Factory(tx.ConservativeRecordBuilder),
        'llmlingua2-writer':Factory(LLMLingua2Writer),
        'current-record-builder':Factory(CurrentRecordRewriteBuilder,roles={'builder':'record_builder'}),
        'llmlingua2-operator':Factory(tx.TextOperator,
            defaults={'writer':{'plugin':'llmlingua2-writer'},
                      'record_builder':{'plugin':'current-record-builder'}},
            roles={'writer':'text_writer','record_builder':'record_builder','member_resolver':'member_resolver'}),
        'member-resolver':Factory(tx.ChronologicalMembers),
        'text-operator':Factory(tx.TextOperator,roles={'writer':'text_writer','record_builder':'record_builder','member_resolver':'member_resolver'}),
        'recordfolder-operator':Factory(tx.TextOperator,roles={'writer':'text_writer','record_builder':'record_builder','member_resolver':'member_resolver'}),
        'memforest-operator':Factory(tx.TextOperator,defaults={'writer':{'plugin':'memforest-pair-writer'}},roles={'writer':'text_writer','record_builder':'record_builder','member_resolver':'member_resolver'}),
        'memforest-pair-writer':Factory(MemForestPairWriter),
        'contextfolder-operator':Factory(tx.TextOperator,defaults={'writer':{'plugin':'contextfolder-writer'}},roles={'writer':'text_writer','record_builder':'record_builder','member_resolver':'member_resolver'}),
        'rule-operator':Factory(tx.RuleOperator),
        'contextfolder-writer':Factory(cf.ContextFolderWriter,roles=context_roles),
        'fact-planner':Factory(cf.FactPlanner),'fact-triage':Factory(cf.FactTriage),
        'context-compiler':Factory(cf.ContextCompiler),'blind-verifier':Factory(cf.BlindFactVerifier),
        'repair-feedback':Factory(cf.RepairFeedback),'shortest-clean-round':Factory(cf.ShortestCleanRound),
        'stored-embeddings':Factory(ft.StoredEmbeddings),'semantic-encoder':Factory(ft.SemanticEmbeddingFeatures),
        'current-embeddings':Factory(ft.CurrentEmbeddings),
        'grounding-features':Factory(ft.GroundingFeatures),'event-time-features':Factory(ft.EventTimeFeatures),
    }


def register_method_plugins(registry):
    for name,factory in factories().items():registry.register(name,factory)
    from .operators.action_dispatch import build
    registry.register('operator-dispatch',build)


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
        'llmlingua2-token-budget-service':StageFactory(TokenBudgetLLMLingua2Service),
    }
    for name,factory in factories.items():registry.register(name,factory)


def default_registry(*, discover: bool = True) -> PluginRegistry:
    from .loading.loader_registry import register_memory_loaders
    from .benchmarks.dataset_loaders import build
    registry = PluginRegistry()
    register_memory_loaders(registry)
    registry.register('dataset-jsonl', build)

    register_method_plugins(registry)
    from .wrappers.wrapper_registry import register_wrappers
    register_wrappers(registry)

    register_experiment_plugins(registry)
    if discover:
        registry.discover()
    return registry
