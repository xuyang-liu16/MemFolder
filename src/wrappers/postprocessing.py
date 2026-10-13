"""Graph projection is independent of text writing and native serialization."""

from collections import defaultdict
from dataclasses import dataclass, replace
from ..component_runtime import emit, resolve, spec
from ..core import (
    Embedding,
    FrozenMap,
    GraphEdge,
    fingerprint,
    result_records,
    validate_embedding_refresh,
    validate_projection,
)
from ..core.values import require


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


@dataclass(frozen=True)
class RedirectEdges:
    reduction: str = 'max'
    self_edges: bool = False
    spec = spec('wrapper.redirect_edges', 'graph_projector', diagnostics=('memfolder.wrapper.edges',))

    def project(self, source, plan, result, context):
        require(self.reduction in ('max', 'sum', 'mean'), 'Unknown edge reduction')
        records = result_records(source, plan, result)
        mapping = {n.node_id: n.node_id for n in source.records}
        outcomes = {o.action_id: o for o in result.outcomes}
        for action in plan.actions:
            outputs = outcomes[action.action_id].outputs
            require(len(outputs) <= 1, 'Supply a specialized projector for one-to-many actions')
            for node_id in action.member_ids:
                mapping[node_id] = outputs[0].node_id if outputs else None
        buckets = defaultdict(list)
        removed = []
        for edge in source.edges:
            a, b = mapping[edge.source_id], mapping[edge.target_id]
            if a is None or b is None or a == b and edge.source_id != edge.target_id and not self.self_edges:
                removed.append(edge.edge_id)
                continue
            if not edge.directed:
                a, b = sorted((a, b))
            buckets[(a, b, edge.relation, edge.directed)].append(edge)
        edges = []
        for (a, b, relation, directed), rows in buckets.items():
            # Preserve an unchanged native edge, including its identity/attributes.
            if len(rows) == 1 and (a, b) == (rows[0].source_id, rows[0].target_id):
                edges.append(rows[0])
                continue
            weights = [e.weight for e in rows]
            weight = max(weights) if self.reduction == 'max' else sum(weights)
            if self.reduction == 'mean':
                weight /= len(weights)
            edges.append(GraphEdge(edge_id='projected:' + fingerprint((a, b, relation, directed))[:32],
                source_id=a, target_id=b, relation=relation, directed=directed, weight=weight,
                extensions=FrozenMap({'memfolder.projection': {'source_edge_ids': [e.edge_id for e in rows],
                    'reduction': self.reduction}})))
        projected = replace(source, records=records, edges=tuple(edges), revision=source.revision + 1)
        validate_projection(source, plan, result, projected)
        emit(context, self.spec.plugin_id, 'memfolder.wrapper.edges', nodes=tuple(mapping),
            mapping=mapping, removed_edges=removed, edges_before=len(source.edges), edges_after=len(edges), reduction=self.reduction)
        return projected
