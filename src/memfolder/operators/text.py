"""Text execution and record construction are separate plugins."""
from __future__ import annotations
from ..planning.common import resolve

from dataclasses import dataclass
from datetime import datetime, timezone
from ..core import (ActionOutcome, OperatorResult, MemoryRecord, ContentPart, RetentionPolicy,
    FrozenMap, fingerprint, validate_plan, validate_result)
from ..core.values import require
from ..planning.common import emit, spec
from .types import Member, ChatRequest, TextWriteResult
from ..prompt_protocol import PROTOCOL_ID, render_merge, prompt_hash


def timestamp(record,policy='earliest'):
    if record.time_ranges:
        choose=max if policy=='latest' else min
        point=choose((r.start for r in record.time_ranges),key=lambda t:(t.clock,t.value))
        return datetime.fromtimestamp(point.value,tz=timezone.utc).isoformat() if point.clock=='unix_seconds' else f'{point.clock}:{point.value}'
    # Raw timestamp text is not used for ordering, but retains the original prompt input.
    return str(record.extensions.get('memfolder.event_timestamp','unknown'))


def members_for(action, snapshot, originals):
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
    selected=tuple(sorted(selected,key=lambda n:(
        choose((r.start.value for r in n.time_ranges),default=n.order),n.node_id)))
    return inputs,tuple(Member(n.node_id,n.text,timestamp(n,policy)) for n in selected)


@dataclass(frozen=True)
class ChronologicalMembers:
    spec = spec('text.chronological_members','member_resolver')
    def resolve(self,action,snapshot,context):
        return members_for(action,snapshot,context.originals)


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
    spec = spec('records.conservative','record_builder')
    def build(self,inputs,action,written,context):
        require(written.status in ('success','fallback'),'Writer did not return a usable result')
        require(type(written.text) is str and bool(written.text.strip()),'Writer returned empty text')
        origins=tuple(dict.fromkeys(o for n in inputs for o in n.origins))
        def bound(name,choose):
            values=[getattr(n,name) for n in inputs if getattr(n,name) is not None]
            require(len({t.clock for t in values})<=1,'Cannot combine visibility bounds from different clocks')
            return choose(values,key=lambda t:t.value) if values else None
        parts=(ContentPart(modality='text',text=written.text),)+tuple(dict.fromkeys(p for n in inputs for p in n.parts if p.modality!='text'))
        output=MemoryRecord(node_id=action.output_ids[0],scope=action.output_scope or inputs[0].scope,
            order=action.parameters.get('output_order',max(n.order for n in inputs)),origins=origins,parts=parts,
            kind=inputs[0].kind if all(n.kind==inputs[0].kind for n in inputs) else 'memory',
            retention=RetentionPolicy(may_drop=all(n.retention.may_drop for n in inputs),
                may_merge=all(n.retention.may_merge for n in inputs),may_rewrite=all(n.retention.may_rewrite for n in inputs)),
            time_ranges=tuple(dict.fromkeys(r for n in inputs for r in n.time_ranges)),
            available_at=bound('available_at',max),expires_at=bound('expires_at',min),
            extensions=FrozenMap({'memfolder.writer':written.metadata,'memfolder.action_id':action.action_id,
                'memfolder.member_ids':action.member_ids,'memfolder.content_embedding':'refresh_required'}))
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
