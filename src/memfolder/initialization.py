"""Memory-only initialization. Framework construction is an independent extension."""
from dataclasses import dataclass,replace
from .core import (MemoryInput,MemoryRecord,OriginRef,Snapshot,TimeRange,ContentPart,
    FrozenMap,fingerprint)
from .core.values import require
from .planning.common import spec,resolve
from .operators.types import ChatRequest


@dataclass(frozen=True)
class HistoryInitializer:
    """One record per event by default; chunks never cross scopes or speakers."""
    events_per_record: int = 1
    speaker_prefix: bool = True
    spec=spec('initialization.history','initializer')
    def initialize(self,memory,context):
        require(type(memory) is MemoryInput,'Initializer accepts memory only')
        if memory.initial_snapshot is not None:return memory
        require(memory.history_artifact is None,'External history requires an explicit initializer')
        require(type(self.events_per_record) is int and self.events_per_record>0,'Invalid history chunk size')
        groups=[]
        for e in memory.history:
            if not groups or len(groups[-1])>=self.events_per_record or (groups[-1][-1].scope,groups[-1][-1].speaker)!=(e.scope,e.speaker):groups.append([])
            groups[-1].append(e)
        records=[]
        for group in groups:
            parts=tuple(ContentPart(modality='text',text=(e.speaker+': ' if self.speaker_prefix and e.speaker else '')+p.text) if p.modality=='text' and p.text is not None else p for e in group for p in e.parts)
            times=[e.occurred_at for e in group if e.occurred_at is not None]
            require(len({t.clock for t in times})<=1,'History chunk mixes clocks')
            records.append(MemoryRecord(node_id='history:'+fingerprint((memory.sample.identity,tuple(e.event_id for e in group))),
                scope=group[0].scope,order=len(records),parts=parts,
                origins=tuple(OriginRef(scope=e.scope,source_id=e.event_id) for e in group),
                available_at=max(times,key=lambda t:t.value) if times else None,
                time_ranges=(TimeRange(start=min(times,key=lambda t:t.value),end=max(times,key=lambda t:t.value)),) if times else (),
                extensions=FrozenMap({'memfolder.history_events':len(group)})))
        return replace(memory,initial_snapshot=Snapshot(snapshot_id='initial:'+fingerprint(memory.sample.identity),records=tuple(records),assets=memory.assets))


@dataclass(frozen=True)
class SummaryInitializer:
    """Replaceable memory extraction, still one provenance group per chunk."""
    chunker: object = HistoryInitializer()
    service: str = 'chat'
    max_tokens: int = 1024
    spec=spec('initialization.summary','initializer')
    async def initialize(self,memory,context):
        require(type(memory) is MemoryInput,'Initializer accepts memory only')
        if memory.initial_snapshot is not None:return memory
        source=await resolve(self.chunker.initialize(memory,context));records=[]
        for n in source.initial_snapshot.records:
            text=await resolve(context.services.require(self.service).complete(ChatRequest(role='memory_extraction',
                prompt='Extract a compact factual memory from this conversation. Preserve names, dates, preferences, updates and uncertainty.\n'+n.text,max_tokens=self.max_tokens)))
            require(type(text) is str and bool(text.strip()),'Memory extractor returned empty text')
            records.append(replace(n,parts=(ContentPart(modality='text',text=text),)))
        return replace(source,initial_snapshot=replace(source.initial_snapshot,records=tuple(records)))


@dataclass(frozen=True)
class BankInitializer:
    """Explicit benchmark sample -> independently configured memory_loader."""
    loaders: tuple
    fallback: object | None = None
    spec=spec('initialization.bank','initializer')
    @property
    def source_paths(self):return tuple(p for _,loader in self.loaders for p in getattr(loader,'source_paths',()))
    async def initialize(self,memory,context):
        require(type(memory) is MemoryInput,'Bank initializer accepts memory only')
        if memory.initial_snapshot is not None:return memory
        loaders=dict(self.loaders);sid=memory.sample.sample_id
        if sid not in loaders:
            require(self.fallback is not None,'No memory bank mapped to benchmark sample')
            return await resolve(self.fallback.initialize(memory,context))
        library=await resolve(loaders[sid].load());require(len(library.inputs)==1,'Select one bank per benchmark sample')
        loaded=library.inputs[0]
        require((loaded.sample.dataset_id,loaded.sample.sample_id)==(memory.sample.dataset_id,sid),'Bank loader must declare the matching dataset_id and sample_id')
        return replace(loaded,sample=memory.sample)
