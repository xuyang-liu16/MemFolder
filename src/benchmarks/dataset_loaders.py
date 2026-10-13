"""Benchmark loaders with separated memory histories and evaluation labels."""

import csv
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from ..component_runtime import resolve, spec
from ..core import (
    ContentPart,
    ContractError,
    DatasetSample,
    EvaluationCase,
    EvaluationSet,
    FrozenMap,
    HistoryEvent,
    MemoryInput,
    OriginRef,
    PluginSpec,
    SampleRef,
    ScopeRef,
    TimePoint,
    fingerprint,
    loads,
)
from ..core.values import require
from ..loading.validation import strict_json
from ..plugins import BuildContext


def read(path,limit=2*1024**3):
    path=Path(path);require(path.is_file() and path.stat().st_size<=limit,'Missing/oversized benchmark source')
    data=path.read_bytes();require(len(data)<=limit,'Benchmark source grew beyond limit');return data


def date(value,offset):
    if value is None:return None
    require(type(value) is str,'Date must be text')
    parsed=None
    try:parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:
        for fmt in ('%I:%M %p on %d %B, %Y','%Y/%m/%d (%a) %H:%M','%Y/%m/%d (%A) %H:%M','%Y/%m/%d %H:%M','%Y-%m-%d'):
            try:parsed=datetime.strptime(value,fmt);break
            except ValueError:pass
    require(parsed is not None,'Unrecognized date; supply a dataset adapter for this format')
    if parsed.tzinfo is None:
        require(type(offset) is int and -840<=offset<=840,'Naive date requires explicit utc_offset_minutes')
        parsed=parsed.replace(tzinfo=timezone(timedelta(minutes=offset)))
    return TimePoint(value=parsed.timestamp(),clock='unix_seconds')


def scope(sample,partition='conversation'):
    return ScopeRef(dataset_id=sample.dataset_id,sample_id=sample.sample_id,partition_id=partition)


def event(sample,event_id,seq,text,speaker=None,at=None,native=None,partition='conversation'):
    require(type(text) is str and bool(text.strip()),'Missing/empty history text')
    return HistoryEvent(event_id=str(event_id),scope=scope(sample,partition),sequence=seq,
        parts=(ContentPart(modality='text',text=text),),speaker=speaker,occurred_at=at,native=FrozenMap(native or {}))


def case(sample,qid,question,truth,*,options=None,as_of=None,evidence=()):
    return EvaluationCase(question_id=str(qid),sample=sample,question=(ContentPart(modality='text',text=question),),
        ground_truth=FrozenMap(truth),options=FrozenMap(options or {}),as_of=as_of,evidence=tuple(evidence))


def dataset(sample,history,cases,protocol):
    return DatasetSample(memory=MemoryInput(sample=sample,history=tuple(history)),
        evaluation=EvaluationSet(sample=sample,cases=tuple(cases),protocol_id=protocol))


@dataclass(frozen=True)
class LoCoMoLoader:
    path: Path
    split: str = 'test'
    utc_offset_minutes: int | None = None
    sample_ids: tuple = ()
    evidence_policy: str = 'strict'
    max_file_bytes: int = 2*1024**3
    spec=spec('dataset.locomo','data_loader')
    @property
    def source_paths(self):return (self.path,)
    def samples(self):
        require(self.evidence_policy in ('strict','preserve_unknown'), 'Unknown LoCoMo evidence policy')
        raw=read(self.path,self.max_file_bytes);rows=strict_json(raw.decode('utf-8-sig'),'locomo');require(type(rows) is list,'LoCoMo expects a JSON array')
        version=sha256(raw).hexdigest()
        for row in rows:
            sid=str(row['sample_id'])
            if self.sample_ids and sid not in self.sample_ids:continue
            sample=SampleRef(dataset_id='locomo',sample_id=sid,split=self.split,dataset_fingerprint=version)
            history=[];conversation=row['conversation']
            sessions=sorted((int(k[8:]),k) for k in conversation if re.fullmatch(r'session_\d+',k))
            for _,key in sessions:
                at=date(conversation.get(key+'_date_time'),self.utc_offset_minutes)
                for turn in conversation[key]:
                    # event_summary, observations, answer/evidence annotations never enter history.
                    native={k:turn[k] for k in ('img_url','blip_caption','query') if k in turn}
                    text=turn['text']
                    if turn.get('blip_caption'):text+='\n[Image caption] '+str(turn['blip_caption'])
                    history.append(event(sample,turn['dia_id'],len(history),text,turn.get('speaker'),at,native))
            origins={e.event_id:OriginRef(scope=e.scope,source_id=e.event_id) for e in history}
            times=[e.occurred_at for e in history if e.occurred_at]
            as_of=max(times,key=lambda t:t.value) if times else None
            cases=[]
            for i,qa in enumerate(row['qa']):
                ids=qa.get('evidence',[])
                require(type(ids) is list and all(type(e) is str for e in ids),'LoCoMo evidence must be a list of dialog IDs')
                unknown=tuple(e for e in ids if e not in origins)
                require(not unknown or self.evidence_policy=='preserve_unknown','LoCoMo evidence names an unknown dialog ID')
                truth={'answer':qa.get('answer',''),'category':qa['category']}
                if unknown:
                    truth['unresolved_evidence']=unknown
                cases.append(case(sample,qa.get('question_id',sid+':'+str(i)),qa['question'],truth,as_of=as_of,evidence=[origins[e] for e in ids if e in origins]))
            yield dataset(sample,history,cases,'locomo.qa.v1')


