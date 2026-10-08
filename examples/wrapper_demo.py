"""Offline Mem0 -> assembly -> native points. No LLM/SDK dependencies."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from memfolder.core import BudgetRequest, EmbeddingSpace, fingerprint, to_data
from memfolder.loading import Importer, Mem0Adapter, SourceDocument
from memfolder.assembly import assemble
from memfolder.compression import ServiceMap,DiagnosticCollector
from memfolder.wrappers import verify_materialization

class TestEncoder:
    def encode(self,texts):return [(float(len(t)),1.,1.) for t in texts]

async def main():
    data={'points':[{'id':i,'payload':{'data':text,'user_id':'alice'},'vector':[1.,1.,1.]} for i,text in enumerate(('Alice likes tea','Alice drinks green tea','Alice runs daily'))]}
    source=Importer(adapter=Mem0Adapter()).load_documents((SourceDocument(source_id='demo',sha256=fingerprint(data),data=data),)).inputs[0]
    space=to_data(EmbeddingSpace(provider='test-only',model='length-vector',revision='1',dimension=3))
    with tempfile.TemporaryDirectory() as td:
        config={'planner':{'plugin':'random-merge'},'operator':{'plugin':'text-operator','parameters':{'writer':{'plugin':'concat-writer'}}},
            'wrapper':{'plugin':'mem0-wrapper','parameters':{'output_dir':'native-output','codec':{'plugin':'mem0-codec','parameters':{'space':space}},
                'embedding_provider':{'plugin':'content-embeddings','parameters':{'space':space}}}}}
        assembly=assemble(config,base_path=td);diagnostics=DiagnosticCollector()
        run=await assembly.run(source,budgets=(BudgetRequest(unit='nodes',limit=2),),services=ServiceMap({'embeddings':TestEncoder()}),diagnostics=diagnostics)
        _,native=verify_materialization(Path(td)/'native-output',artifact=run.materialized.artifact)
        print(json.dumps({'framework':native.framework_id,'records':len(run.snapshot.records),'diagnostic_events':len(diagnostics.records),'encoder':'test-only'}))

if __name__=='__main__':asyncio.run(main())
