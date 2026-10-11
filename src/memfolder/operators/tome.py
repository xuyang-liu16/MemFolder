"""Pair writer and refreshed-record builder, independently replaceable plugins."""
from dataclasses import dataclass, replace
import math
from ..core import Embedding, FrozenMap, to_data
from ..core.values import require
from ..planning.common import emit, resolve, spec
from .text import ConservativeRecordBuilder, timestamp
from .types import ChatRequest, TextWriteResult

from ..prompt_protocol import PROTOCOL_ID, render_merge, prompt_hash


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
