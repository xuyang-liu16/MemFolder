"""Record merge writers, record construction and action execution."""

from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math
from ..component_runtime import emit, resolve, spec
from .contracts import ChatRequest, Member, TextWriteResult
from ..core import (
    ActionOutcome,
    ContentPart,
    Embedding,
    FrozenMap,
    MemoryRecord,
    OperatorResult,
    RetentionPolicy,
    to_data,
    validate_plan,
    validate_result,
)
from ..core.values import require
from ..prompt_protocol import PROTOCOL_ID, prompt_hash, render_merge


def record_owner(record):
    """Read the retained native user ID, including preexisting imported snapshots."""
    raw=record.native.get('record') or {}
    payload=raw.get('payload') or raw
    value=(record.native.get('user_id') or payload.get('user_id') or
           (payload.get('metadata') or {}).get('user_id') or (raw.get('source') or {}).get('user_id'))
    return str(value) if value is not None else None


def timestamp(record,policy='earliest'):
    if record.time_ranges:
        choose=max if policy=='latest' else min
        point=choose((r.start for r in record.time_ranges),key=lambda t:(t.clock,t.value))
        return datetime.fromtimestamp(point.value,tz=timezone.utc).isoformat() if point.clock=='unix_seconds' else f'{point.clock}:{point.value}'
    # Raw timestamp text is not used for ordering, but retains the original prompt input.
    return str(record.extensions.get('memfolder.event_timestamp','unknown'))


def display_timestamp(record, policy=None):
    """Display the materialized event time without discarding time lineage."""
    policy = policy or record.extensions.get('memfolder.timestamp_policy') or 'anchor'
    require(policy in ('anchor', 'earliest', 'latest'), 'Unknown display timestamp policy')
    if policy != 'anchor':
        return timestamp(record, policy)
    if 'memfolder.anchor_timestamp' in record.extensions:
        return str(record.extensions['memfolder.anchor_timestamp'])
    raw = record.native.get('record') or {}
    payload = raw.get('payload') or raw
    meta = payload.get('metadata') or {}
    value = payload.get('timestamp', meta.get('timestamp'))
    if value is not None and value != '':
        return str(value)
    return str(record.extensions.get('memfolder.event_timestamp') or timestamp(record))


def members_for(action, snapshot, originals, *, order_by='event_time'):
    current={n.node_id:n for n in snapshot.records}
    inputs=tuple(current[i] for i in action.member_ids)
    if action.input_view=='original':
        origins=tuple(dict.fromkeys(o for n in inputs for o in n.origins))
        selected=tuple(originals.get(o) for o in origins)
        require(all(o in n.origins for o,n in zip(origins,selected)),'Original reader returned unrelated provenance')
        # Originals may be records spanning several origins: deduplicate the entire record.
        selected=tuple({n.node_id:n for n in selected}.values())
        require({o for n in selected for o in n.origins}==set(origins),'Original reader introduced extra/missing origins')
    else:
        require(action.input_view=='current','Text operator cannot resolve custom input views')
        selected=inputs
    policy=action.parameters.get('timestamp_policy','earliest')
    require(policy in ('earliest','latest'),'Unknown member timestamp policy')
    choose=max if policy=='latest' else min
    require(order_by in ('event_time','order'),'Choose event_time or order for member ordering')
    selected=tuple(sorted(selected,key=lambda n:(
        n.order if order_by=='order' else choose((r.start.value for r in n.time_ranges),default=n.order),n.node_id)))
    return inputs,tuple(Member(n.node_id,n.text,timestamp(n,policy)) for n in selected)


@dataclass(frozen=True)
class ChronologicalMembers:
    order_by: str = 'event_time'
    spec = spec('text.chronological_members','member_resolver')
    def __post_init__(self):
        require(self.order_by in ('event_time','order'),'Choose event_time or order for member ordering')
    def resolve(self,action,snapshot,context):
        return members_for(action,snapshot,context.originals,order_by=self.order_by)


