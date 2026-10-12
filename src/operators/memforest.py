"""Historical MemForest pair writer, independent of its MST planner."""
from dataclasses import dataclass
from ..core import FrozenMap
from ..core.values import require
from ..planning.common import spec
from .types import ChatRequest,TextWriteResult
from ..prompt_protocol import PROTOCOL_ID, render_merge, prompt_hash
from ..planning.common import resolve


@dataclass(frozen=True)
class MemForestPairWriter:
    service: str = 'chat'
    attempts: int = 3
    failure_policy: str = 'raise'  # historical keep-newer fallback is explicit, never hidden
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
