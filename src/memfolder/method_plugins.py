"""Builtin factories. New contributions use entry points/module:factory, not this list."""
from __future__ import annotations
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import get_type_hints
import json
from .core import EmbeddingSpace, FrozenMap, from_data, to_data
from .core.values import require
from .plugins import PluginRequest
from .planning import recordfolder as rf, baselines as bl, features as ft, memforest as mf, streammeco as sm
from .operators import text as tx, contextfolder as cf
from .operators.memforest import MemForestPairWriter
from .planning.temporal_tome import TemporalTomePlanner
from .operators.tome import TomePairWriter, TomeEmbeddingBuilder
from .planning.rewrite import CurrentRecordRewritePlanner
from .operators.llmlingua2 import LLMLingua2Writer, CurrentRecordRewriteBuilder


class Factory:
    """Explicit role map keeps each stage independently configurable."""
    def __init__(self,cls,*,roles=None,defaults=None):
        self.cls=cls;self.spec=cls.spec;self.roles=roles or {};self.defaults=defaults or {}
    def __call__(self,parameters,*,context):
        values={**self.defaults,**parameters};allowed={f.name for f in fields(self.cls)}
        require(set(values)<=allowed,'Unknown component parameter')
        hints=get_type_hints(self.cls)
        for key,value in list(values.items()):
            if key in self.roles:
                request=PluginRequest.from_mapping(value)
                values[key]=context.registry.create(request,role=self.roles[key],context=context,
                                                     available=context.available).instance
            elif key=='space':
                values[key]=from_data(EmbeddingSpace,to_data(value))
            elif key=='grounding' and type(value) is str:
                path=context.path(value);require(path.is_file() and path.stat().st_size<=256*1024*1024,'Missing/oversized grounding file')
                values[key]=FrozenMap(json.loads(path.read_text(encoding='utf-8-sig')))
            elif hints.get(key) is bool:require(type(value) is bool,'Expected boolean parameter: '+key)
            elif hints.get(key) is int:require(type(value) is int,'Expected integer parameter: '+key)
            elif hints.get(key) is float:require(type(value) in (int,float),'Expected numeric parameter: '+key)
            elif hints.get(key) is str:require(type(value) is str,'Expected text parameter: '+key)
            elif hints.get(key) is FrozenMap:values[key]=FrozenMap(value)
            elif key in ('participants','text_kinds','media_kinds'):
                require(isinstance(value,(list,tuple)) and all(type(v) is str for v in value),'Expected list of strings')
                values[key]=tuple(value)
        return self.cls(**values)


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
        'random-merge-round':Factory(bl.TomeRoundPlanner,defaults={'random_pairs':True}),
        'tome':Factory(TemporalTomePlanner),
        'tome-temporal':Factory(TemporalTomePlanner),
        'tome-bsm':Factory(bl.TomeRoundPlanner),
        'current-record-rewrite':Factory(CurrentRecordRewritePlanner),
        'tome-pooled-groups':Factory(bl.TomePooledGroups),
        'tome-pooled':Factory(bl.PartitionPlanner,defaults={'partitioner':{'plugin':'tome-pooled-groups'}},roles={'partitioner':'partitioner'}),
        'average-linkage-groups':Factory(bl.AverageLinkageGroups),
        'memforest-proxy':Factory(bl.PartitionPlanner,defaults={'partitioner':{'plugin':'average-linkage-groups'}},roles={'partitioner':'partitioner'}),
        'kmeans-clusters':Factory(bl.KmeansClusters),
        'cluster-representatives':Factory(bl.ClusterRepresentatives,roles={'clusterer':'partitioner'}),
        'kmeans-prune':Factory(bl.PrunePlanner,defaults={'selector':{'plugin':'cluster-representatives'}},roles={'selector':'anchor_selector'}),
        'kmeans-merge':Factory(bl.PartitionPlanner,defaults={'partitioner':{'plugin':'kmeans-clusters'}},roles={'partitioner':'partitioner'}),
        'joint-clusters':Factory(mf.JointClusters),'capacity-allocator':Factory(mf.CapacityAllocator),
        'legacy-cluster-ceil':Factory(mf.LegacyClusterCeil),'mst-pair':Factory(mf.MstPairRouter),
        'memforest':Factory(mf.MemForestPlanner,roles={'clusterer':'partitioner','allocator':'budget_allocator','router':'pair_router'}),
        'media-connectivity':Factory(sm.MediaConnectivity),'spherical-coverage':Factory(sm.SphericalCoverage),
        'importance-diversity':Factory(sm.ImportanceDiversity),
        'streammeco':Factory(sm.StreamMeCoPlanner,roles={'classifier':'graph_classifier','first_selector':'graph_selector','second_selector':'graph_selector'}),
        'native-summary':Factory(tx.NativeSummaryWriter),'concat-writer':Factory(tx.ConcatWriter),
        'tome-pair-writer':Factory(TomePairWriter),
        'tome-embedding-builder':Factory(TomeEmbeddingBuilder,roles={'builder':'record_builder'}),
        'tome-operator':Factory(tx.TextOperator,
            defaults={'writer':{'plugin':'tome-pair-writer'},
                      'record_builder':{'plugin':'tome-embedding-builder'}},
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
    from .operators.dispatch import build
    registry.register('operator-dispatch',build)