@dataclass(frozen=True)
class NativeSummaryWriter:
    service: str = 'chat'
    spec = spec('recordfolder.native_summary','text_writer')
    async def write(self,members,action,context):
        if len(members)==1:
            return TextWriteResult(text=members[0].text,usage=FrozenMap({'chat_calls':0}))
        prompt=render_merge(members)
        text=await resolve(context.services.require(self.service).complete(ChatRequest(
            role='memory_merge',prompt=prompt,prompt_id=PROTOCOL_ID+'.merge')))
        require(type(text) is str and bool(text.strip()),'Native summary returned empty or invalid text')
        return TextWriteResult(text=text,usage=FrozenMap({'chat_calls':1}),metadata=FrozenMap({
            'prompt_id':PROTOCOL_ID+'.merge','protocol_id':PROTOCOL_ID,
            'prompt_sha256':prompt_hash(prompt),'input_count':len(members)}))


@dataclass(frozen=True)
class ConcatWriter:
    separator: str = '; '
    spec = spec('text.concat','text_writer')
    def write(self,members,action,context):
        return TextWriteResult(text=self.separator.join(m.text.strip() for m in members if m.text.strip()),
                              usage=FrozenMap({'chat_calls':0}),metadata=FrozenMap({'text_policy':'concatenation'}))


@dataclass(frozen=True)
class ConservativeRecordBuilder:
    timestamp_policy: str | None = None
    spec = spec('records.conservative','record_builder')
    def __post_init__(self):
        require(self.timestamp_policy in (None,'earliest','latest'),'Unknown output timestamp policy')
    def build(self,inputs,action,written,context):
        require(written.status in ('success','fallback'),'Writer did not return a usable result')
        require(type(written.text) is str and bool(written.text.strip()),'Writer returned empty text')
        origins=tuple(dict.fromkeys(o for n in inputs for o in n.origins))
        def bound(name,choose):
            values=[getattr(n,name) for n in inputs if getattr(n,name) is not None]
            require(len({t.clock for t in values})<=1,'Cannot combine visibility bounds from different clocks')
            return choose(values,key=lambda t:t.value) if values else None
        parts=(ContentPart(modality='text',text=written.text),)+tuple(dict.fromkeys(p for n in inputs for p in n.parts if p.modality!='text'))
        # Match native materialization: the retained anchor ID owns the summary.
        # Carry identity only; the original payload remains in the source archive.
        anchor=next((n for n in inputs if n.node_id==action.output_ids[0]),inputs[0])
        owner=record_owner(anchor)
        output=MemoryRecord(node_id=action.output_ids[0],scope=action.output_scope or inputs[0].scope,
            order=action.parameters.get('output_order',max(n.order for n in inputs)),origins=origins,parts=parts,
            kind=inputs[0].kind if all(n.kind==inputs[0].kind for n in inputs) else 'memory',
            retention=RetentionPolicy(may_drop=all(n.retention.may_drop for n in inputs),
                may_merge=all(n.retention.may_merge for n in inputs),may_rewrite=all(n.retention.may_rewrite for n in inputs)),
            time_ranges=tuple(dict.fromkeys(r for n in inputs for r in n.time_ranges)),
            available_at=bound('available_at',max),expires_at=bound('expires_at',min),
            native=FrozenMap({'user_id':owner}) if owner is not None else FrozenMap(),
            extensions=FrozenMap({'memfolder.writer':written.metadata,'memfolder.action_id':action.action_id,
                'memfolder.member_ids':action.member_ids,'memfolder.content_embedding':'refresh_required',
                'memfolder.anchor_timestamp':display_timestamp(anchor,'anchor')}))
        sources=[n.extensions.get('memfolder.temporal_source') for n in inputs]
        if all(sources) and all(source==sources[0] for source in sources):
            output=replace(output,extensions=FrozenMap({**output.extensions,
                'memfolder.temporal_source':sources[0]}))
        if not output.time_ranges:
            # A shared explicit display label (e.g. an M3 clip) is not an event date.
            labels={n.extensions.get('memfolder.event_timestamp') for n in inputs}
            if len(labels)==1 and None not in labels and all(sources) and all(s==sources[0] for s in sources):
                output=replace(output,extensions=FrozenMap({**output.extensions,
                    'memfolder.event_timestamp':next(iter(labels)),
                    'memfolder.temporal_source':sources[0]}))
        # Execute generic action policies while retaining the full time lineage.
        policy=action.parameters.get('timestamp_policy',self.timestamp_policy)
        if policy is None and len(inputs)==1:
            policy=anchor.extensions.get('memfolder.timestamp_policy')
        if policy is not None:
            require(policy in ('earliest','latest'),'Unknown output timestamp policy')
            output=replace(output,extensions=FrozenMap({**output.extensions,
                'memfolder.timestamp_policy':policy,
                'memfolder.event_timestamp':timestamp(output,policy)}))
        # Native payloads are source records in the archive, rather than masquerading as
        # updated backend payloads. Wrapper performs the actual native projection.
        return output


