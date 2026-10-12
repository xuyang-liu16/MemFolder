"""One application runner assembles every stage without benchmark/framework dispatch."""
from dataclasses import dataclass,replace,fields,is_dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
import inspect
from .core import (AlgorithmContext,BudgetRequest,CapturePolicy,DatasetSample,ExperimentResult,
    CompressionStatistics,SampleRunResult,RunManifest,PluginBinding,PlanningRequest,
    FrozenMap,DiagnosticLinks,ArtifactRef,from_data,to_data,fingerprint,loads)
from .core.values import require
from .assembly import assemble,binding_parameters
from .catalog import default_registry
from .plugins import BuildContext,PluginRequest
from .compression import CompressionEngine,ServiceMap
from .planning.common import resolve
from .artifacts import ArtifactStore,parse_json
from .observation import TraceRecorder,ObservedComponent,Subscription
from .evaluation.evaluator import aggregate
from .wrappers import run_wrapped,verify_materialization
from .services import MeteredService
from .prompt_protocol import protocol_manifest


def file_hash(path):
    digest=sha256()
    with path.open('rb') as stream:
        while raw:=stream.read(1024*1024):digest.update(raw)
    return digest.hexdigest()


def components(roots):
    seen=set()
    def visit(value):
        if id(value) in seen:return
        seen.add(id(value))
        if hasattr(value,'spec'):yield value
        if is_dataclass(value):
            for f in fields(value):yield from visit(getattr(value,f.name))
        elif isinstance(value,(tuple,list)):
            for child in value:yield from visit(child)
        elif isinstance(value,dict):
            for child in value.values():yield from visit(child)
    for root in roots:yield from visit(root)


def input_manifest(roots):
    paths=sorted({Path(p).resolve() for c in components(roots) for p in getattr(c,'source_paths',())},key=str)
    output={'provider_fingerprints':[{'plugin_id':c.spec.plugin_id,'fingerprint':c.input_fingerprint} for c in components(roots) if getattr(c,'input_fingerprint',None) is not None]}
    for path in paths:
        require(path.exists(),'Experiment input source is missing')
        files=sorted(p for p in path.rglob('*') if p.is_file()) if path.is_dir() else (path,)
        output[fingerprint(str(path))]={p.relative_to(path).as_posix() if path.is_dir() else 'file':file_hash(p) for p in files}
    return FrozenMap(output)


async def samples(loader):
    source=await resolve(loader.samples())
    try:
        if hasattr(source,'__aiter__'):
            async for item in source:yield item
        else:
            for item in source:yield item
    finally:
        if callable(getattr(source,'aclose',None)):await source.aclose()
        elif callable(getattr(source,'close',None)):source.close()


def statistics(initial,final,compression,seconds,services):
    before=sum(n.eligible for n in initial.records);after=sum(n.eligible for n in final.records)
    chars_before=sum(len(n.text) for n in initial.records);chars_after=sum(len(n.text) for n in final.records)
    measured={}
    try:counter=services.require('tokenizer')
    except ValueError:counter=None
    if counter is not None:
        require(bool(getattr(counter,'measurement_id',None)),'Token measurement requires an identity')
        values=[sum(counter.count(n.text) for n in s.records) for s in (initial,final)]
        require(all(type(v) is int and v>=0 for v in values),'Invalid token measurements')
        measured={'measurement_id':counter.measurement_id,'input_tokens':values[0],'output_tokens':values[1]}
    return CompressionStatistics(input_nodes=len(initial.records),output_nodes=len(final.records),input_eligible=before,output_eligible=after,
        input_characters=chars_before,output_characters=chars_after,input_edges=len(initial.edges),output_edges=len(final.edges),
        rounds=len(compression.steps),elapsed_seconds=seconds,node_retention=after/before if before else None,
        character_retention=chars_after/chars_before if chars_before else None,measurement=FrozenMap(measured))


def rebase_report(report,prefix):
    return replace(report,predictions=tuple(replace(p,reader_context=replace(p.reader_context,path=prefix+'/'+p.reader_context.path) if p.reader_context else None) for p in report.predictions),
        artifacts=tuple(replace(r,path=prefix+'/'+r.path) for r in report.artifacts))


