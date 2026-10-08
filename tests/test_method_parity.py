"""Characterization against selected pure functions in the pinned original sources.

No legacy module imports, database IO, model calls or benchmark evaluation.
These tests are checkout-only; an installed package does not need the archive.
"""
import ast
from collections import defaultdict
from dataclasses import dataclass,replace
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import random
import sys
import types
import unittest
from typing import *

from test_compression import request,sync,CTX,NUMPY
from memfolder.core import *
from memfolder.planning import *
from memfolder.planning.common import Geometry,subset_request

ROOT=Path(__file__).resolve().parents[2]
CATALOG=ROOT/'refactor_review/code_catalog.json'
AVAILABLE=CATALOG.exists() and NUMPY


def reference(source_id,symbols,extra=None):
    """Only explicitly reviewed pure declarations are executed."""
    catalog=json.loads(CATALOG.read_text(encoding='utf-8'))
    path=Path(next(f['local_path'] for f in catalog if f['id']==source_id))
    source=path.read_text(encoding='utf-8-sig');tree=ast.parse(source)
    declarations=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in symbols]
    assert len(declarations)==len(symbols)
    import numpy as np
    module=types.ModuleType('_memfolder_reference_'+fingerprint((source_id,tuple(symbols)))[:12]);sys.modules[module.__name__]=module
    module.__dict__.update(np=np,dataclass=dataclass,defaultdict=defaultdict,math=math,random=random,
        EPSILON=1e-6,WINDOW=50,TOPK=8,NEIGHBOR_K=5,EVENT_PREFIX='event::')
    if extra:module.__dict__.update(extra)
    code=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]+declarations,type_ignores=[])
    exec(compile(ast.fix_missing_locations(code),str(path),'exec'),module.__dict__)
    return module


