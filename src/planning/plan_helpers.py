"""Shared geometry, partition and budget boundaries; no backend imports."""

from __future__ import annotations
from dataclasses import dataclass, replace
from functools import cached_property
from ..component_runtime import emit, resolve, spec
from .contracts import AnchorSelection, Group
from ..core import (
    Action,
    ActionPlan,
    ContractError,
    FrozenMap,
    fingerprint,
    validate_features,
    validate_plan,
)
from ..core.values import require


def numpy():
    try:
        import numpy as np
        require(callable(getattr(np, 'asarray', None)), 'Install memfolder[algorithms] for vector planners')
        return np
    except ImportError:
        raise ContractError('Install memfolder[algorithms] for vector planners') from None


def selection_request(request, operation):
    require(operation in ('drop', 'merge'), 'Invalid selection operation')
    return replace(request, extensions=FrozenMap({**request.extensions,
        'memfolder.selection': {'operation': operation}}))


def selection_required(request, nodes, *, default='drop'):
    operation = request.extensions.get('memfolder.selection', {}).get('operation', default)
    require(operation in ('drop', 'merge'), 'Invalid selection operation')
    return tuple(n for n in nodes if not getattr(n.retention, 'may_' + operation))


def check_anchors(request,nodes,selection,target):
    require(isinstance(selection,AnchorSelection),'Anchor selector must return AnchorSelection')
    require(selection.input_fingerprint==request.snapshot.fingerprint,'Stale anchor selection')
    require(len(selection.selected_ids)==target and len(set(selection.selected_ids))==target,'Selector missed exact anchor target')
    require(set(selection.selected_ids)<={n.node_id for n in nodes},'Anchor selector crossed budget groups')


def check_groups(nodes, groups, *, target=None):
    ids = [n.node_id for n in nodes]
    flat = [i for g in groups for i in g.member_ids]
    require(len(flat) == len(set(flat)) and set(flat) == set(ids), 'Partition must cover nodes exactly once')
    require(len({g.anchor_id for g in groups}) == len(groups)
            and all(g.anchor_id in g.member_ids for g in groups), 'Invalid partition anchors')
    require(target is None or len(groups) == target, 'Partition missed its node target')


def ordered_nodes(request):
    return tuple(sorted((n for n in request.snapshot.records if n.eligible), key=lambda n: (n.order, n.node_id)))


def node_targets(request):
    """Current members of resolved node groups. Initial scope budgets survive revisions.

    Global groups are accepted only within one scope. Custom groups use stable origin
    membership recorded by the caller on revised snapshots; never guess allocation.
    """
    budgets = [b for b in request.budgets if b.request.unit == 'nodes']
    require(len(budgets) == 1, 'Planner needs exactly one resolved node budget')
    budget = budgets[0]
    require(budget.request.enforcement != 'advisory', 'Planner needs an enforced node budget')
    nodes = ordered_nodes(request)
    if budget.request.allocation == 'scope':
        by_scope = {}
        for n in nodes:
            by_scope.setdefault(fingerprint(n.scope), []).append(n)
        targets = {t.group.group_id: t.limit for t in budget.targets}
        require(set(by_scope) <= set(targets), 'Current snapshot introduces an unbudgeted scope')
        groups = [(key, tuple(rows), min(len(rows), targets[key])) for key, rows in by_scope.items()]
    else:
        by_id = {n.node_id: n for n in nodes}
        groups = []
        membership=request.extensions.get('memfolder.budget_membership')
        for t in budget.targets:
            if membership is not None and budget.request.reference=='initial':
                rows=[]
                for n in nodes:
                    owners={membership.get(fingerprint(o)) for o in n.origins}
                    require(len(owners)==1 and None not in owners,'Node crosses or escapes original budget membership')
                    if next(iter(owners))==t.group.group_id:rows.append(n)
                rows=tuple(rows)
            else:
                require(set(t.group.member_ids) <= set(by_id),
                        'Revised custom/global budgets require explicit origin membership or resolution for current nodes')
                rows = tuple(by_id[i] for i in t.group.member_ids)
            groups.append((t.group.group_id, rows, min(len(rows), t.limit)))
    seen = [n.node_id for _, rows, _ in groups for n in rows]
    require(set(seen) == {n.node_id for n in nodes} and len(seen) == len(set(seen)), 'Budget groups omit/overlap current nodes')
    return tuple(groups)


