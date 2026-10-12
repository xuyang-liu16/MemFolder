"""Bounded experiment matrices; each run owns its outputs and config fingerprint."""
from dataclasses import replace
from itertools import product
from pathlib import Path
import copy
from .core import FrozenMap,fingerprint,to_data
from .artifacts import parse_json
from .core.values import require
from .artifacts import ArtifactStore
from .experiment import assemble_experiment


def configurations(base,*,axes=(),seeds=(0,),max_runs=256):
    require(type(max_runs) is int and max_runs>0 and seeds and all(type(s) is int for s in seeds),'Invalid matrix bounds/seeds')
    size=len(seeds)
    for axis in axes:
        require(set(axis)=={'path','values'} and axis['values'] and type(axis['path']) is str,'Invalid matrix axis')
        size*=len(axis['values'])
    require(size<=max_runs,'Matrix exceeds max_runs')
    require(len({a['path'] for a in axes})==len(axes),'Duplicate matrix axis')
    for values in product(*(a['values'] for a in axes)):
        for seed in seeds:
            config=copy.deepcopy(to_data(FrozenMap(base)))
            for axis,value in zip(axes,values):
                keys=axis['path'].split('.');target=config
                for key in keys[:-1]:require(type(target) is dict and key in target,'Matrix path missing');target=target[key]
                require(type(target) is dict and keys[-1] in target,'Matrix leaf missing');target[keys[-1]]=to_data(FrozenMap({'v':value}))['v']
            config.setdefault('run',{})['seed']=seed;yield config


async def run_matrix(base,directory,*,axes=(),seeds=(0,),max_runs=256,base_path=None,registry=None,resume=False):
    root=Path(directory).resolve();rows=list(configurations(base,axes=axes,seeds=seeds,max_runs=max_runs))
    ids=[fingerprint(FrozenMap(c))[:24] for c in rows];require(len(set(ids))==len(ids),'Duplicate matrix configurations')
    require(resume or not root.exists(),'Matrix output already exists');root.mkdir(parents=True,exist_ok=resume)
    results=[]
    for name,config in zip(ids,rows):
        config['output_dir']=str(root/name)
        result=await assemble_experiment(config,registry=registry,base_path=base_path).run(resume=resume)
        results.append({'directory':name,'run_id':result.manifest.run_id,'seed':result.manifest.seed,'aggregate':to_data(result.aggregate),
            'compression':[to_data(s.statistics) for s in result.samples]})
    report=FrozenMap({'runs':results,'count':len(results)})
    report_path=root/'matrix.json'
    if not report_path.exists():ArtifactStore(root).put('matrix.json',report)
    else:require(parse_json(report_path.read_text(encoding='utf-8'))==to_data(report),'Matrix result mismatch')
    return report
