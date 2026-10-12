"""Graph projection is independent of text writing and native serialization."""
from dataclasses import dataclass, replace
from collections import defaultdict
from ..core import GraphEdge, FrozenMap, fingerprint, result_records, validate_projection
from ..core.values import require
from ..planning.common import emit, spec


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