@dataclass(frozen=True)
class TextOperator:
    writer: object = NativeSummaryWriter()
    record_builder: object = ConservativeRecordBuilder()
    member_resolver: object = ChronologicalMembers()
    spec = spec('text.operator','operator',actions=('keep','drop','merge','rewrite'),modes=('once','repeat','stream'), diagnostics=('memfolder.operator.outcome',))
    async def apply(self,snapshot,plan,context):
        validate_plan(snapshot,plan)
        by_id={n.node_id:n for n in snapshot.records};outcomes=[]
        for action in plan.actions:
            if action.kind=='keep':
                outcome=ActionOutcome(action_id=action.action_id,status='success',outputs=(by_id[action.member_ids[0]],))
            elif action.kind=='drop':
                outcome=ActionOutcome(action_id=action.action_id,status='success',outputs=())
            else:
                require(action.kind in ('merge','rewrite'),'Unsupported text action kind')
                inputs,members=await resolve(self.member_resolver.resolve(action,snapshot,context))
                require(tuple(inputs)==tuple(by_id[i] for i in action.member_ids),'Member resolver changed authoritative contributor records')
                written=await resolve(self.writer.write(members,action,context))
                output=await resolve(self.record_builder.build(inputs,action,written,context))
                outcome=ActionOutcome(action_id=action.action_id,status=written.status,outputs=(output,),
                    reason_code=written.reason_code,usage=written.usage)
            outcomes.append(outcome)
            emit(context,self.spec.plugin_id,'memfolder.operator.outcome',actions=(action.action_id,),nodes=action.member_ids,
                 kind=action.kind,status=outcome.status,usage=dict(outcome.usage),
                 output_hashes=[n.content_fingerprint for n in outcome.outputs],reason=outcome.reason_code)
        result=OperatorResult(plan_fingerprint=plan.fingerprint,outcomes=tuple(outcomes))
        validate_result(snapshot,plan,result)
        return result


@dataclass(frozen=True)
class RuleOperator(TextOperator):
    spec = spec('rules.operator','operator',actions=('keep','drop'),modes=('once','repeat','stream'), diagnostics=('memfolder.operator.outcome',))
    async def apply(self,snapshot,plan,context):
        require(all(a.kind in self.spec.action_kinds for a in plan.actions),'Rule operator only supports keep/drop')
        return await resolve(super().apply(snapshot,plan,context))


@dataclass(frozen=True)
class MemForestPairWriter:
    service: str = 'chat'
    attempts: int = 3
    failure_policy: str = 'raise'  # keep-newer fallback is explicit, never hidden
    spec = spec('memforest.pair_summary','text_writer')
    async def write(self,members,action,context):
        require(len(members)==2,'MemForest pair writer requires exactly two current memories')
        require(type(self.attempts) is int and self.attempts>0 and self.failure_policy in ('raise','keep_newer'),'Invalid pair writer policy')
        older,newer=members
        prompt=render_merge(members)
        for index in range(self.attempts):
            try:
                text=await resolve(context.services.require(self.service).complete(ChatRequest(
                    role='memory_merge',prompt=prompt,prompt_id=PROTOCOL_ID+'.merge')))
                require(type(text) is str and bool(text.strip()),'Empty pair merge')
                return TextWriteResult(text=text.strip(),usage=FrozenMap({'chat_calls':index+1}),
                    metadata=FrozenMap({'prompt_id':PROTOCOL_ID+'.merge','protocol_id':PROTOCOL_ID,
                        'prompt_sha256':prompt_hash(prompt),'input_count':2}))
            except Exception:
                if index+1<self.attempts:continue
        if self.failure_policy=='keep_newer':
            return TextWriteResult(text=newer.text,status='fallback',reason_code='pair_merge_failed_kept_newer_text',
                usage=FrozenMap({'chat_calls':self.attempts}),metadata=FrozenMap({'facts_may_be_lost':True}))
        from ..core import ContractError
        raise ContractError('MemForest pair merge failed; no result was materialized') from None


