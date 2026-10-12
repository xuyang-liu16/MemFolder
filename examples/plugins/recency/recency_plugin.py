"""A contributor's selector, usable as prune selection or merge anchors.

This pedagogical recency rule uses declared canonical order; it is not one of
the paper baselines. It can be installed without modifying MemFolder files.
"""
from dataclasses import dataclass
from memfolder.core import PluginSpec, ContractError
from memfolder.planning import AnchorSelection, component_nodes, selection_required


@dataclass(frozen=True)
class RecencySelector:
    newest_first: bool = True
    spec = PluginSpec(plugin_id='example.recency', role='anchor_selector', api_version=1)

    async def select(self, request, target, context):
        nodes = component_nodes(request)
        required = tuple(n.node_id for n in selection_required(request, nodes))
        if not len(required) <= target <= len(nodes):
            raise ContractError('Recency target cannot preserve protected records')
        optional = sorted((n for n in nodes if n.node_id not in required),
            key=lambda n: (n.order, n.node_id), reverse=self.newest_first)
        return AnchorSelection(request.snapshot.fingerprint,
            required + tuple(n.node_id for n in optional[:target - len(required)]))


def build(parameters, *, context):
    if set(parameters) - {'newest_first'}:
        raise ContractError('Unknown recency parameter')
    value = parameters.get('newest_first', True)
    if type(value) is not bool:
        raise ContractError('newest_first must be boolean')
    return RecencySelector(value)


build.spec = RecencySelector.spec