def feature(request, name, ids):
    batches = [b for b in request.features if b.name == name]
    require(len(batches) == 1, 'Missing or ambiguous feature batch: ' + name)
    validate_features(request.snapshot, batches[0], required_ids=tuple(ids))
    return batches[0]


@dataclass(frozen=True)
class Geometry:
    node_ids: tuple[str, ...]
    vectors: object  # private ndarray, never part of public wire/observations

    @classmethod
    def of(cls, request, nodes, feature_name='semantic', *, dtype='float64'):
        np = numpy()
        ids = tuple(n.node_id for n in nodes)
        batch = feature(request, feature_name, ids)
        require(batch.space is not None and batch.space.metric == 'cosine', 'Geometry needs a declared cosine space')
        by_id = {r.node_id: r for r in batch.rows}
        matrix = np.asarray([by_id[i].vector for i in ids], dtype=dtype)
        require(matrix.shape == (len(ids), batch.space.dimension) and np.all(np.isfinite(matrix)),
                'Geometry needs finite inline vectors; resolve artifacts through a feature provider')
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / np.clip(norms, 1e-12, None)  # matches RecordFolder reference, including zero rows
        matrix.setflags(write=False)
        return cls(ids, matrix)

    @cached_property
    def cosine(self):
        np = numpy()
        matrix = np.clip(self.vectors @ self.vectors.T, -1.0, 1.0)
        matrix.setflags(write=False)
        return matrix


def subset_request(request, nodes):
    """Keep the authoritative snapshot fingerprint; subcomponents use explicit IDs."""
    return replace(request, extensions=FrozenMap({**request.extensions,
        'memfolder.planning': {'node_ids': [n.node_id for n in nodes]}}))


def component_nodes(request):
    ids = request.extensions.get('memfolder.planning', {}).get('node_ids')
    nodes = {n.node_id: n for n in ordered_nodes(request)}
    return tuple(nodes[i] for i in ids) if ids is not None else tuple(nodes.values())


def plan_groups(request, groups, *, method, rewrite_singletons=False, input_view='original', orders=None):
    nodes = {n.node_id: n for n in ordered_nodes(request)}
    check_groups(tuple(nodes.values()), groups)
    actions = []
    for position, g in enumerate(groups):
        members = tuple(nodes[i] for i in g.member_ids)
        kind = 'merge' if len(members) > 1 else ('rewrite' if rewrite_singletons and members[0].retention.may_rewrite else 'keep')
        parameters = {'anchor_id': g.anchor_id}
        if orders is not None:
            parameters['output_order'] = orders[g.anchor_id]
        actions.append(Action(action_id='action.' + fingerprint((request.run_id, request.round_index, method, g.member_ids))[:24],
            kind=kind, member_ids=g.member_ids, output_ids=(g.anchor_id,),
            input_view=input_view, reason_codes=(method,), parameters=FrozenMap(parameters)))
    plan = ActionPlan(plan_id=method + '.' + fingerprint((request.run_id, request.round_index, request.snapshot.fingerprint))[:24],
        input_fingerprint=request.snapshot.fingerprint, target_ids=tuple(nodes), actions=tuple(actions),
        extensions=FrozenMap({'memfolder.method': method, 'memfolder.round': request.round_index}))
    validate_plan(request.snapshot, plan)
    return plan


def plan_prune(request, retained, *, method):
    nodes = ordered_nodes(request)
    require(set(retained) <= {n.node_id for n in nodes}, 'Selector returned unknown retained IDs')
    actions = tuple(Action(action_id='action.' + fingerprint((request.run_id, request.round_index, method, n.node_id))[:24],
        kind='keep' if n.node_id in retained else 'drop', member_ids=(n.node_id,),
        output_ids=(n.node_id,) if n.node_id in retained else (), reason_codes=(method,)) for n in nodes)
    plan = ActionPlan(plan_id=method + '.' + fingerprint((request.run_id, request.round_index, request.snapshot.fingerprint))[:24],
        input_fingerprint=request.snapshot.fingerprint, target_ids=tuple(n.node_id for n in nodes), actions=actions,
        extensions=FrozenMap({'memfolder.method': method}))
    validate_plan(request.snapshot, plan)
    return plan
