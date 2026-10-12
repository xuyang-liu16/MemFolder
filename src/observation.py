"""Persistent, immutable events with explicit observer failure and capture policies."""
from dataclasses import dataclass
from pathlib import Path
from time import monotonic_ns
from .core import (CapturePolicy, TraceCoverage, EventEnvelope, Snapshot, ActionPlan,
    OperatorResult, DiagnosticRecord, DiagnosticLinks, FrozenMap, project_snapshot, to_data, dumps,
    MemoryInput,Prediction,EvaluationReport,FeatureBatch)
from .core.values import require
from .planning.common import resolve
from .artifacts import ArtifactStore, PublicArtifacts, FileReportWriter


@dataclass(frozen=True)
class ObservationContext:
    run_id: str
    artifacts: PublicArtifacts
    reports: FileReportWriter


@dataclass(frozen=True)
class Subscription:
    observer: object
    required: bool = False
    stages: tuple = ()


class TraceRecorder:
    def __init__(self,root,run_id,*,capture=CapturePolicy(),subscriptions=(),redactor=None):
        self.root=Path(root);self.run_id=run_id;self.capture=capture;self.subscriptions=tuple(subscriptions);self.redactor=redactor
        require(capture.text_policy!='redacted' or redactor is not None,'Redacted capture needs a redactor plugin')
        self.store=ArtifactStore(self.root);self.allowed=set();self.events=[];self.diagnostics=[];self.failures=[]
        self.pending=[];self.sample=None;self.dropped=0;self._opened=[];self._sequence=0;self._artifact_sequence=0;self._stream=None
        self.node_scopes={};self.node_origins={};self.action_nodes={};self.round_index=None;self.branch='compressed';self.spans=[]
        if capture.profile!='off':
            (self.root/'trace').mkdir(parents=True,exist_ok=True)
            self._stream=(self.root/'trace/events.jsonl').open('x',encoding='utf-8')

    def selected(self,stage,scope=None):
        return self.capture.profile!='off' and (not self.capture.sample_ids or self.sample is not None and self.sample.sample_id in self.capture.sample_ids) and (
            not self.capture.stages or stage in self.capture.stages) and (scope is None or not self.capture.scopes or scope in self.capture.scopes)

    def context(self,index):
        return ObservationContext(self.run_id,PublicArtifacts(self.store,self.allowed),FileReportWriter(self.root/'reports'/str(index)))

    async def open(self):
        for index,sub in enumerate(self.subscriptions):
            try:
                await resolve(sub.observer.open(self.context(index)));self._opened.append(index)
            except Exception:
                self.failures.append('observer:'+str(index)+':open')
                if sub.required:raise

    async def flush(self):
        events,self.pending=self.pending,[]
        for event in events:
            for index in self._opened:
                sub=self.subscriptions[index]
                if sub.stages and event.stage not in sub.stages:continue
                try:await resolve(sub.observer.on_event(event,self.context(index)))
                except Exception:
                    self.failures.append('observer:'+str(index)+':event')
                    if sub.required:raise

    async def close(self):
        failure=None
        try:
            await self.flush()
        except Exception as exc:failure=exc
        for index in reversed(self._opened):
            try:await resolve(self.subscriptions[index].observer.close(self.context(index)))
            except Exception as exc:
                self.failures.append('observer:'+str(index)+':close')
                if self.subscriptions[index].required and failure is None:failure=exc
        if self._stream:self._stream.close();self._stream=None
        if failure is not None:raise failure

    def enabled(self,schema):
        return self.selected('diagnostic') and (not self.capture.diagnostic_schemas or schema in self.capture.diagnostic_schemas)

    def emit(self,record):
        if not self.enabled(record.schema):return
        links=self.filter_links(record.links)
        if self.capture.scopes and record.links.node_ids and not links.node_ids:return
        self.diagnostics.append(record)
        refs=()
        if self.selected('diagnostic') and self.capture.profile in ('cases','full'):
            # Scoped diagnostic data needs its own contributor projection. Default to
            # links/field names rather than leaking data from unselected scopes.
            value=to_data(record) if not self.capture.scopes and self.capture.text_policy in ('full','selected','redacted') else {'schema':record.schema,'version':record.version,'component_id':record.component_id,'links':to_data(links),'data_keys':list(record.data)}
            if self.capture.text_policy=='redacted':value=self.redactor.redact(value)
            refs=(self.publish(value,'diagnostic'),)
        self.event('diagnostic','diagnostic',component=record.component_id,refs=refs,links=links)

    def publish(self,value,label):
        self._artifact_sequence+=1
        ref=self.store.put('trace/artifacts/'+str(self._artifact_sequence)+'-'+label+'.json',value)
        self.allowed.add(ref);return ref

    def track(self,snapshot):
        for n in snapshot.records:self.node_scopes[n.node_id]=n.scope;self.node_origins[n.node_id]=n.origins

    def included(self,node_id):
        return not self.capture.scopes or self.node_scopes.get(node_id) in self.capture.scopes

    def filter_links(self,links):
        nodes=tuple(i for i in links.node_ids if self.included(i))
        origins=tuple(dict.fromkeys((*links.origins,*(o for i in nodes for o in self.node_origins.get(i,())))))
        origins=tuple(o for o in origins if not self.capture.scopes or o.scope in self.capture.scopes)
        actions=tuple(a for a in links.action_ids if not self.capture.scopes or any(self.included(i) for i in self.action_nodes.get(a,())))
        return DiagnosticLinks(node_ids=nodes,origins=origins,action_ids=actions,candidate_ids=links.candidate_ids if not self.capture.scopes else (),question_ids=links.question_ids)

    def links(self,value):
        if isinstance(value,MemoryInput):value=value.initial_snapshot
        if isinstance(value,Snapshot):
            self.track(value);return DiagnosticLinks(node_ids=tuple(n.node_id for n in value.records))
        if isinstance(value,ActionPlan):
            for a in value.actions:self.action_nodes[a.action_id]=a.member_ids
            return DiagnosticLinks(node_ids=value.target_ids,action_ids=tuple(a.action_id for a in value.actions))
        if isinstance(value,OperatorResult):
            for o in value.outcomes:
                for n in o.outputs:self.node_scopes[n.node_id]=n.scope;self.node_origins[n.node_id]=n.origins
            return DiagnosticLinks(node_ids=tuple(i for o in value.outcomes for i in (*self.action_nodes.get(o.action_id,()),*(n.node_id for n in o.outputs))),action_ids=tuple(o.action_id for o in value.outcomes))
        if isinstance(value,EvaluationReport):value=value.predictions
        if isinstance(value,(tuple,list)) and all(isinstance(p,Prediction) for p in value):
            return DiagnosticLinks(node_ids=tuple(dict.fromkeys(h.node_id for p in value for h in p.retrieval)),question_ids=tuple(p.question_id for p in value))
        return DiagnosticLinks()

    def projection(self,value):
        text=self.capture.text_policy in ('full','selected','redacted')
        if isinstance(value,MemoryInput):value=value.initial_snapshot
        if isinstance(value,Snapshot):
            data=to_data(project_snapshot(value,include_text=text))
            if self.capture.scopes:data['nodes']=[n for n in data['nodes'] if n['scope'] in [to_data(s) for s in self.capture.scopes]]
            ids={n['node_id'] for n in data['nodes']};data['edges']=[e for e in data['edges'] if e['source_id'] in ids and e['target_id'] in ids]
            if self.capture.vector_policy in ('full','selected'):
                data['vectors']={n.node_id:to_data(n.embeddings) for n in value.records if n.node_id in ids}
        elif isinstance(value,ActionPlan):
            data={'input_fingerprint':value.input_fingerprint,'actions':[{'action_id':a.action_id,'kind':a.kind,'member_ids':a.member_ids,'output_ids':a.output_ids,'input_view':a.input_view} for a in value.actions if any(self.included(i) for i in a.member_ids)]}
        elif isinstance(value,OperatorResult):
            data={'outcomes':[{'action_id':o.action_id,'status':o.status,'nodes':[{'node_id':n.node_id,'origins':to_data(n.origins),'content_fingerprint':n.content_fingerprint,'text':n.text if text else None} for n in o.outputs if self.included(n.node_id)]} for o in value.outcomes if any(self.included(i) for i in self.action_nodes.get(o.action_id,()))]}
        elif isinstance(value,FeatureBatch):
            data={'name':value.name,'input_fingerprint':value.input_fingerprint,'space':to_data(value.space),'rows':[{'node_id':r.node_id,'vector':to_data(r.vector) if self.capture.vector_policy in ('full','selected') else None,'values':to_data(r.values) if text and not self.capture.scopes else {'fields':list(r.values)}} for r in value.rows if self.included(r.node_id)]}
        elif isinstance(value,EvaluationReport):
            data={'protocol_id':value.protocol_id,'predictions':self.projection(value.predictions),'metrics':to_data(value.metrics)}
        elif isinstance(value,(list,tuple)) and all(isinstance(p,Prediction) for p in value):
            data={'predictions':[{'question_id':p.question_id,'answer':to_data(p.answer) if text else None,
                'retrieval':to_data(tuple(h for h in p.retrieval if self.included(h.node_id))),'usage':to_data(p.usage)} for p in value]}
        else:raise ValueError('No public projection registered for this component result')
        if self.capture.text_policy=='redacted':data=self.redactor.redact(data)
        return data

    def event(self,stage,phase,*,component=None,refs=(),links=DiagnosticLinks(),summary=None,scope=None,span_id=None,parent_span_id=None):
        if not self.selected(stage,scope):return
        seq=self._sequence;self._sequence+=1
        links=self.filter_links(links)
        parent=parent_span_id
        if parent is None and self.spans:
            parent=self.spans[-2] if self.spans[-1]==span_id and len(self.spans)>1 else self.spans[-1] if self.spans[-1]!=span_id else None
        event=EventEnvelope(event_id=self.run_id+':'+str(seq),run_id=self.run_id,sequence=seq,name='memfolder.'+stage+'.'+phase,
            stage=stage,phase=phase,span_id=span_id or self.run_id+':'+stage+':'+str(seq),
            parent_span_id=parent,monotonic_ns=monotonic_ns(),sample=self.sample,scope=scope,
            component_id=component,action_id=links.action_ids[0] if len(links.action_ids)==1 else None,
            question_id=links.question_ids[0] if len(links.question_ids)==1 else None,round_index=self.round_index,
            artifact_refs=tuple(refs),summary=FrozenMap(summary or {}),extensions=FrozenMap({'memfolder.links':to_data(links),'memfolder.branch':self.branch}))
        try:
            self._stream.write(dumps(event)+'\n');self._stream.flush()
        except Exception:
            self.dropped+=1;raise
        self.events.append(event);self.pending.append(event)

    @property
    def coverage(self):
        return TraceCoverage(capture=self.capture,complete_for_capture=self.capture.profile!='off' and not self.failures and not self.dropped,
            events_written=len(self.events),events_dropped=self.dropped,missing_stages=tuple(dict.fromkeys(self.failures)))


