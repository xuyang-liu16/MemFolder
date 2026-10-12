"""Actual content embeddings, separate from pooled planner features."""
from dataclasses import dataclass, replace
from ..core import Embedding, FrozenMap, validate_embedding_refresh
from ..core.values import require
from ..planning.common import emit, resolve, spec


@dataclass(frozen=True)
class ChangedTextEmbeddings:
    space: object
    service: str = 'embeddings'
    source_slot: str | None = None
    preserve_native: bool = False
    spec = spec('wrapper.changed_text_embeddings', 'embedding_provider', diagnostics=('memfolder.wrapper.embeddings',))

    async def refresh(self, snapshot, context):
        selected = []
        for node in snapshot.records:
            if not node.text or not all(p.modality == 'text' for p in node.parts):
                continue
            present = [e for e in node.embeddings if e.space == self.space and e.values]
            if present:
                continue
            native = node.native.get('vectors', {})
            slot = self.source_slot or node.kind
            values = native.get(slot, ())
            if self.preserve_native and values:
                require(all(len(v) == self.space.dimension for v in values), 'Declared source slot dimension mismatch')
                # This opt-in is a caller declaration of the source model, not an
                # inference from vector dimensions or a verified content binding.
                continue
            require(bool(node.text), 'Text embedding provider cannot encode an empty/nontext record')
            selected.append(node)
        vectors = await resolve(context.services.require(self.service).encode(tuple(n.text for n in selected))) if selected else ()
        require(len(vectors) == len(selected), 'Content encoder returned wrong row count')
        updates = {n.node_id: replace(n, embeddings=tuple(e for e in n.embeddings if e.space != self.space) + (
            Embedding(space=self.space, source_fingerprint=n.content_fingerprint,
                values=tuple(float(v) for v in vector)),)) for n, vector in zip(selected, vectors)}
        after = replace(snapshot, records=tuple(updates.get(n.node_id, n) for n in snapshot.records))
        validate_embedding_refresh(snapshot, after)
        emit(context, self.spec.plugin_id, 'memfolder.wrapper.embeddings', nodes=tuple(updates),
            refreshed=len(updates), space=FrozenMap({'provider': self.space.provider, 'model': self.space.model,
                'revision': self.space.revision, 'dimension': self.space.dimension}), preserve_native=self.preserve_native)
        return after