class ObservedEngine(CompressionEngine):
    def __init__(self,*args,trace):
        super().__init__(*args);object.__setattr__(self,'trace',trace)
    async def step(self,request,**kwargs):
        self.trace.round_index=request.round_index
        return await super().step(request,**kwargs)


@dataclass(frozen=True)
class ExperimentAssembly:
    dataset: object
    initializer: object
    compression: object
    reader: object | None
    evaluator: object | None
    capture: CapturePolicy
    subscriptions: tuple
    redactor: object | None
    services: tuple
    output_dir: Path
    settings: FrozenMap
    bindings: tuple
    config_fingerprint: str
    def roots(self):return (self.dataset,self.initializer,self.compression.engine.planner,self.compression.engine.operator,
        *self.compression.engine.feature_providers,self.compression.wrapper,self.reader,self.evaluator,self.redactor,
        *(s.observer for s in self.subscriptions),*(v for _,v in self.services))

    async def run(self,*,output_dir=None,services=None,resume=False):
        root=Path(output_dir or self.output_dir).resolve();inputs=input_manifest(self.roots())
        supplied=services if isinstance(services,ServiceMap) else ServiceMap(services)
        supplied_identities={k:getattr(v,'cache_identity',None) for k,v in supplied.items()}
        if resume:
            require(all(value is not None for value in supplied_identities.values()),'Resuming injected services requires explicit cache_identity for each service')
            require(bool(getattr(self.dataset,'source_paths',())) or getattr(self.dataset,'input_fingerprint',None) is not None,'Dynamic datasets require input_fingerprint for resume')
        shared_prompts=protocol_manifest()
        execution=fingerprint((self.config_fingerprint,self.compression.source_manifest,inputs,to_data(self.bindings),supplied_identities,shared_prompts))
        if resume and root.exists():
            return verify_experiment(root,expected_execution=execution)
        require(not root.exists(),'Experiment output exists; use a fresh directory or verified resume')
        root.mkdir(parents=True);store=ArtifactStore(root)
        trace=TraceRecorder(root,'run:'+execution[:24],capture=self.capture,subscriptions=self.subscriptions,redactor=self.redactor)
        providers={**dict(self.services),**dict(supplied.items())}
        metered={name:MeteredService(value) for name,value in providers.items() if callable(getattr(value,'complete',None)) or callable(getattr(value,'encode',None))}
        configured=ServiceMap({**providers,**metered})
        artifacts=[];completed=[];seen=set();sample_refs=[];protocols=[];compression_status='running';evaluation_status='not_run' if self.reader is None else 'pending';stage='open';error=None
        async def observed(component,name,*args):return await getattr(ObservedComponent(component,trace,name),{'initialize':'initialize','reader':'predict','evaluator':'evaluate'}[name])(*args)
        try:
            await trace.open()
            artifacts.append(store.put('sources.json',{'runtime':to_data(self.compression.source_manifest),'inputs':to_data(inputs),
                'bindings':to_data(self.bindings),'execution_fingerprint':execution,'shared_prompt_protocol':shared_prompts}))
            async for item in samples(self.dataset):
                stage='load';require(type(item) is DatasetSample,'Dataset plugin must yield DatasetSample')
                sample=item.memory.sample;require(sample.identity not in seen,'Duplicate benchmark sample identity');seen.add(sample.identity);sample_refs.append(sample)
                protocols.append({'sample':to_data(sample),'protocol_id':item.evaluation.protocol_id,'public_questions_fingerprint':fingerprint(item.evaluation.reader_input()),'evaluation_fingerprint':fingerprint(item.evaluation)})
                usage_before={k:v.report() for k,v in metered.items()}
                trace.sample=sample;trace.node_scopes={};trace.node_origins={};trace.action_nodes={};trace.round_index=None;trace.branch='compressed'
                trace.event('load','completed',component=self.dataset.spec.plugin_id);await trace.flush()
                name='samples/'+fingerprint(sample.identity)[:24];sample_store=ArtifactStore(root/name)
                local_services=configured.overlay({'artifacts':sample_store});context=AlgorithmContext(services=local_services,diagnostics=trace)
                stage='initialize';memory=await observed(self.initializer,'initialize',item.memory,context)
                require(memory.sample.identity==sample.identity and memory.initial_snapshot is not None,'Initializer changed sample identity or did not build memory')
                initial=memory.initial_snapshot;trace.track(initial)
                source_ref=store.put(name+'/source.json',initial);artifacts.append(source_ref)
                wrapper=self.compression.wrapper
                require(callable(getattr(wrapper,'for_output',None)),'Experiment wrapper needs for_output(directory) for isolated sample outputs')
                wrapper=wrapper.for_output(root/name/'native')
                # bind() produces a new archive, project/materialize stay observed per run.
                session=wrapper.bind(initial) if callable(getattr(wrapper,'bind',None)) else wrapper
                exported=await resolve(ObservedComponent(session,trace,'export').export(memory,context))
                require(exported==initial,'Wrapper export changed source snapshot')
                from .core import resolve_budget
                budgets=tuple(resolve_budget(initial,from_data(BudgetRequest,to_data(b))) for b in self.settings['budgets'])
                request=PlanningRequest(run_id=trace.run_id,snapshot=initial,budgets=budgets,mode=self.settings['mode'],seed=self.settings['seed'])
                engine=ObservedEngine(ObservedComponent(self.compression.engine.planner,trace,'planner'),
                    ObservedComponent(self.compression.engine.operator,trace,'operator'),
                    tuple(ObservedComponent(p,trace,'features') for p in self.compression.engine.feature_providers),self.compression.engine.available,trace=trace)
                stage='compression';start=perf_counter()
                compressed=await engine.run(request,services=local_services,diagnostics=trace,projector=ObservedComponent(session,trace,'project'),max_rounds=self.settings['max_rounds'])
                compression_seconds=perf_counter()-start
                trace.round_index=None
                for i,step in enumerate(compressed.steps):
                    artifacts.append(store.put(name+'/rounds/'+str(i)+'.json',{'plan':to_data(step.planning.plan),'result':to_data(step.result),'input_fingerprint':step.request.snapshot.fingerprint}))
                stage='materialize';view=await resolve(ObservedComponent(session,trace,'materialize').materialize(compressed.snapshot,context))
                from .core import validate_embedding_refresh
                validate_embedding_refresh(compressed.snapshot,view.snapshot)
                final_ref=store.put(name+'/final.json',view.snapshot);artifacts.append(final_ref)
                native_ref=replace(view.artifact,path=name+'/native/'+view.artifact.path);artifacts.append(native_ref)
                local_services=local_services.overlay({'materialized_root':root/name/'native'});context=replace(context,services=local_services)
                report=None;baseline=None;qa_start=perf_counter()
                if self.reader is not None:
                    evaluation_status='running';stage='reader'
                    predictions=await observed(self.reader,'reader',item.evaluation.reader_input(),view,context)
                    for p in predictions:
                        if p.reader_context:artifacts.append(replace(p.reader_context,path=name+'/'+p.reader_context.path))
                    stage='evaluator';report=await observed(self.evaluator,'evaluator',item.evaluation,predictions,context)
                    report=rebase_report(report,name)
                    artifacts.extend(report.artifacts)
                    artifacts.append(store.put(name+'/evaluation.json',report))
                    if self.settings['evaluate_source']:
                        trace.branch='uncompressed'
                        stage='baseline';baseline_wrapper=wrapper.for_output(root/name/'baseline_native')
                        baseline_session=baseline_wrapper.bind(initial) if callable(getattr(baseline_wrapper,'bind',None)) else baseline_wrapper
                        baseline_view=await resolve(baseline_session.materialize(initial,context))
                        artifacts.append(replace(baseline_view.artifact,path=name+'/baseline_native/'+baseline_view.artifact.path))
                        baseline_context=replace(context,services=configured.overlay({'artifacts':ArtifactStore(root/name/'baseline'),'materialized_root':root/name/'baseline_native'}))
                        preds=await observed(self.reader,'reader',item.evaluation.reader_input(),baseline_view,baseline_context)
                        for p in preds:
                            if p.reader_context:artifacts.append(replace(p.reader_context,path=name+'/baseline/'+p.reader_context.path))
                        baseline=await observed(self.evaluator,'evaluator',item.evaluation,preds,baseline_context)
                        baseline=rebase_report(baseline,name+'/baseline')
                        artifacts.extend(baseline.artifacts)
                        artifacts.append(store.put(name+'/baseline_evaluation.json',baseline))
                stat=statistics(initial,view.snapshot,compressed,compression_seconds,configured)
                usage={k:{field:{op:amount-usage_before[k][field].get(op,0) for op,amount in value.report()[field].items()} for field in ('calls','failed','seconds')} for k,value in metered.items()}
                completed.append(SampleRunResult(sample=sample,source=source_ref,final=final_ref,materialized=native_ref,statistics=stat,
                    evaluation=report,baseline_evaluation=baseline,timings=FrozenMap({'compression_seconds':compression_seconds,'evaluation_seconds':perf_counter()-qa_start if self.reader else 0.}),usage=FrozenMap({'services':usage,'provider_token_usage':None})))
                trace.event('sample','completed',summary={'input_nodes':stat.input_nodes,'output_nodes':stat.output_nodes,'rounds':stat.rounds});await trace.flush()
            require(bool(completed) or self.settings['allow_empty'],'Benchmark selected no samples')
            compression_status='completed';evaluation_status='completed' if self.reader else 'not_run'
        except Exception as exc:
            error=exc;compression_status='failed'
            if evaluation_status=='running':evaluation_status='failed'
            trace.event('run','failed',summary={'stage':stage,'error_type':type(exc).__name__})
        finally:
            try:await trace.close()
            except Exception as exc:
                if error is None:error=exc
            for _,service in reversed(self.services):
                if callable(getattr(service,'close',None)):
                    try:await resolve(service.close())
                    except Exception as exc:
                        if error is None:error=exc
        coverage=trace.coverage
        for report_path in sorted((root/'reports').rglob('*')):
            if report_path.is_file():artifacts.append(ArtifactRef(artifact_id='observer-report:'+report_path.relative_to(root).as_posix(),
                path=report_path.relative_to(root).as_posix(),sha256=file_hash(report_path),media_type='application/json'))
        if self.capture.profile!='off':
            artifacts.extend(sorted(trace.allowed,key=lambda r:r.path))
            event_path=root/'trace/events.jsonl'
            artifacts.append(ArtifactRef(artifact_id='events:'+trace.run_id,path='trace/events.jsonl',sha256=file_hash(event_path),media_type='application/x-ndjson',schema_id='memfolder.event',record_count=len(trace.events)))
            artifacts.append(store.put('trace/index.json',{'events':to_data(tuple(trace.events)),'public_artifacts':to_data(tuple(sorted(trace.allowed,key=lambda r:r.path))),'coverage':to_data(coverage)}))
        manifest=RunManifest(run_id=trace.run_id,config_fingerprint=self.config_fingerprint,samples=tuple(sample_refs),bindings=self.bindings,
            seed=self.settings['seed'],mode=self.settings['mode'],compression_status=compression_status,evaluation_status=evaluation_status,
            observation_status='off' if self.capture.profile=='off' else 'complete' if coverage.complete_for_capture else 'incomplete',coverage=coverage,
            artifacts=tuple(artifacts),extensions=FrozenMap({'memfolder.execution_fingerprint':execution,'memfolder.failed_stage':stage if error else None,
                'memfolder.protocols':protocols,'memfolder.shared_prompt_protocol':shared_prompts}))
        manifest_ref=store.put('run.manifest.json',manifest)
        if error is not None:raise error
        result=ExperimentResult(manifest=manifest,samples=tuple(completed),aggregate=FrozenMap({
            'compressed':to_data(aggregate(r.evaluation for r in completed if r.evaluation)),
            'uncompressed':to_data(aggregate(r.baseline_evaluation for r in completed if r.baseline_evaluation))}))
        result_ref=store.put('result.json',result)
        store.put('completion.json',{'manifest':to_data(manifest_ref),'result':to_data(result_ref),'execution_fingerprint':execution})
        return result