@dataclass(frozen=True)
class LongMemEvalLoader:
    path: Path
    split: str = 'test'
    utc_offset_minutes: int | None = None
    sample_ids: tuple = ()
    max_file_bytes: int = 2*1024**3
    spec=spec('dataset.longmemeval','data_loader')
    @property
    def source_paths(self):return (self.path,)
    def samples(self):
        raw=read(self.path,self.max_file_bytes);rows=strict_json(raw.decode('utf-8-sig'),'longmemeval');require(type(rows) is list,'LongMemEval expects a JSON array')
        version=sha256(raw).hexdigest()
        for row in rows:
            sid=str(row['question_id'])
            if self.sample_ids and sid not in self.sample_ids:continue
            sample=SampleRef(dataset_id='longmemeval',sample_id=sid,split=self.split,dataset_fingerprint=version)
            ids=row['haystack_session_ids'];sessions=row['haystack_sessions'];dates=row['haystack_dates']
            require(len(ids)==len(sessions)==len(dates) and len(set(ids))==len(ids),'LongMemEval parallel session fields mismatch')
            history=[];evidence=[];answer_sessions=set(row.get('answer_session_ids',()))
            for session_id,turns,when in zip(ids,sessions,dates):
                at=date(when,self.utc_offset_minutes)
                for i,turn in enumerate(turns):
                    e=event(sample,str(session_id)+':'+str(i),len(history),turn['content'],turn['role'],at,{'session_id':str(session_id)})
                    history.append(e)
                    if turn.get('has_answer'):evidence.append(OriginRef(scope=e.scope,source_id=e.event_id))
                if session_id in answer_sessions and not any(t.get('has_answer') for t in turns):
                    evidence.extend(OriginRef(scope=e.scope,source_id=e.event_id) for e in history[-len(turns):] if turns)
            truth={'answer':str(row['answer']),'question_type':row['question_type'],'abstention':sid.endswith('_abs')}
            yield dataset(sample,history,[case(sample,sid,row['question'],truth,as_of=date(row.get('question_date'),self.utc_offset_minutes),evidence=evidence)],'longmemeval.qa.v1')


def choices(value):
    if type(value) is str:
        value=value.strip()
        if value.startswith('['):
            import ast
            require(len(value)<=1_000_000,'Oversized choices')
            try:value=strict_json(value,'choices')
            except ValueError:value=ast.literal_eval(value)
        else:
            matches=list(re.finditer(r'(?:^|\n)\s*\(([a-zA-Z])\)\s*',value))
            require(bool(matches),'Options require a list or labeled lines')
            value={m.group(1).upper():value[m.end():matches[i+1].start() if i+1<len(matches) else len(value)].strip() for i,m in enumerate(matches)}
    if type(value) is list:
        require(0<len(value)<=26,'Invalid number of options');value={chr(65+i):str(v) for i,v in enumerate(value)}
    require(type(value) is dict and value and all(type(k) is str and type(v) is str for k,v in value.items()),'Invalid options')
    return value


