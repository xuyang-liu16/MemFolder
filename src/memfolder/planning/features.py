"""Explicit feature projections. No model names or native vector pooling are guessed."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Mapping
import math

from ..core import FeatureBatch, FeatureRow, FrozenMap
from ..core.values import require
from .common import spec, emit, numpy


@dataclass(frozen=True)
class StoredEmbeddings:
    space: object
    name: str = 'semantic'
    spec = spec('features.stored_embeddings', 'feature_provider')

    def extract(self, snapshot, context):
        rows=[]
        for n in snapshot.records:
            if not n.eligible: continue
            selected=[e for e in n.embeddings if e.space == self.space]
            require(len(selected)==1 and bool(selected[0].values),'Missing inline embedding in the configured space')
            rows.append(FeatureRow(node_id=n.node_id,vector=selected[0].values))
        return FeatureBatch(name=self.name,input_fingerprint=snapshot.fingerprint,rows=tuple(rows),space=self.space)


@dataclass(frozen=True)
class CurrentEmbeddings:
    """Read current content-bound vectors; reject stale or ambiguous spaces."""
    space: object | None = None
    name: str = 'semantic'
    spec = spec('features.current_content_embeddings', 'feature_provider')
    def extract(self, snapshot, context):
        nodes = [n for n in snapshot.records if n.eligible]
        if not nodes:
            return FeatureBatch(name=self.name, input_fingerprint=snapshot.fingerprint,
                                rows=(), space=self.space)
        spaces = {e.space for n in nodes for e in n.embeddings
                  if e.source_fingerprint == n.content_fingerprint}
        space = self.space
        if space is None:
            require(len(spaces) == 1, 'Current embeddings require an explicit unambiguous space')
            space = next(iter(spaces))
        rows = []
        for n in nodes:
            matches = [e for e in n.embeddings if e.space == space
                       and e.source_fingerprint == n.content_fingerprint and e.values]
            require(len(matches) == 1, 'Missing/stale current content embedding: '+n.node_id)
            rows.append(FeatureRow(node_id=n.node_id, vector=matches[0].values))
        return FeatureBatch(name=self.name, input_fingerprint=snapshot.fingerprint,
                           rows=tuple(rows), space=space)


def event_time(value, *, timezone_offset=None):
    """Only explicit ISO timestamps/numbers with a declared clock are admitted."""
    if type(value) in (int,float): return float(value)
    require(type(value) is str and value.strip(), 'Missing grounding event timestamp')
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:
        from ..core import ContractError
        raise ContractError('Grounding timestamp must be normalized ISO 8601 before planning') from None
    if dt.tzinfo is None:
        require(timezone_offset is not None, 'Naive event timestamps require an explicit UTC offset')
        from datetime import timedelta
        dt=dt.replace(tzinfo=timezone(timedelta(seconds=timezone_offset)))
    return dt.timestamp()


@dataclass(frozen=True)
class GroundingFeatures:
    """Standard-release grounding JSON, or caller-owned detached per-node records.

    id_map explicitly maps canonical IDs to source IDs. Participants are supplied by
    the adapter, rather than inferred from benchmark-specific user_id suffixes.
    Unknown timestamps are not silently given epoch-zero values.
    """
    grounding: FrozenMap
    participants: tuple[str,...] = ()
    id_map: FrozenMap = FrozenMap()
    timezone_offset: int | None = None
    clock: str = 'unix_seconds'
    name: str = 'entities'
    require_time: bool = True
    spec = spec('features.grounding', 'feature_provider', diagnostics=('memfolder.planning.grounding',))

    def extract(self, snapshot, context):
        nodes={str(n['node_id']):n for n in self.grounding.get('nodes',())}
        speakers={s.strip().casefold() for s in self.participants}
        rows=[]
        for n in snapshot.records:
            if not n.eligible: continue
            source=self.id_map.get(n.node_id,n.node_id)
            require(source in nodes, 'Grounding is incomplete; supply an explicit ID map')
            row=nodes[source];keys=set()
            for e in row.get('entities',()):
                key=str(e.get('key',e.get('canonical',''))).strip().casefold()
                if key and not key.startswith('event::') and str(e.get('canonical','')).strip().casefold() not in speakers:
                    keys.add(key)
            for r in row.get('relations',()):
                for side in ('subject','object'):
                    key=str(r.get(side,'')).strip().casefold()
                    if key and key not in speakers: keys.add(key)
            values={'entities':sorted(keys)}
            if self.require_time:
                values.update(event_time=event_time(row.get('timestamp'),timezone_offset=self.timezone_offset),clock=self.clock)
            rows.append(FeatureRow(node_id=n.node_id,values=FrozenMap(values)))
        batch=FeatureBatch(name=self.name,input_fingerprint=snapshot.fingerprint,rows=tuple(rows))
        emit(context,self.spec.plugin_id,'memfolder.planning.grounding',nodes=[r.node_id for r in rows],
            populated=sum(bool(r.values['entities']) for r in rows),total=len(rows))
        return batch


@dataclass(frozen=True)
class EventTimeFeatures:
    name: str = 'temporal'
    aggregation: str = 'earliest'
    spec = spec('features.event_time', 'feature_provider')

    def extract(self,snapshot,context):
        require(self.aggregation in ('earliest','latest'),'Unknown event time aggregation')
        rows=[]
        for n in snapshot.records:
            if not n.eligible: continue
            require(bool(n.time_ranges),'No parsed event time; availability is not event time')
            clocks={r.start.clock for r in n.time_ranges}
            require(len(clocks)==1,'Node event times use multiple clocks')
            choose=max if self.aggregation=='latest' else min
            earliest=choose((r.start for r in n.time_ranges),key=lambda t:t.value)
            rows.append(FeatureRow(node_id=n.node_id,values=FrozenMap({'event_time':earliest.value,'clock':earliest.clock})))
        return FeatureBatch(name=self.name,input_fingerprint=snapshot.fingerprint,rows=tuple(rows))


@dataclass(frozen=True)
class SemanticEmbeddingFeatures:
    """Inject encoder via Services. encode(texts) returns aligned vectors; space is explicit."""
    space: object
    service: str = 'embeddings'
    name: str = 'semantic'
    spec = spec('features.semantic_encoder','feature_provider')

    async def extract(self,snapshot,context):
        nodes=tuple(n for n in snapshot.records if n.eligible)
        if not nodes: return FeatureBatch(name=self.name,input_fingerprint=snapshot.fingerprint,rows=(),space=self.space)
        from .common import resolve
        vectors=await resolve(context.services.require(self.service).encode(tuple(n.text for n in nodes)))
        require(len(vectors)==len(nodes),'Encoder output count mismatch')
        return FeatureBatch(name=self.name,input_fingerprint=snapshot.fingerprint,space=self.space,
            rows=tuple(FeatureRow(node_id=n.node_id,vector=tuple(float(v) for v in vector)) for n,vector in zip(nodes,vectors)))