def verify_experiment(directory,*,expected_execution=None):
    root=Path(directory);store=ArtifactStore(root)
    complete=parse_json((root/'completion.json').read_text(encoding='utf-8'))
    from .core import ArtifactRef
    require(expected_execution is None or complete['execution_fingerprint']==expected_execution,'Resume inputs, config, plugins or runtime changed')
    manifest=store.read(from_data(ArtifactRef,complete['manifest']));result=store.read(from_data(ArtifactRef,complete['result']))
    require(type(result) is ExperimentResult and result.manifest==manifest and manifest.compression_status=='completed' and manifest.evaluation_status in ('completed','not_run'),'Incomplete experiment')
    require(manifest.extensions['memfolder.execution_fingerprint']==complete['execution_fingerprint'],'Execution fingerprint mismatch')
    for ref in manifest.artifacts:require(store.verify(ref),'Run artifact checksum mismatch')
    for row in result.samples:
        verify_materialization(row.materialized.resolve(root).parent,artifact=replace(row.materialized,path='manifest.json'))
        if row.baseline_evaluation:verify_materialization(row.materialized.resolve(root).parent.parent/'baseline_native')
    return result


def assemble_experiment(configuration,*,registry=None,base_path=None,available=()):
    require(set(configuration)<={'dataset','initializer','compression','reader','evaluator','capture','observers','redactor','services','output_dir','run'} and {'dataset','compression','output_dir'}<=set(configuration),'Invalid experiment config')
    require(('reader' in configuration)==('evaluator' in configuration),'Configure reader and evaluator together')
    registry=registry or default_registry();bindings=[]
    context=BuildContext(base_path=Path(base_path or Path.cwd()),registry=registry,available=tuple(available),binding_sink=bindings.append)
    def build(config,role):return registry.create(PluginRequest.from_mapping(config),role=role,context=context,available=tuple(available)).instance
    compressed=assemble(configuration['compression'],registry=registry,base_path=context.base_path,available=available)
    require(compressed.wrapper is not None,'Experiment requires a materializing wrapper')
    dataset=build(configuration['dataset'],'data_loader');initializer=build(configuration.get('initializer',{'plugin':'history-initializer'}),'initializer')
    reader=build(configuration['reader'],'reader') if 'reader' in configuration else None
    evaluator=build(configuration['evaluator'],'evaluator') if reader is not None else None
    capture=from_data(CapturePolicy,to_data(FrozenMap(configuration.get('capture',{}))))
    subscriptions=[]
    for row in configuration.get('observers',()):
        require(set(row)<={'plugin','parameters','required','stages'} and type(row.get('required',False)) is bool,'Invalid observer subscription')
        stages=row.get('stages',());require(all(type(s) is str for s in stages),'Invalid observer stage filter')
        subscriptions.append(Subscription(build({k:v for k,v in row.items() if k in ('plugin','parameters')},'observer'),row.get('required',False),tuple(stages)))
    redactor=build(configuration['redactor'],'redactor') if 'redactor' in configuration else None
    require(capture.text_policy!='redacted' or redactor is not None,'Redacted capture needs a redactor plugin')
    services=tuple((name,build(v,'service')) for name,v in configuration.get('services',{}).items())
    settings={'seed':0,'mode':'once','max_rounds':None,'budgets':[],'allow_empty':False,'evaluate_source':False}
    require(set(configuration.get('run',{}))<=set(settings),'Unknown run setting');settings.update(configuration.get('run',{}))
    require(type(settings['seed']) is int and settings['mode'] in ('once','repeat') and
            (settings['max_rounds'] is None or type(settings['max_rounds']) is int and settings['max_rounds']>0),
            'Invalid batch execution settings')
    require(all(type(settings[k]) is bool for k in ('allow_empty','evaluate_source')),'Invalid run boolean')
    require(not settings['evaluate_source'] or reader is not None,'Source QA requires reader/evaluator')
    for b in settings['budgets']:from_data(BudgetRequest,to_data(FrozenMap(b)))
    bindings.extend(compressed.bindings)
    roots=(dataset,initializer,reader,evaluator,redactor,*(s.observer for s in subscriptions),*(v for _,v in services))
    for component in components(roots):
        path=inspect.getsourcefile(type(component))
        if path:bindings.append(PluginBinding(plugin_id=component.spec.plugin_id,role=component.spec.role,api_version=component.spec.api_version,
            implementation_revision='sha256:'+file_hash(Path(path)),parameters_fingerprint=binding_parameters(component)))
    return ExperimentAssembly(dataset,initializer,compressed,reader,evaluator,capture,tuple(subscriptions),redactor,services,context.path(configuration['output_dir']),FrozenMap(settings),tuple(dict.fromkeys(bindings)),fingerprint(FrozenMap(configuration)))