@dataclass(frozen=True)
class TomePairWriter:
    service: str = 'chat'
    spec = spec('tome.memforest_pair_writer.v2', 'text_writer')
    async def write(self, members, action, context):
        require(len(members) == 2, 'ToMe pair writer requires two current records')
        prompt = render_merge(members)
        text = await resolve(context.services.require(self.service).complete(
            ChatRequest(role='memory_merge', prompt=prompt, prompt_id=PROTOCOL_ID+'.merge')))
        require(isinstance(text, str) and bool(text.strip()), 'Empty ToMe pair merge')
        return TextWriteResult(text=text.strip(), usage=FrozenMap({'chat_calls': 1}),
            metadata=FrozenMap({'prompt_id':PROTOCOL_ID+'.merge', 'input_view':'current',
                'prompt_sha256':prompt_hash(prompt),'protocol_id':PROTOCOL_ID,'input_count':2}))


@dataclass(frozen=True)
class TomeEmbeddingBuilder:
    builder: object = ConservativeRecordBuilder()
    space: object | None = None
    service: str = 'embeddings'
    spec = spec('tome.latest_time_content_embedding.v1', 'record_builder',
                diagnostics=('memfolder.operator.tome_record',))
    async def build(self, inputs, action, written, context):
        require(len(inputs) == 2 and action.input_view == 'current'
                and action.parameters.get('timestamp_policy') == 'latest',
                'Temporal ToMe builder requires a latest-time current pair')
        destination = next(n for n in inputs if n.node_id == action.output_ids[0])
        node = await resolve(self.builder.build(inputs, action, written, context))
        require(node.node_id == destination.node_id, 'ToMe must retain destination ID')
        spaces = {e.space for n in inputs for e in n.embeddings
                  if e.source_fingerprint == n.content_fingerprint}
        space = self.space
        if space is None:
            require(len(spaces) == 1, 'Declare an unambiguous ToMe embedding space')
            space = next(iter(spaces))
        require(space.metric == 'cosine', 'ToMe needs cosine embeddings')
        require(all(any(e.space == space and e.source_fingerprint == n.content_fingerprint
                        for e in n.embeddings) for n in inputs),
                'ToMe pair inputs must have current vectors in the output embedding space')
        node = replace(node, order=destination.order, extensions=FrozenMap({
            **node.extensions, 'memfolder.timestamp_policy': 'latest',
            'memfolder.event_timestamp': timestamp(destination, 'latest'),
            'memfolder.tome.half_pass': action.parameters.get('half_pass')}))
        rows = await resolve(context.services.require(self.service).encode((node.text,)))
        require(len(rows) == 1 and len(rows[0]) == space.dimension,
                'ToMe merged text embedding is missing or misaligned')
        require(all(type(v) in (float,int) and math.isfinite(v) for v in rows[0])
                and any(v != 0 for v in rows[0]), 'Invalid or zero ToMe content embedding')
        node = replace(node, embeddings=(Embedding(space=space,
            source_fingerprint=node.content_fingerprint, values=tuple(float(v) for v in rows[0])),),
            extensions=FrozenMap({**node.extensions, 'memfolder.content_embedding': 'refreshed'}))
        emit(context, self.spec.plugin_id, 'memfolder.operator.tome_record',
            nodes=(node.node_id,), current_content_fingerprint=node.content_fingerprint,
            timestamp_policy='latest', timestamp=timestamp(node, 'latest'),
            embedding_space=to_data(space), inherited_time_ranges=to_data(node.time_ranges),
            origins=to_data(node.origins))
        return node
