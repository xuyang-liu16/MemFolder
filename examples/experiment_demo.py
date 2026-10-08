"""No models/network: an executable full-pipeline and case-query example."""
import asyncio,json,tempfile
from pathlib import Path
from memfolder import assemble_experiment,FileRunReader

def main():
    base=Path(__file__).parent/'experiments'
    config=json.loads((base/'offline-demo.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='memfolder-full-demo-') as folder:
        output=Path(folder)/'run'
        result=asyncio.run(assemble_experiment(config,base_path=base).run(output_dir=output))
        reader=FileRunReader(output);row=result.samples[0]
        case=reader.by_question(row.sample,row.evaluation.predictions[0].question_id)
        print(json.dumps({'samples':len(result.samples),'input_nodes':row.statistics.input_nodes,'output_nodes':row.statistics.output_nodes,
            'case_status':case.status,'events':len(case.events),'test_only':True,'model_calls':0}))

if __name__=='__main__':main()
