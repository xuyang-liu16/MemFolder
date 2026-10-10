"""Pair writer and refreshed-record builder, independently replaceable plugins."""
from dataclasses import dataclass, replace
import math
from ..core import Embedding, FrozenMap, to_data
from ..core.values import require
from ..planning.common import emit, resolve, spec
from .text import ConservativeRecordBuilder, timestamp
from .types import ChatRequest, TextWriteResult

# Verbatim FACT_PRESERVING_MERGE_PROMPT from the backed-up text ToMe executor's
# RecallFlow_NC.py dependency. No QA, labels or probes enter the prompt.
PAIR_PROMPT = """
You are compressing two long-term memory entries into one concise memory.

Goal:
Preserve concrete atomic facts while removing redundancy. Atomic facts include:
- people and identity/status facts
- relationships
- activities, habits, plans, preferences, and emotions
- locations
- books, pets, named objects, organizations, or other named items
- events and participation
- dates, times, and temporal order

Rules:
1. Output only the final merged memory, without analysis or bullet labels.
2. Do not replace concrete facts with vague categories. For example, keep
   "pottery, painting, and camping" instead of only "creative and outdoor activities".
3. If several facts share the same subject and type, merge them into a compact list.
4. Preserve relative temporal order and convert relative time expressions when the
   timestamps make that possible.
5. Do not add facts that are not supported by the two memories.
6. Keep the merged memory no longer than the combined source memories when possible.

Memory 1: {older_text}
Timestamp 1: {older_time}
Memory 2: {newer_text}
Timestamp 2: {newer_time}
""".strip()


@dataclass(frozen=True)
class TomePairWriter:
    service: str = 'chat'
    spec = spec('tome.fact_preserving_pair_writer.v1', 'text_writer')
    async def write(self, members, action, context):
        require(len(members) == 2, 'ToMe pair writer requires two current records')
        older, newer = members
        prompt = PAIR_PROMPT.format(older_text=older.text, older_time=older.time,
                                   newer_text=newer.text, newer_time=newer.time)
        text = await resolve(context.services.require(self.service).complete(
            ChatRequest(role='tome_pair_merge', prompt=prompt)))
        require(isinstance(text, str) and bool(text.strip()), 'Empty ToMe pair merge')
        return TextWriteResult(text=text.strip(), usage=FrozenMap({'chat_calls': 1}),
            metadata=FrozenMap({'prompt_id': self.spec.plugin_id, 'input_view': 'current'}))


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