@dataclass(frozen=True)
class PersonaMemLoader:
    path: Path
    contexts_path: Path
    split: str = 'test'
    sample_ids: tuple = ()
    max_file_bytes: int = 2*1024**3
    spec=spec('dataset.personamem','data_loader')
    @property
    def source_paths(self):return (self.path,self.contexts_path)
    def samples(self):
        # Index offsets rather than retaining all potentially 1M-token conversations.
        raw=read(self.path,self.max_file_bytes);index={};h=sha256()
        require(self.contexts_path.is_file() and self.contexts_path.stat().st_size<=self.max_file_bytes,'Missing/oversized PersonaMem contexts')
        with self.contexts_path.open('rb') as stream:
            total=0
            while True:
                offset=stream.tell();line=stream.readline()
                if not line:break
                h.update(line);total+=len(line);require(total<=self.max_file_bytes,'Contexts grew beyond limit')
                if not line.strip():continue
                obj=strict_json(line.decode('utf-8-sig'),'personamem.contexts')
                require(type(obj) is dict and len(obj)==1,'Expected shared_context_id to conversation mapping')
                key=next(iter(obj));require(key not in index,'Duplicate PersonaMem context ID');index[key]=offset
        version=fingerprint((sha256(raw).hexdigest(),h.hexdigest()))
        import io
        with self.contexts_path.open('rb') as stream:
            for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
                sid=str(row['question_id'])
                if self.sample_ids and sid not in self.sample_ids:continue
                key=row['shared_context_id'];require(key in index,'Missing PersonaMem shared context')
                stream.seek(index[key]);full=strict_json(stream.readline().decode('utf-8-sig'),'personamem.context')[key]
                end=int(row['end_index_in_shared_context']);require(type(full) is list and 0<=end<=len(full),'Invalid PersonaMem context cutoff')
                sample=SampleRef(dataset_id='personamem',sample_id=sid,split=self.split,dataset_fingerprint=version)
                history=[event(sample,key+':'+str(i),i,turn['content'],turn['role']) for i,turn in enumerate(full[:end])]
                options=choices(row['all_options']);gold=row['correct_answer'].strip('() ').upper();require(gold in options,'Unknown PersonaMem answer label')
                yield dataset(sample,history,[case(sample,sid,row['user_question_or_message'],{'choice':gold,'question_type':row['question_type'],'persona_id':row['persona_id']},options=options)],'personamem.choice.v1')


@dataclass(frozen=True)
class M3BenchmarkLoader:
    path: Path
    memory_loaders: tuple
    variant: str = 'robot'
    split: str = 'test'
    sample_ids: tuple = ()
    question_ids: tuple = ()
    max_file_bytes: int = 2*1024**3
    spec=spec('dataset.m3','data_loader')
    @property
    def source_paths(self):return (self.path,)+tuple(p for _,loader in self.memory_loaders for p in getattr(loader,'source_paths',()))
    def samples(self):
        require(self.variant in ('robot','web'),'Unknown M3 benchmark subset')
        raw=read(self.path,self.max_file_bytes);rows=strict_json(raw.decode('utf-8-sig'),'m3');require(type(rows) is dict,'M3 annotations expect video_id mapping')
        loaders=dict(self.memory_loaders)
        for video,row in rows.items():
            if self.sample_ids and video not in self.sample_ids:continue
            require(video in loaders,'M3 benchmark requires an explicit native memory mapping for each selected video')
            library=loaders[video].load();require(len(library.inputs)==1,'Select a single video memory bank')
            loaded=library.inputs[0];groups={}
            for qa in row['qa_list']:
                if self.question_ids and qa['question_id'] not in self.question_ids:continue
                groups.setdefault(qa.get('before_clip'),[]).append(qa)
            for cutoff,qas in groups.items():
                sid=video if cutoff is None else video+':through_clip:'+str(cutoff)
                sample=SampleRef(dataset_id='m3.'+self.variant,sample_id=sid,split=self.split,
                    dataset_fingerprint=fingerprint((sha256(raw).hexdigest(),loaded.sample.dataset_fingerprint)))
                snapshot=loaded.initial_snapshot
                if cutoff is not None:
                    require(type(cutoff) is int and cutoff>=0,'Invalid M3 before_clip')
                    # Official truncate_memory_by_clip retains native IDs through the last
                    # text node at this clip, including earlier protected identity nodes.
                    ends=[int(n.native['id']) for n in snapshot.records if n.kind in ('episodic','semantic') and n.native['record']['metadata']['timestamp']==cutoff]
                    require(bool(ends),'M3 cutoff clip missing; refusing to expose the full graph')
                    end=max(ends);kept=tuple(n for n in snapshot.records if int(n.native['id'])<=end);ids={n.node_id for n in kept}
                    require(all(n.available_at is None or n.available_at.value<=cutoff for n in kept),'M3 native ordering crosses clip boundary')
                    snapshot=replace(snapshot,records=kept,edges=tuple(e for e in snapshot.edges if e.source_id in ids and e.target_id in ids))
                # Rebind only public sample scopes. Native graph/video identities stay intact.
                records=[]
                for n in snapshot.records:
                    sc=replace(n.scope,dataset_id=sample.dataset_id,sample_id=sid)
                    origins=tuple(replace(o,scope=replace(o.scope,dataset_id=sample.dataset_id,sample_id=sid)) for o in n.origins)
                    records.append(replace(n,scope=sc,origins=origins))
                snapshot=replace(snapshot,records=tuple(records));memory=replace(loaded,sample=sample,initial_snapshot=snapshot)
                times=[n.available_at for n in records if n.available_at is not None]
                as_of=TimePoint(value=cutoff,clock=times[0].clock) if cutoff is not None and times else max(times,key=lambda t:t.value) if times else None
                cases=tuple(case(sample,q['question_id'],q['question'],{'answer':q['answer'],'question_type':q.get('type',[])},as_of=as_of) for q in qas)
                yield DatasetSample(memory=memory,evaluation=EvaluationSet(sample=sample,cases=cases,protocol_id='m3.'+self.variant+'.open_qa.v1'))