@unittest.skipUnless(AVAILABLE,'optional dependencies or pinned checkout references unavailable')
class MethodParityTests(unittest.TestCase):
    def test_recordfolder_final_groups_match_standard_release(self):
        class Plan:
            def __init__(self,**kwargs):self.__dict__.update(kwargs)
            def anchors(self):return [g.anchor_node_id for g in self.groups]
            def partition(self):return {i:g.anchor_node_id for g in self.groups for i in g.member_node_ids}
            def check(self,*args):return self
            def check_same_universe(self,*args):return self
        def make_group(scope,anchor,ids):return types.SimpleNamespace(anchor_node_id=anchor,member_node_ids=tuple(sorted(ids)),chains=[])
        density=reference('standard_release:g1s/g1s/steps/s3_anchors.py',
            ['cosine_distance','stable_argmax','delta','density_peaks','baseline_partition'])
        chain=reference('standard_release:g1s/g1s/steps/s4_chaining.py',
            ['ChainingConfig','Candidate','candidate_pairs','signal_variances','fuse','proposed_edges','match_edges','chains_from','host_of','regroup'],
            {'Plan':Plan,'make_group':make_group})
        import numpy as np
        for n,target in [(5,1),(9,4),(17,6)]:
            req=request(n=n,target=target);geometry=Geometry.of(req,req.snapshot.records)
            nodes=req.snapshot.records;distance=density.cosine_distance(geometry.cosine)
            anchors=density.density_peaks(node_ids=geometry.node_ids,distance=distance,target=target)
            pi0=density.baseline_partition(node_ids=geometry.node_ids,distance=distance,anchors=anchors)
            groups=[make_group(None,geometry.node_ids[a],[geometry.node_ids[i] for i in ids]) for a,ids in sorted(pi0.items())]
            base=Plan(groups=groups,method='g1s',sample_id=0,scope_id='s',source_store='',keep_ratio=target/n,
                generator_model='',num_nodes_before=n,config_id='',metadata={})
            features={r.node_id:r.values for r in req.features[1].rows}
            sets={i:set(v['entities']) for i,v in features.items()};frequency=defaultdict(int)
            for s in sets.values():
                for e in s:frequency[e]+=1
            weights={e:math.log(n/c) for e,c in frequency.items()}
            class Grounding:
                def shared_mass(self,a,b):return sum(weights[e] for e in sorted(sets[a]&sets[b]))
                def union_mass(self,a,b):return sum(weights[e] for e in sorted(sets[a]|sets[b]))
                def event_time(self,i,payload):return datetime.fromtimestamp(features[i]['event_time'],tz=timezone.utc)
                def coverage(self,ids):return sum(bool(sets[i]) for i in ids)/len(ids)
            scope=types.SimpleNamespace(node_ids=geometry.node_ids,embeddings=geometry.vectors,
                index_of={i:p for p,i in enumerate(geometry.node_ids)},by_id={i:types.SimpleNamespace(payload={}) for i in geometry.node_ids})
            expected=chain.regroup(base,scope,Grounding())
            actual=sync(RecordFolderPlanner().plan(req,CTX)).plan
            self.assertEqual({g.anchor_node_id:frozenset(g.member_node_ids) for g in expected.groups},
                             {a.output_ids[0]:frozenset(a.member_ids) for a in actual.actions})

    def test_tome_text_round_routes_and_order_match_legacy(self):
        ref=reference('g1s_legacy:code/evaluation/experiments/direct_tome.py',
            ['TomeRoundRoute','normalized_cosine_rows','bsm_route'])
        import numpy as np
        for n,target in [(9,4),(10,7),(17,3)]:
            req=request(n=n,target=target,mode='repeat')
            route=ref.bsm_route(np.asarray([r.vector for r in req.features[0].rows]),min(n-target,n//2))
            expected={req.snapshot.records[b].node_id:[req.snapshot.records[b].node_id] for b in route.destination_positions}
            for a,b in zip(route.selected_source_positions,route.selected_destination_positions):expected[req.snapshot.records[b].node_id].append(req.snapshot.records[a].node_id)
            expected.update({req.snapshot.records[i].node_id:[req.snapshot.records[i].node_id] for i in route.unmerged_source_positions})
            actual=sync(TomeRoundPlanner().plan(req,CTX))
            self.assertEqual({a.output_ids[0]:list(a.member_ids) for a in actual.plan.actions},expected)
            sequence=next(iter(actual.next_state.data['sequences'].values()))
            self.assertEqual(tuple(sequence),tuple(req.snapshot.records[i].node_id for i in route.next_positions))

    def test_random_disjoint_round_matches_PCG64_legacy(self):
        ref=reference('g1s_legacy:code/evaluation/experiments/direct_tome.py',['TomeRoundRoute','random_pair_route'])
        req=request(n=17,target=10,mode='repeat');route=ref.random_pair_route(17,7,req.seed)
        actual=sync(TomeRoundPlanner(random_pairs=True).plan(req,CTX)).plan
        pairs={frozenset(a.member_ids) for a in actual.actions if a.kind=='merge'}
        expected={frozenset((req.snapshot.records[a].node_id,req.snapshot.records[b].node_id)) for a,b in zip(route.selected_source_positions,route.selected_destination_positions)}
        self.assertEqual(pairs,expected)

    def test_m3_tome_pooled_and_average_linkage_match_original(self):
        ref=reference('m3:tools/g1s/plan_baselines.py',['_groups_from_members','tome_clip','memforest_clip'])
        for n,target in [(9,3),(8,5)]:
            req=request(n=n,target=target);geometry=Geometry.of(req,req.snapshot.records)
            nodes=[types.SimpleNamespace(node_id=str(i),vector=geometry.vectors[i]) for i in range(n)]
            for original,component in [(ref.tome_clip,TomePooledGroups()),(ref.memforest_clip,AverageLinkageGroups())]:
                expected={frozenset(int(i) for i in g['member_node_ids']) for g in original(nodes,target)}
                groups=component.partition(subset_request(req,req.snapshot.records),target,CTX)
                actual={frozenset(int(i[1:]) for i in g.member_ids) for g in groups}
                self.assertEqual(actual,expected)

    def test_memforest_joint_clusters_and_MST_pair_match_vendor(self):
        fid='g1s_legacy:external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/MemForest.py'
        ref=reference(fid,['DisjointSet','cosine_similarity','kmeans_labels','build_joint_clusters','best_merge_pair_via_mst'])
        req=request(n=17,target=6);geometry=Geometry.of(req,req.snapshot.records,dtype='float32')
        nodes=[types.SimpleNamespace(point_id=n.node_id,vector=geometry.vectors[i],created_at=float(i)) for i,n in enumerate(req.snapshot.records)]
        expected=ref.build_joint_clusters(nodes,.25,.8,5,42)
        actual=JointClusters(cluster_ratio=.25).partition(subset_request(req,req.snapshot.records),6,CTX)
        self.assertEqual([tuple(n.point_id for n in rows) for _,rows in sorted(expected.items())],[g.member_ids for g in actual])
        i,j=ref.best_merge_pair_via_mst(nodes)
        pair=MstPairRouter().pair(req,req.snapshot.records,CTX)
        self.assertEqual(frozenset(pair.member_ids),frozenset((nodes[i].point_id,nodes[j].point_id)))

    def test_dart_random_and_medoid_selectors_match_archived_adaptations(self):
        path=ROOT/'server_audit/source_snapshot/data/v12_g1s_experiments_20260921/code/g1s_code_package_20260921/code/evaluation/experiments/embedding_information_anchor_selection.py'
        source=path.read_text(encoding='utf-8');tree=ast.parse(source)
        wanted={'DartMedoidPivotAnchorSelector','DartRandomAnchorFarthestSelector','_stable_argbest','_stable_seed'}
        module=types.ModuleType('_memfolder_dart_reference');sys.modules[module.__name__]=module
        import numpy as np,hashlib
        class Base:pass
        module.__dict__.update(np=np,hashlib=hashlib,json=json,math=math,_BaseAnchorSelector=Base,
            _local_result=lambda cid,budget,geometry,selected,*a,**kw: selected)
        declarations=[node for node in tree.body if getattr(node,'name',None) in wanted]
        exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]+declarations,type_ignores=[])),str(path),'exec'),module.__dict__)
        req=request(n=17,target=6);geometry=Geometry.of(req,req.snapshot.records);cos=geometry.cosine
        cost=(1-cos).sum(axis=1);medoid=int(np.argmin(cost));scope=fingerprint(req.snapshot.records[0].scope)
        legacy_geometry=types.SimpleNamespace(members=tuple(range(17)),node_ids=geometry.node_ids,cosine=cos,medoid=medoid)
        problem=types.SimpleNamespace(base_seed=req.seed,scope_id=scope,interaction_router=None)
        config=types.SimpleNamespace(tie_tolerance=1e-12)
        for cls,variant in [(module.DartMedoidPivotAnchorSelector,'medoid_pivot'),(module.DartRandomAnchorFarthestSelector,'random_anchor_farthest')]:
            expected=cls()._select_cluster(problem,0,6,legacy_geometry,config)
            actual=DartSelector(variant=variant).select(subset_request(req,req.snapshot.records),6,CTX).selected_ids
            self.assertEqual(tuple(geometry.node_ids[i] for i in expected),actual)

    def test_streammeco_both_class_selections_match_pinned_upstream(self):
        path=ROOT/'memfolder/build/upstream/streammeco/streammeco.py'
        source=path.read_text(encoding='utf-8');tree=ast.parse(source)
        wanted={'_node_embedding','_assign_rank_weights','_is_equivalence_text_node','classify_text_nodes',
            '_group_first_class_nodes','_adjust_keep_counts','_greedy_farthest_selection','_select_via_spherical_kmeans',
            'compress_first_class_nodes','compress_second_class_nodes'}
        module=types.ModuleType('_memfolder_streammeco_reference');sys.modules[module.__name__]=module
        import numpy as np
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import normalize
        module.__dict__.update(np=np,math=math,defaultdict=defaultdict,KMeans=KMeans,normalize=normalize,
            TEXT_NODE_TYPES={'episodic','semantic'},MEDIA_NODE_TYPES={'img','voice'},
            FIRST_CLASS_CLUSTER_RATIO=.05,FIRST_CLASS_KEEP_RATIO=.7,SECOND_CLASS_KEEP_RATIO=.7)
        declarations=[node for node in tree.body if getattr(node,'name',None) in wanted]
        exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]+declarations,type_ignores=[])),str(path),'exec'),module.__dict__)
        req=request(n=60,target=None,graph=True);vectors={r.node_id:r.vector for r in req.features[0].rows}
        graph=types.SimpleNamespace(nodes={n.node_id:types.SimpleNamespace(type=n.kind,embeddings=[vectors[n.node_id]] if n.node_id in vectors else [],
            metadata={'contents':[n.text]}) for n in req.snapshot.records},text_nodes=[n.node_id for n in req.snapshot.records if n.eligible],
            edges={(e.source_id,e.target_id):e.weight for e in req.snapshot.edges},text_nodes_by_clip={'p':[n.node_id for n in req.snapshot.records if n.eligible]})
        first,second,matrix=module.classify_text_nodes(graph)
        first_kept,_=module.compress_first_class_nodes(graph,first)
        second_kept,_=module.compress_second_class_nodes(graph,second,matrix)
        actual=sync(StreamMeCoPlanner().plan(req,CTX)).plan
        self.assertEqual({a.member_ids[0] for a in actual.actions if a.kind=='keep'},set(first_kept)|set(second_kept))

    def test_contextfolder_triage_and_round_selection_preserve_release_rules(self):
        # Extract pure old Fact/required_facts/Round definitions, not the LLM runner.
        from memfolder.operators import Fact,FactTriage,EncodingRound,ShortestCleanRound
        from dataclasses import field
        ref=reference('standard_release:g1s/g1s/tele/facts.py',['Fact','required_facts'],
            {'WEIGHTS':{'high':3.,'med':2.,'low':1.},'STRICT_BELOW_RATIO':.65})
        cases=[('high',False),('med',False),('low',False),('high',True),('',False)]
        old=[ref.Fact('f','q','a',level,inferable) for level,inferable in cases]
        new=[Fact('f','q','a',level,inferable) for level,inferable in cases]
        self.assertEqual([f.weight for f in old],[f.weight for f in new])
        for ratio in (.6,.65,.8):self.assertEqual(ref.required_facts(old,ratio),set(FactTriage().required(tuple(new),ratio,CTX)))


if __name__=='__main__':unittest.main()
