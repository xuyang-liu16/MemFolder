"""Optional online grounding; cached release grounding remains independently usable."""
from dataclasses import dataclass
from ..core import FeatureBatch,FeatureRow,FrozenMap
from ..core.values import require
from ..operators.types import ChatRequest
from ..artifacts import parse_json
from .common import spec,resolve


@dataclass(frozen=True)
class ChatGroundingFeatures:
    service: str = 'grounding'
    name: str = 'entities'
    aliases: FrozenMap = FrozenMap()
    require_time: bool = False
    spec=spec('features.chat_grounding','feature_provider')
    async def extract(self,snapshot,context):
        rows=[]
        for node in snapshot.records:
            if not node.eligible:continue
            prompt='Extract explicitly mentioned named entities from MEMORY. Return JSON only: {"entities": ["entity name"]}. Do not infer missing identities.\nMEMORY\n'+node.text
            raw=await resolve(context.services.require(self.service).complete(ChatRequest(role='memory_grounding',prompt=prompt,temperature=0)))
            data=parse_json(raw);require(type(data) is dict and set(data)=={'entities'} and type(data['entities']) is list and all(type(e) is str and e.strip() for e in data['entities']),'Invalid grounding response')
            entities=sorted({self.aliases.get(e.casefold().strip(),e.casefold().strip()) for e in data['entities']})
            values={'entities':entities}
            if self.require_time:
                require(bool(node.time_ranges),'Grounding time must come from explicit parsed event time')
                times=[r.start for r in node.time_ranges];require(len({t.clock for t in times})==1,'Mixed grounding clocks')
                first=min(times,key=lambda t:t.value);values.update(event_time=first.value,clock=first.clock)
            rows.append(FeatureRow(node_id=node.node_id,values=FrozenMap(values)))
        return FeatureBatch(name=self.name,input_fingerprint=snapshot.fingerprint,rows=tuple(rows))
