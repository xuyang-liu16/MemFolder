"""Real-bank -> compression -> native reader, using explicitly TEST-ONLY vectors.

No model/QA calls, original bank writes, or research-quality claims.
"""
from pathlib import Path
from hashlib import sha256
import argparse
import ast
import asyncio
import json
import logging
import sys

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--input',type=Path,required=True)
parser.add_argument('--format',choices=('mem0','m3'),required=True)
parser.add_argument('--dependency-path',type=Path,action='append',default=[])
parser.add_argument('--output-dir',type=Path,required=True)
args=parser.parse_args()
for directory in args.dependency_path:
    import site
    site.addsitedir(str(directory.resolve()));sys.path.insert(0,str(directory.resolve()))
sys.path.insert(0,str(ROOT/'src'))

from memfolder.core import *
from memfolder.assembly import assemble
from memfolder.compression import ServiceMap, DiagnosticCollector
from memfolder.loading import load_mem0_sqlite,load_m3,LoadOptions
from memfolder.wrappers import verify_materialization,open_qdrant_view,load_m3_view
from memfolder.wrappers.io import file_digest

SPACE=EmbeddingSpace(provider='acceptance-test-only',model='synthetic-content-vector',revision='1',dimension=3)
class Encoder:
    def encode(self,texts):return [(float(len(t)),float(sum(map(ord,t))%101),1.) for t in texts]


async def check():
    before=file_digest(args.input)
    library=load_mem0_sqlite(args.input,options=LoadOptions(dataset_id='longmemeval',sample_id='s000')) if args.format=='mem0' else load_m3(args.input,options=LoadOptions(dataset_id='m3-robot'))
    assert len(library.inputs)==1
    source=library.inputs[0]; snapshot=source.initial_snapshot
    writer='qdrant-writer' if args.format=='mem0' else 'm3-json-writer'
    config={'planner':{'plugin':'random-merge'},'operator':{'plugin':'text-operator','parameters':{'writer':{'plugin':'concat-writer'}}},
        'wrapper':{'plugin':args.format+'-wrapper','parameters':{'output_dir':str(args.output_dir.resolve()),
            'codec':{'plugin':args.format+'-codec','parameters':{'space':to_data(SPACE)}},'writer':{'plugin':writer},
            'embedding_provider':{'plugin':'content-embeddings','parameters':{'space':to_data(SPACE)}}}}}
    assembly=assemble(config);diagnostics=DiagnosticCollector()
    run=await assembly.run(source,budgets=(BudgetRequest(unit='nodes',ratio=.5,minimum=1,rounding='ceil'),),
        seed=7,services=ServiceMap({'embeddings':Encoder()}),diagnostics=diagnostics)
    final,native=verify_materialization(args.output_dir,artifact=run.materialized.artifact)
    assert {o for n in final.records for o in n.origins}=={o for n in snapshot.records for o in n.origins}
    protected={n.node_id:n for n in snapshot.records if not n.eligible}
    for node in final.records:
        if node.node_id in protected:
            assert replace_embeddings(node)==replace_embeddings(protected[node.node_id])
    if args.format=='mem0':
        client,collection=open_qdrant_view(args.output_dir)
        try:
            assert client.count(collection,exact=True).count==len(final.records)
            hits=client.query_points(collection,query=list(final.records[0].embeddings[0].values),limit=5).points
            assert hits and all(p.payload['data'] in {n.text for n in final.records} for p in hits)
        finally:client.close()
        reader='actual qdrant-client local reload and dense query'
    else:
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity
        path=ROOT/'build/upstream/m3/mmagent/videograph.py'
        provenance=json.loads((ROOT/'docs/LOADING_SOURCES.json').read_text())['official_sources']['m3']['sources'][0]
        assert file_digest(path)==provenance['sha256']
        tree=ast.parse(path.read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='VideoGraph')
        env={'np':np,'cosine_similarity':cosine_similarity,'logger':logging.getLogger('acceptance')}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),str(path),'exec'),env)
        graph=load_m3_view(args.output_dir,env['VideoGraph'])
        assert len(graph.search_text_nodes([[1.,2.,1.]]))==len(graph.text_nodes)
        assert all(i in graph.nodes for v in graph.text_nodes_by_clip.values() for i in v)
        assert graph.character_mappings==to_data(native.data['character_mappings'])
        reader='pinned official VideoGraph class AST: native search, clip/event indexes and character mappings'
    verify_materialization(args.output_dir,artifact=run.materialized.artifact)
    assert file_digest(args.input)==before
    diagnostics.write_jsonl(args.output_dir/'diagnostics.jsonl')
    report={'status':'passed','format':args.format,'source_sha256':before,'source_records':len(snapshot.records),
        'final_records':len(final.records),'eligible_before':sum(n.eligible for n in snapshot.records),'eligible_after':sum(n.eligible for n in final.records),
        'protected_records':len(protected),'edges_before':len(snapshot.edges),'edges_after':len(final.edges),'reader':reader,
        'content_vectors':'TEST-ONLY deterministic vectors; all text refreshed; media unchanged',
        'operator':'concat wiring test, not scientific compression','source_unchanged':True,'model_calls':0,'benchmark_evaluations':0,
        'diagnostic_events':len(diagnostics.records),'native_manifest_sha256':run.materialized.artifact.sha256,
        'implementation_sha256':{p.relative_to(ROOT).as_posix():file_digest(p) for p in sorted((ROOT/'src').rglob('*.py'))}}
    reportdir=ROOT/'build/wrapper_validation';reportdir.mkdir(exist_ok=True)
    (reportdir/(args.format+'.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='implementation_sha256'}))


def replace_embeddings(node):
    from dataclasses import replace
    return replace(node,embeddings=())


asyncio.run(check())
