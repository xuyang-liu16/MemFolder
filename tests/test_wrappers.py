"""End-to-end wrapper contracts and native readers; all encoders are offline fakes."""
import asyncio
import ast
from dataclasses import replace
from hashlib import sha256
import json
import logging
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid5, NAMESPACE_URL

from memfolder.core import *
from memfolder.assembly import assemble
from memfolder.compression import ServiceMap, DiagnosticCollector, CompressionEngine
from memfolder.loading import Importer, Mem0Adapter, MemOSAdapter, M3Adapter, SourceDocument, LoadOptions, load_mem0, load_m3, load_memos_cube
from memfolder.planning import PartitionPlanner, PrunePlanner
from memfolder.operators import TextOperator, ConcatWriter, RuleOperator
from memfolder.wrappers import *
from memfolder.planning.common import spec
from test_loading import m3_document

ROOT = Path(__file__).resolve().parents[1]
SPACE = EmbeddingSpace(provider='test-only', model='deterministic-content', revision='1', dimension=3)
CTX = AlgorithmContext(services=ServiceMap(), diagnostics=NullDiagnostics())


def sync(value): return asyncio.run(value)


class Encoder:
    def __init__(self): self.texts = []
    async def encode(self, texts):
        self.texts.extend(texts)
        return [(float(len(t)), float(sum(map(ord,t)) % 7), 1.) for t in texts]


def memory(adapter, data, options=None):
    lib = Importer(adapter=adapter, options=options or LoadOptions(dataset_id='test')).load_documents((
        SourceDocument(source_id='fixture', sha256=fingerprint(data), data=data),))
    return lib.inputs[0]


def mem0():
    return memory(Mem0Adapter(), {'points':[{'id':str(uuid5(NAMESPACE_URL,'p'+str(i))),
        'payload':{'data':t,'user_id':'alice','custom':{'value':i}},'vector':[1.,float(i),.5]}
        for i,t in enumerate(('Alice likes tea.', 'Alice drinks green tea.', 'Alice runs daily.'))]})


def memos(tree=False):
    ids = [str(uuid5(NAMESPACE_URL,'m'+str(i))) for i in range(3)]
    rows = [{'id':ids[i],'memory':t,'metadata':{'cube_id':'cube-A','status':'activated','embedding':[1.,float(i),.5],
        'children_ids':ids[i+1:i+2]}} for i,t in enumerate(('Alice likes tea.', 'Alice drinks tea.', 'Alice runs daily.'))]
    data = {'nodes':rows,'edges':[{'source':ids[0],'target':ids[1],'type':'PARENT','weight':2.}]} if tree else rows
    return memory(MemOSAdapter(), data, LoadOptions(dataset_id='test', namespace='cube-A'))


def m3(*, media_storage=False):
    data = m3_document(); data['video_id'] = 'test-video'
    data['nodes'].append({'id':5,'type':'episodic','metadata':{'contents':['Alice closes the door.'],'timestamp':0},'embeddings':[[.1,.9]]})
    data['text_nodes'].append(5); data['text_nodes_by_clip']['0'].append(5); data['event_sequence_by_clip']['0'].append(5)
    data['next_node_id'] = 6
    data['edges'] += [{'source':0,'target':5,'weight':3.}, {'source':5,'target':0,'weight':3.}]
    if media_storage:
        data['nodes'][0]['embeddings_storage']=[{'encoding':'ndarray','dtype':'float32','shape':[2],'values':v} for v in data['nodes'][0]['embeddings']]
        data['nodes'][0]['metadata']['opaque_bytes']={'encoding':'base64','python_type':'bytes','data':'YWJj'}
    return memory(M3Adapter(),data)


def wrapper(codec, writer, output, *, embeddings=False, copier=None):
    return FrameworkWrapper(codec,writer,output, embedding_provider=ChangedTextEmbeddings(SPACE) if embeddings else None, asset_copier=copier)


def compress(source, wrapper, *, merge=True, ratio=.5, diagnostics=None):
    engine = CompressionEngine(PartitionPlanner() if merge else PrunePlanner(), TextOperator(ConcatWriter()) if merge else RuleOperator())
    return sync(run_wrapped(engine,wrapper,source,budgets=(BudgetRequest(unit='nodes',ratio=ratio,minimum=1,rounding='ceil'),),
        services=ServiceMap({'embeddings':Encoder()}),diagnostics=diagnostics))