class ObservedComponent:
    """Delegate algorithm calls exactly; recorder data cannot replace returned values."""
    def __init__(self,component,trace,stage):self.component=component;self.trace=trace;self.stage=stage;self.spec=component.spec
    def __getattr__(self,name):
        method=getattr(self.component,name)
        if name not in ('plan','apply','extract','project','refresh','predict','evaluate','initialize','export','materialize'):return method
        async def call(*args,**kwargs):
            if name=='plan' and args:self.trace.round_index=args[0].round_index
            span=self.trace.run_id+':'+self.stage+':'+str(self.trace._sequence)
            self.trace.event(self.stage,'started',component=self.spec.plugin_id,span_id=span)
            await self.trace.flush()
            self.trace.spans.append(span)
            try:
                value=await resolve(method(*args,**kwargs))
                observed=getattr(value,'plan',value)
                observed=getattr(observed,'snapshot',observed)
                links=self.trace.links(observed)
                refs=()
                if self.trace.selected(self.stage) and self.trace.capture.profile in ('cases','full'):
                    refs=(self.trace.publish(self.trace.projection(observed),self.stage),)
                self.trace.event(self.stage,'completed',component=self.spec.plugin_id,refs=refs,links=DiagnosticLinks(node_ids=links.node_ids,origins=links.origins),span_id=span,parent_span_id=self.trace.spans[-2] if len(self.trace.spans)>1 else None)
                if isinstance(observed,ActionPlan):
                    for action in observed.actions:self.trace.event(self.stage,'validated',component=self.spec.plugin_id,refs=refs,
                        links=DiagnosticLinks(node_ids=action.member_ids,action_ids=(action.action_id,)),summary={'kind':action.kind})
                elif isinstance(observed,OperatorResult):
                    for outcome in observed.outcomes:self.trace.event(self.stage,'validated',component=self.spec.plugin_id,refs=refs,
                        links=DiagnosticLinks(node_ids=(*self.trace.action_nodes.get(outcome.action_id,()),*(n.node_id for n in outcome.outputs)),action_ids=(outcome.action_id,)),summary={'status':outcome.status})
                elif isinstance(observed,(tuple,list)) and all(isinstance(p,Prediction) for p in observed):
                    for prediction in observed:self.trace.event(self.stage,'validated',component=self.spec.plugin_id,refs=refs,
                        links=DiagnosticLinks(node_ids=tuple(h.node_id for h in prediction.retrieval),question_ids=(prediction.question_id,)))
                await self.trace.flush();return value
            except Exception:
                self.trace.event(self.stage,'failed',component=self.spec.plugin_id,span_id=span)
                await self.trace.flush();raise
            finally:self.trace.spans.pop()
        return call


@dataclass(frozen=True)
class EventReportObserver:
    from .core import PluginSpec
    spec=PluginSpec(plugin_id='memfolder.observer.event_report',role='observer')
    def open(self,context):object.__setattr__(self,'_counts',{})
    def on_event(self,event,context):self._counts[event.stage]=self._counts.get(event.stage,0)+1
    def close(self,context):context.reports.write_json('events.json',FrozenMap({'run_id':context.run_id,'stages':self._counts}))


@dataclass(frozen=True)
class RegexRedactor:
    patterns: tuple
    replacement: str = '[REDACTED]'
    from .core import PluginSpec
    spec=PluginSpec(plugin_id='memfolder.redactor.regex',role='redactor')
    def redact(self,value):
        import re
        if type(value) is str:
            for pattern in self.patterns:value=re.sub(pattern,self.replacement,value)
            return value
        if isinstance(value,dict):return {k:self.redact(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [self.redact(v) for v in value]
        return value
