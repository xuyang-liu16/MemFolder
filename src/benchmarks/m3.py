"""Pinned M3-Bench annotation schema plus separately supplied native memory graphs."""
from dataclasses import dataclass,replace
from hashlib import sha256
from pathlib import Path
from ..core import SampleRef,EvaluationSet,DatasetSample,TimePoint,FrozenMap,fingerprint
from ..core.values import require
from ..loading.common import strict_json
from ..planning.common import spec
from .raw import read,case


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