SPEC = PluginSpec(plugin_id='memfolder.dataset.jsonl.v1', role='data_loader',
                  provides=('benchmark.samples', 'benchmark.memory_evaluation_separation'))


@dataclass(frozen=True, kw_only=True)
class CanonicalDatasetLoader:
    path: Path
    max_samples: int = 1_000_000
    max_file_bytes: int = 2 * 1024**3
    spec = SPEC

    def __post_init__(self):
        for limit in (self.max_samples,self.max_file_bytes):
            require(type(limit) is int and limit > 0, 'Invalid benchmark input limit')

    @property
    def source_paths(self):
        return (self.path,)

    def samples(self):
        require(self.path.is_file() and self.path.stat().st_size <= self.max_file_bytes,
                'Missing/oversized canonical benchmark file')
        total, count = 0, 0
        with self.path.open('rb') as source:
            for line_number, raw in enumerate(source,1):
                total += len(raw)
                require(total <= self.max_file_bytes, 'Benchmark file-size limit exceeded')
                try:
                    text = raw.decode('utf-8-sig' if line_number == 1 else 'utf-8')
                except UnicodeError:
                    raise ContractError('Invalid benchmark UTF-8') from None
                if not text.strip():
                    continue
                require(count < self.max_samples, 'Benchmark sample limit exceeded')
                try:
                    sample = loads(text, expected=DatasetSample)
                except ContractError:
                    raise ContractError('Invalid DatasetSample envelope in benchmark JSONL') from None
                count += 1
                yield sample


def build(parameters, *, context: BuildContext):
    require(set(parameters) <= {'path','max_samples','max_file_bytes'} and 'path' in parameters,
            'Unknown/missing canonical benchmark parameters')
    return CanonicalDatasetLoader(path=context.path(parameters['path']),
        max_samples=parameters.get('max_samples',1_000_000), max_file_bytes=parameters.get('max_file_bytes',2*1024**3))


build.spec = SPEC


@dataclass(frozen=True)
class CompositeDatasetLoader:
    loaders: tuple
    spec=spec('dataset.composite','data_loader')
    @property
    def source_paths(self):return tuple(p for loader in self.loaders for p in getattr(loader,'source_paths',()))
    async def samples(self):
        for loader in self.loaders:
            source=await resolve(loader.samples())
            try:
                if hasattr(source,'__aiter__'):
                    async for sample in source:yield sample
                else:
                    for sample in source:yield sample
            finally:
                if callable(getattr(source,'aclose',None)):await source.aclose()
                elif callable(getattr(source,'close',None)):source.close()
