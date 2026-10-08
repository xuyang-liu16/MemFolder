"""Small CLI over the public assembly/run/analysis APIs."""
import argparse
import asyncio
import json
from pathlib import Path
from .artifacts import parse_json
from .core import to_data,FrozenMap,ContractError


def main(argv=None):
    parser=argparse.ArgumentParser(prog='memfolder');commands=parser.add_subparsers(dest='command',required=True)
    run=commands.add_parser('run');run.add_argument('config',type=Path);run.add_argument('--resume',action='store_true')
    matrix=commands.add_parser('matrix');matrix.add_argument('config',type=Path);matrix.add_argument('--resume',action='store_true')
    validate=commands.add_parser('verify');validate.add_argument('directory',type=Path)
    case=commands.add_parser('case');case.add_argument('directory',type=Path);case.add_argument('--sample-id',required=True);case.add_argument('--dataset-id',required=True)
    query=case.add_mutually_exclusive_group(required=True);query.add_argument('--question-id');query.add_argument('--action-id');query.add_argument('--source-id')
    case.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    try:
        if args.command in ('run','matrix'):
            require_config=args.config.is_file() and args.config.stat().st_size<=1024*1024
            if not require_config:raise ContractError('Missing/oversized experiment config')
            config=parse_json(args.config.read_text(encoding='utf-8-sig'));FrozenMap(config)
        if args.command=='run':
            from .experiment import assemble_experiment
            result=asyncio.run(assemble_experiment(config,base_path=args.config.parent).run(resume=args.resume))
            data={'run_id':result.manifest.run_id,'samples':len(result.samples),'compression_status':result.manifest.compression_status,'evaluation_status':result.manifest.evaluation_status,'output_dir':str(args.config.parent/config['output_dir'])}
        elif args.command=='matrix':
            from .matrix import run_matrix
            if set(config)-{'experiment','output_dir','axes','seeds','max_runs'}:raise ContractError('Unknown matrix setting')
            result=asyncio.run(run_matrix(config['experiment'],args.config.parent/config['output_dir'],axes=config.get('axes',()),seeds=config.get('seeds',(0,)),max_runs=config.get('max_runs',256),base_path=args.config.parent,resume=args.resume))
            data={'runs':result['count'],'output_dir':str(args.config.parent/config['output_dir'])}
        elif args.command=='verify':
            from .experiment import verify_experiment
            result=verify_experiment(args.directory);data={'run_id':result.manifest.run_id,'status':'verified'}
        else:
            from .analysis import FileRunReader
            reader=FileRunReader(args.directory);sample=reader.sample(args.dataset_id,args.sample_id)
            if args.question_id:value=reader.by_question(sample,args.question_id)
            elif args.action_id:value=reader.by_action(sample,args.action_id)
            else:
                origins=tuple(o for o in reader.origins(sample_id=args.sample_id,source_id=args.source_id) if o.scope.dataset_id==args.dataset_id)
                if len(origins)!=1:raise ContractError('Origin absent or ambiguous in captured trace')
                value=reader.by_origin(origins[0])
            data={'run_id':value.run_id,'status':value.status,'events':len(value.events),'artifacts':len(value.artifacts)}
            if args.output:data['case_path']=str(reader.export(value,args.output))
        print(json.dumps(data,ensure_ascii=False,allow_nan=False));return 0
    except Exception as exc:
        # Exceptions may include model prompts, HTTP headers or data. CLI reveals
        # only the type. Library callers retain the original exception for debugging.
        print(json.dumps({'status':'failed','error_type':type(exc).__name__}));return 1


if __name__=='__main__':raise SystemExit(main())