class WrapperTests(unittest.TestCase):
    def test_mem0_merge_refresh_and_roundtrip(self):
        source = mem0(); before = dumps(source)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)/'output'; diagnostics = DiagnosticCollector()
            run = compress(source,wrapper(Mem0Codec(SPACE),Mem0PointsWriter(),out,embeddings=True),diagnostics=diagnostics)
            snapshot,native = verify_materialization(out,artifact=run.materialized.artifact)
            self.assertEqual(len(snapshot.records),2)
            points = native.data['points']
            for node in snapshot.records:
                point = next(p for p in points if p['id'] == native.node_id_map[node.node_id])
                self.assertEqual(tuple(point['vector']),node.embeddings[0].values)
                self.assertEqual(point['payload']['data'],node.text)
            loaded = load_mem0(out/'mem0.points.json')
            self.assertEqual(sorted(n.text for n in loaded.inputs[0].initial_snapshot.records), sorted(n.text for n in snapshot.records))
            self.assertEqual(dumps(source),before)
            self.assertTrue({'memfolder.wrapper.export','memfolder.wrapper.edges','memfolder.wrapper.embeddings','memfolder.wrapper.materialized'} <= {d.schema for d in diagnostics.records})

    def test_mem0_prune_preserves_uuid_and_payload(self):
        source=mem0()
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';run=compress(source,wrapper(Mem0Codec(),Mem0PointsWriter(),out),merge=False)
            _,native=verify_materialization(out)
            originals={n.native['id']:n.native['record'] for n in source.initial_snapshot.records}
            for point in native.data['points']:
                self.assertEqual(point['payload'],originals[point['id']]['payload'])
                self.assertEqual(point['vector'],originals[point['id']]['vector'])

    def test_mem0_uint64_id_is_preserved(self):
        source=memory(Mem0Adapter(),{'points':[{'id':42,'payload':{'data':'tea','user_id':'alice'},'vector':[1.]}]})
        native=Mem0Codec().encode(source.initial_snapshot,NativeArchive(source.initial_snapshot),CTX)
        self.assertEqual(native.data['points'][0]['id'],'42')

    def test_mem0_export_payload_normalizes_data_and_owner_for_native_filters(self):
        source=memory(Mem0Adapter(),{'results':[{'id':42,'memory':'tea','metadata':{'user_id':'alice'},'embedding':[1.,2.]}]})
        native=Mem0Codec().encode(source.initial_snapshot,NativeArchive(source.initial_snapshot),CTX)
        payload=native.data['points'][0]['payload']
        self.assertEqual(payload['data'],'tea');self.assertEqual(payload['user_id'],'alice');self.assertNotIn('memory',payload)

    def test_mem0_expiration_normalizes_date_and_rejects_precision_loss(self):
        from datetime import datetime,timezone
        source=mem0();snapshot=source.initial_snapshot;node=snapshot.records[0]
        boundary=datetime(2026,10,10,tzinfo=timezone.utc).timestamp()
        snapshot=replace(snapshot,records=(replace(node,expires_at=TimePoint(value=boundary,clock='unix_seconds')), *snapshot.records[1:]))
        native=Mem0Codec().encode(snapshot,NativeArchive(source.initial_snapshot),CTX)
        point=next(p for p in native.data['points'] if p['id']==node.native['id'])
        self.assertEqual(point['payload']['expiration_date'],'2026-10-10')
        snapshot=replace(snapshot,records=(replace(snapshot.records[0],expires_at=TimePoint(value=boundary+1,clock='unix_seconds')), *snapshot.records[1:]))
        with self.assertRaisesRegex(ContractError,'sub-day'):Mem0Codec().encode(snapshot,NativeArchive(source.initial_snapshot),CTX)

    def test_missing_content_embedding_fails_before_output_creation(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out'
            with self.assertRaisesRegex(ContractError,'refreshed content embedding'):
                compress(mem0(),wrapper(Mem0Codec(),Mem0PointsWriter(),out))
            self.assertFalse(out.exists())

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td); sentinel=out/'original';sentinel.write_text('unchanged')
            with self.assertRaisesRegex(ContractError,'already exists'):
                compress(mem0(),wrapper(Mem0Codec(),Mem0PointsWriter(),out),merge=False)
            self.assertEqual(sentinel.read_text(),'unchanged')

    def test_failed_writer_has_no_completion_manifest(self):
        class Broken:
            spec=Mem0PointsWriter.spec
            def write(self,*args): raise RuntimeError('write failed')
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out'
            with self.assertRaises(RuntimeError): compress(mem0(),wrapper(Mem0Codec(),Broken(),out),merge=False)
            self.assertTrue((out/'failure.json').exists());self.assertFalse((out/'manifest.json').exists())
            with self.assertRaises(ContractError):verify_materialization(out)

    def test_checksum_detects_native_file_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';compress(mem0(),wrapper(Mem0Codec(),Mem0PointsWriter(),out),merge=False)
            (out/'mem0.points.json').write_text('{}')
            with self.assertRaisesRegex(ContractError,'checksum'):verify_materialization(out)

    def test_wrong_encoder_dimension_is_rejected(self):
        class Bad:
            def encode(self,texts):return [[1.] for t in texts]
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';w=wrapper(Mem0Codec(SPACE),Mem0PointsWriter(),out,embeddings=True).bind(mem0().initial_snapshot)
            with self.assertRaisesRegex(ContractError,'dimension'):
                sync(w.materialize(w.archive.snapshot,AlgorithmContext(services=ServiceMap({'embeddings':Bad()}),diagnostics=NullDiagnostics())))
            self.assertFalse(out.exists())

    def test_refresh_does_not_reuse_unbound_source_vectors_by_default(self):
        source=mem0();encoder=Encoder()
        after=sync(ChangedTextEmbeddings(SPACE).refresh(source.initial_snapshot,AlgorithmContext(services=ServiceMap({'embeddings':encoder}),diagnostics=NullDiagnostics())))
        self.assertEqual(len(encoder.texts),3);validate_embedding_refresh(source.initial_snapshot,after)

    def test_declared_native_vector_reuse_needs_no_service(self):
        source=mem0()
        after=sync(ChangedTextEmbeddings(SPACE,source_slot='default',preserve_native=True).refresh(source.initial_snapshot,CTX))
        self.assertEqual(after,source.initial_snapshot)

    def test_mem0_named_vectors_roundtrip_without_silent_slot_loss(self):
        data={'points':[{'id':42,'payload':{'data':'tea','user_id':'alice'},'vector':{'dense':[1.,2.],'sparse':{'indices':[1],'values':[.5]}}}]}
        source=memory(Mem0Adapter(),data)
        native=Mem0Codec().encode(source.initial_snapshot,NativeArchive(source.initial_snapshot),CTX)
        self.assertEqual(to_data(native.data['points'][0]['vector']),data['points'][0]['vector'])
        after=sync(ChangedTextEmbeddings(SPACE).refresh(source.initial_snapshot,AlgorithmContext(services=ServiceMap({'embeddings':Encoder()}),diagnostics=NullDiagnostics())))
        with self.assertRaisesRegex(ContractError,'slot-aware'):Mem0Codec(SPACE).encode(after,NativeArchive(source.initial_snapshot),CTX)

    def test_memos_merge_native_fields_and_vectors(self):
        source=memos()
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';run=compress(source,wrapper(MemOSCodec(space=SPACE),MemOSWriter(),out,embeddings=True))
            _,native=verify_materialization(out)
            for row in native.data['nodes']:
                self.assertEqual(set(row),{'id','memory','metadata'})
                self.assertEqual(len(row['metadata']['embedding']),3)
                self.assertNotIn(row['id'],row['metadata'].get('children_ids',()))
            loaded=memory(MemOSAdapter(),to_data(native.data['nodes']),LoadOptions(namespace='cube-A'))
            self.assertEqual(len(loaded.initial_snapshot.records),2)

    def test_memos_tree_edges_redirect_without_dangling(self):
        source=memos(tree=True)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';compress(source,wrapper(MemOSCodec(backend='tree_text',space=SPACE),MemOSWriter(),out,embeddings=True))
            _,native=verify_materialization(out);ids={n['id'] for n in native.data['nodes']}
            self.assertTrue(all(e['source'] in ids and e['target'] in ids for e in native.data['edges']))
            data=json.loads((out/'textual_memory.json').read_text())
            self.assertEqual(set(data),{'nodes','edges'})

    def test_memos_auto_backend_survives_pruning_all_edges(self):
        source=memos(tree=True);snapshot=replace(source.initial_snapshot,records=(source.initial_snapshot.records[2],),edges=())
        native=MemOSCodec().encode(snapshot,NativeArchive(source.initial_snapshot),CTX)
        self.assertEqual(native.data['backend'],'tree_text')

    def test_memos_multiple_declared_source_slots_are_not_discarded_on_keep(self):
        data=[{'id':str(uuid5(NAMESPACE_URL,'multi')),'memory':'tea','metadata':{'cube_id':'cube-A',
            'embedding':[1.,2.,3.],'embedding_1024':[4.,5.,6.]}}]
        source=memory(MemOSAdapter(),data,LoadOptions(namespace='cube-A',embedding_spaces={'embedding':SPACE}))
        native=MemOSCodec(space=SPACE).encode(source.initial_snapshot,NativeArchive(source.initial_snapshot),CTX)
        self.assertEqual(native.data['nodes'][0]['metadata']['embedding_1024'],(4.,5.,6.))

    def test_memos_multiple_slots_reject_implicit_refresh_slot_loss(self):
        data=[{'id':str(uuid5(NAMESPACE_URL,'multi')),'memory':'tea','metadata':{'cube_id':'cube-A',
            'embedding':[1.,2.,3.],'embedding_1024':[4.,5.,6.]}}]
        source=memory(MemOSAdapter(),data,LoadOptions(namespace='cube-A'))
        after=sync(ChangedTextEmbeddings(SPACE).refresh(source.initial_snapshot,AlgorithmContext(services=ServiceMap({'embeddings':Encoder()}),diagnostics=NullDiagnostics())))
        with self.assertRaisesRegex(ContractError,'slot-aware'):MemOSCodec(space=SPACE).encode(after,NativeArchive(source.initial_snapshot),CTX)

    def test_memos_opaque_assets_are_copied_and_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'source';root.mkdir();(root/'activation_memory.pickle').write_bytes(b'opaque-do-not-unpickle')
            rows=to_data(memos().initial_snapshot.records[0].native['record'])
            (root/'textual_memory.json').write_text(json.dumps([rows]))
            (root/'config.json').write_text(json.dumps({'cube_id':'cube-A','text_mem':{'backend':'naive_text','config':{'memory_filename':'textual_memory.json'}},'act_mem':{'backend':'kv_cache','config':{'memory_filename':'activation_memory.pickle'}}}))
            source=load_memos_cube(root).inputs[0];out=Path(td)/'output'
            run=compress(source,wrapper(MemOSCodec(),MemOSWriter(),out,copier=VerifiedAssetCopier(root)),merge=False,ratio=1.)
            self.assertEqual((out/'activation_memory.pickle').read_bytes(),b'opaque-do-not-unpickle')
            self.assertEqual(len(run.snapshot.records),2)
            self.assertIn('act_mem',json.loads((out/'memfolder.memos.components.json').read_text()))
            verify_materialization(out)

    def test_missing_asset_copier_fails_before_output(self):
        source=mem0();ref=ArtifactRef(artifact_id='a',path='a.bin',sha256='a'*64,media_type='application/octet-stream',schema_id='asset')
        snapshot=replace(source.initial_snapshot,assets=(ref,))
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';w=wrapper(Mem0Codec(),Mem0PointsWriter(),out).bind(snapshot)
            with self.assertRaisesRegex(ContractError,'asset root'):sync(w.materialize(snapshot,CTX))
            self.assertFalse(out.exists())

    def test_m3_merge_rebuilds_indexes_and_protects_identities(self):
        source=m3();original=source.initial_snapshot
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';run=compress(source,wrapper(M3Codec(space=SPACE),M3JsonWriter(),out,embeddings=True))
            _,native=verify_materialization(out);data=to_data(native.data)
            decoded=memory(M3Adapter(),data)
            self.assertEqual(len(decoded.initial_snapshot.records),len(run.snapshot.records))
            self.assertEqual(data['character_mappings'],m3_document()['character_mappings'])
            media={str(n['id']):n for n in data['nodes'] if n['type'] in ('img','voice')}
            for n in original.records:
                if n.kind in ('img','voice'):self.assertEqual(media[n.native['id']]['metadata'],to_data(n.native['record']['metadata']))
            for n in data['nodes']:
                if n['type'] in ('episodic','semantic'):self.assertEqual(len(n['embeddings']),1)
            self.assertEqual(data['next_node_id'],max(n['id'] for n in data['nodes'])+1)

    def test_m3_prune_preserves_media_and_surviving_edges(self):
        source=m3()
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';compress(source,wrapper(M3Codec(),M3JsonWriter(),out),merge=False)
            _,native=verify_materialization(out)
            self.assertTrue({0,1,2}<={n['id'] for n in native.data['nodes']})
            memory(M3Adapter(),to_data(native.data))

    def test_bound_sessions_have_independent_archives(self):
        w=wrapper(Mem0Codec(),Mem0PointsWriter(),Path('unused'));a=w.bind(mem0().initial_snapshot);b=w.bind(memos().initial_snapshot)
        self.assertIsNone(w.archive);self.assertNotEqual(a.archive.snapshot,b.archive.snapshot)
        with self.assertRaisesRegex(ContractError,'another source'):a.export(memos(),CTX)

    def test_native_package_wire_roundtrip(self):
        source=mem0();native=Mem0Codec().encode(source.initial_snapshot,NativeArchive(source.initial_snapshot),CTX)
        self.assertEqual(loads(dumps(native)),native)
        with self.assertRaises(ContractError):replace(native,node_id_map=FrozenMap({k:'one' for k in native.node_id_map}))

    def test_assembly_config_composes_wrapper_subplugins(self):
        with tempfile.TemporaryDirectory() as td:
            config={'planner':{'plugin':'random-merge'},'operator':{'plugin':'text-operator','parameters':{'writer':{'plugin':'concat-writer'}}},
                'wrapper':{'plugin':'mem0-wrapper','parameters':{'output_dir':'out','codec':{'plugin':'mem0-codec','parameters':{'space':to_data(SPACE)}},
                    'embedding_provider':{'plugin':'content-embeddings','parameters':{'space':to_data(SPACE)}}}}}
            assembly=assemble(config,base_path=td)
            run=sync(assembly.run(mem0(),budgets=(BudgetRequest(unit='nodes',limit=2),),services=ServiceMap({'embeddings':Encoder()})))
            self.assertEqual(run.materialized.framework_id,'mem0');self.assertTrue((Path(td)/'out/manifest.json').exists())
            self.assertTrue({'wrapper','native_codec','native_writer','embedding_provider','graph_projector'}<={b.role for b in assembly.bindings})

    def test_external_framework_codec_requires_no_engine_changes(self):
        class External:
            spec=spec('test.external_codec','native_codec');framework_id='research-store'
            async def encode(self,snapshot,archive,context):
                ids={n.node_id:str(i) for i,n in enumerate(snapshot.records)}
                return NativePackage(framework_id=self.framework_id,format_id='research-store.v1',snapshot_fingerprint=snapshot.fingerprint,
                    node_id_map=FrozenMap(ids),data=FrozenMap({'texts':[n.text for n in snapshot.records]}),lineage=FrozenMap({n.node_id:{} for n in snapshot.records}))
        class Writer:
            spec=spec('test.external_writer','native_writer');reader_capabilities=('research-store.read',)
            async def write(self,native,directory,context):
                from memfolder.wrappers.io import write_json
                return (write_json(directory,'research.json',native.data),)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';run=compress(mem0(),wrapper(External(),Writer(),out))
            self.assertEqual(run.materialized.framework_id,'research-store');verify_materialization(out)

    def test_self_edges_are_preserved_on_noop_projection(self):
        source=mem0();snapshot=source.initial_snapshot;node=snapshot.records[0]
        edge=GraphEdge(edge_id='self',source_id=node.node_id,target_id=node.node_id,relation='self')
        snapshot=replace(snapshot,edges=(edge,))
        request=PlanningRequest(run_id='noop',snapshot=snapshot,budgets=(resolve_budget(snapshot,BudgetRequest(unit='nodes',ratio=1.)),))
        run=sync(CompressionEngine(PrunePlanner(),RuleOperator()).run(request,projector=RedirectEdges()))
        self.assertEqual(run.snapshot.edges,(edge,))

    def test_m3_parallel_redirect_uses_max_weight(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';compress(m3(),wrapper(M3Codec(space=SPACE),M3JsonWriter(),out,embeddings=True))
            _,native=verify_materialization(out)
            media_edges=[e for e in native.data['edges'] if e['source']==0]
            self.assertEqual(len(media_edges),1);self.assertEqual(media_edges[0]['weight'],3.)

    def test_repeated_output_keeps_complete_first_result(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';w=wrapper(Mem0Codec(),Mem0PointsWriter(),out)
            first=compress(mem0(),w,merge=False);before=(out/'manifest.json').read_bytes()
            with self.assertRaises(ContractError):compress(mem0(),w,merge=False)
            self.assertEqual((out/'manifest.json').read_bytes(),before);verify_materialization(out,artifact=first.materialized.artifact)

    def test_history_only_memory_input_requires_loader(self):
        source=replace(mem0(),initial_snapshot=None)
        with self.assertRaisesRegex(ContractError,'Load a canonical'):wrapper(Mem0Codec(),Mem0PointsWriter(),Path('unused')).export(source,CTX)

    def test_m3_native_reader_rejects_ragged_text_vectors(self):
        class Graph:
            class Node:pass
        source=m3();native=M3Codec().encode(source.initial_snapshot,NativeArchive(source.initial_snapshot),CTX)
        with self.assertRaisesRegex(ContractError,'uniform vector shapes'):hydrate_m3(native.data,Graph)

    def test_asset_checksum_mismatch_never_publishes_output(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'source';root.mkdir();(root/'a.bin').write_bytes(b'changed')
            ref=ArtifactRef(artifact_id='a',path='a.bin',sha256='a'*64,media_type='application/octet-stream',schema_id='asset')
            snapshot=replace(mem0().initial_snapshot,assets=(ref,));out=Path(td)/'out'
            with self.assertRaisesRegex(ContractError,'changed'):
                sync(wrapper(Mem0Codec(),Mem0PointsWriter(),out,copier=VerifiedAssetCopier(root)).bind(snapshot).materialize(snapshot,CTX))
            self.assertFalse((out/'manifest.json').exists());self.assertTrue((out/'failure.json').exists())


def optional_dependencies():
    try:
        import numpy as np
        import pydantic, qdrant_client
        return hasattr(np,'array') and hasattr(pydantic,'field_validator')
    except ImportError:return False


def upstream_class(path, name, env):
    """Execute only the pinned class AST; skip SDK imports/LLM/config side effects."""
    if not path.is_file():
        raise unittest.SkipTest('Optional pinned reference missing; run tools/fetch_test_sources.py')
    source=path.read_text(encoding='utf-8');tree=ast.parse(source)
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),env)
    return env[name]


@unittest.skipUnless(optional_dependencies(),'Isolated native SDK dependencies required')
class NativeReaderTests(unittest.TestCase):
    def test_real_qdrant_reload_filter_and_search(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';run=compress(mem0(),wrapper(Mem0Codec(SPACE),QdrantWriter(dimension=3),out,embeddings=True))
            client,collection=open_qdrant_view(out)
            try:
                from qdrant_client import models
                points,_=client.scroll(collection,with_vectors=True,limit=10)
                self.assertEqual(len(points),2)
                result=client.query_points(collection,query=list(run.snapshot.records[0].embeddings[0].values),limit=2,
                    query_filter=models.Filter(must=[models.FieldCondition(key='user_id',match=models.MatchValue(value='alice'))])).points
                self.assertEqual(len(result),2)
                self.assertTrue(all(p.payload['data'] in {n.text for n in run.snapshot.records} for p in result))
            finally:client.close()

    def test_actual_memos_model_and_naive_reader_load_search(self):
        if not (ROOT/'build/upstream/memos/src/memos/memories/textual/item.py').is_file():
            self.skipTest('Optional pinned reference missing; run tools/fetch_test_sources.py')
        import runpy, os
        from datetime import datetime
        env=runpy.run_path(str(ROOT/'build/upstream/memos/src/memos/memories/textual/item.py'))
        env.update({'BaseTextMemory':object,'NaiveTextMemoryConfig':object,'MessageList':list,'Any':object,
            'os':os,'json':json,'datetime':datetime,'logger':logging.getLogger('test')})
        cls=upstream_class(ROOT/'build/upstream/memos/src/memos/memories/textual/naive.py','NaiveTextMemory',env)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';compress(memos(),wrapper(MemOSCodec(),MemOSWriter(),out))
            native=cls.__new__(cls);native.config=SimpleNamespace(memory_filename='textual_memory.json');native.memories=[]
            load_memos_view(out,native)
            self.assertEqual(len(native.get_all()),2)
            self.assertTrue(native.search('Alice tea',1)[0].memory)
            with self.assertRaisesRegex(ContractError,'empty'):load_memos_view(out,native)

    def test_actual_m3_reader_search_and_graph_traversal(self):
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity
        env={'np':np,'cosine_similarity':cosine_similarity,'logger':logging.getLogger('test')}
        cls=upstream_class(ROOT/'build/upstream/m3/mmagent/videograph.py','VideoGraph',env)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';run=compress(m3(),wrapper(M3Codec(space=SPACE),M3JsonWriter(),out,embeddings=True))
            graph=load_m3_view(out,cls)
            results=graph.search_text_nodes([[1.,2.,1.]])
            self.assertEqual({i for i,score in results},set(graph.text_nodes))
            self.assertTrue(all(i in graph.nodes for i in graph.get_connected_nodes(0)))
            self.assertTrue(all(isinstance(i,int) for i in graph.text_nodes_by_clip))
            self.assertEqual(graph.reverse_character_mappings,{'face_0':'character_0','voice_1':'character_0'})

    def test_actual_m3_pickle_restricted_readback_preserves_ndarray(self):
        import sys, types
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity
        module=types.ModuleType('videograph')
        module.__dict__.update({'np':np,'cosine_similarity':cosine_similarity,'logger':logging.getLogger('test')})
        cls=upstream_class(ROOT/'build/upstream/m3/mmagent/videograph.py','VideoGraph',module.__dict__)
        previous=sys.modules.get('videograph');sys.modules['videograph']=module
        try:
            source=m3(media_storage=True)
            with tempfile.TemporaryDirectory() as td:
                out=Path(td)/'out';w=wrapper(M3Codec(space=SPACE),M3PickleWriter(),out,embeddings=True)
                engine=CompressionEngine(PartitionPlanner(),TextOperator(ConcatWriter()))
                sync(run_wrapped(engine,w,source,budgets=(BudgetRequest(unit='nodes',ratio=.5,minimum=1,rounding='ceil'),),
                    services=ServiceMap({'embeddings':Encoder(),'m3.graph_type':cls})))
                loaded=load_m3(out/'videograph.pkl',options=LoadOptions(dataset_id='test',namespace='test-video'))
                self.assertEqual(len(loaded.inputs[0].initial_snapshot.records),5)
                graph=load_m3_view(out,cls);self.assertEqual(len(graph.search_text_nodes([[1.,2.,1.]])),3)
                self.assertEqual(str(graph.nodes[0].embeddings[0].dtype),'float32')
                self.assertEqual(graph.nodes[0].metadata['opaque_bytes'],b'abc')
        finally:
            if previous is None:sys.modules.pop('videograph',None)
            else:sys.modules['videograph']=previous

    def test_actual_memos_tree_loader_receives_native_graph_document(self):
        if not (ROOT/'build/upstream/memos/src/memos/memories/textual/tree.py').is_file():
            self.skipTest('Optional pinned reference missing; run tools/fetch_test_sources.py')
        env={'BaseTextMemory':object,'TreeTextMemoryConfig':object,'TextualMemoryItem':object,'TextualMemoryMetadata':object,
            'MessageList':list,'Any':object,'logger':logging.getLogger('test')}
        # Compile just load(): remaining TreeTextMemory annotations/imports belong to a configured SDK.
        path=ROOT/'build/upstream/memos/src/memos/memories/textual/tree.py';tree=ast.parse(path.read_text())
        owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TreeTextMemory')
        method=next(n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='load')
        import os
        env.update({'os':os,'json':json});exec(compile(ast.Module(body=[method],type_ignores=[]),str(path),'exec'),env)
        class Store:
            document=None
            def import_graph(self,data,user_name=None):self.document=data
        class Configured:
            config=SimpleNamespace(memory_filename='textual_memory.json');graph_store=Store()
            load=env['load']
            def get_all(self,**kwargs):return {'nodes':[],'edges':[]}
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out';compress(memos(tree=True),wrapper(MemOSCodec(backend='tree_text'),MemOSWriter(),out))
            target=load_memos_view(out,Configured(),user_name='alice')
            self.assertEqual(set(target.graph_store.document),{'nodes','edges'})
            self.assertEqual(len(target.graph_store.document['nodes']),2)


if __name__ == '__main__':unittest.main()
