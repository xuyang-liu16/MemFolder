"""Method-neutral actions. Planning, execution, and graph materialization stay separate."""
from __future__ import annotations
from collections.abc import Mapping
from types import MappingProxyType
from functools import cached_property
from .memory import ArtifactRef, MemoryRecord, ScopeRef, Snapshot
from .values import Contract, FrozenMap, digest, fingerprint, identifier, record, require


@record('memfolder.action')
class Action(Contract):
    action_id: str
    kind: str  # builtins or an explicitly declared namespaced custom action
    member_ids: tuple[str, ...]
    output_ids: tuple[str, ...] = ()
    input_view: str = 'current'  # original/current, or namespaced custom view
    output_scope: ScopeRef | None = None
    reason_codes: tuple[str, ...] = ()
    diagnostic_refs: tuple[ArtifactRef, ...] = ()
    parameters: FrozenMap = FrozenMap()
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        for v in (self.action_id, self.kind, self.input_view, *self.member_ids, *self.output_ids):
            identifier(v)
        require(bool(self.member_ids) and len(set(self.member_ids)) == len(self.member_ids), 'Invalid action membership')
        require(len(set(self.output_ids)) == len(self.output_ids), 'Duplicate action outputs')
        require(self.kind in BUILTIN_RULES or '.' in self.kind, 'Custom action kinds require a namespace')
        require(self.input_view in {'original', 'current'} or '.' in self.input_view, 'Custom input views require a namespace')


@record('memfolder.action_rule')
class ActionRule(Contract):
    min_members: int
    max_members: int | None
    min_outputs: int
    max_outputs: int | None
    permissions: tuple[str, ...] = ()
    preserves_records: bool = False
    conserves_lineage: bool = True

    def __post_init__(self):
        super().__post_init__()
        require(self.min_members >= 1 and self.min_outputs >= 0, 'Invalid action arity')
        require(self.max_members is None or self.max_members >= self.min_members, 'Invalid member bounds')
        require(self.max_outputs is None or self.max_outputs >= self.min_outputs, 'Invalid output bounds')
        require(set(self.permissions) <= {'drop', 'merge', 'rewrite'}, 'Unknown retention permission')


BUILTIN_RULES = MappingProxyType({
    'keep': ActionRule(min_members=1, max_members=1, min_outputs=1, max_outputs=1, preserves_records=True),
    'drop': ActionRule(min_members=1, max_members=1, min_outputs=0, max_outputs=0, permissions=('drop',), conserves_lineage=False),
    'merge': ActionRule(min_members=2, max_members=None, min_outputs=1, max_outputs=1, permissions=('merge',)),
    'rewrite': ActionRule(min_members=1, max_members=1, min_outputs=1, max_outputs=1, permissions=('rewrite',)),
})


def action_rules(custom: Mapping[str, ActionRule] | None = None) -> dict[str, ActionRule]:
    custom = dict(custom or {})
    require(not set(custom) & set(BUILTIN_RULES), 'Builtin action semantics cannot be replaced')
    require(all('.' in k and type(v) is ActionRule for k, v in custom.items()), 'Custom rules need namespace and ActionRule')
    return {**BUILTIN_RULES, **custom}


@record('memfolder.action_plan')
class ActionPlan(Contract):
    plan_id: str
    input_fingerprint: str
    target_ids: tuple[str, ...]  # explicitly selected batch; every target has exactly one action
    actions: tuple[Action, ...]
    boundary: str = 'scope'  # sample permits explicit same-sample cross-partition consolidation
    state_ref: ArtifactRef | None = None
    diagnostic_refs: tuple[ArtifactRef, ...] = ()
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.plan_id)
        digest(self.input_fingerprint)
        require(self.boundary in {'scope', 'sample'}, 'Unknown plan boundary')
        require(len(set(self.target_ids)) == len(self.target_ids), 'Duplicate targets')
        require(len({a.action_id for a in self.actions}) == len(self.actions), 'Duplicate action IDs')

    @cached_property
    def fingerprint(self):
        return fingerprint(self)


def validate_plan(snapshot: Snapshot, plan: ActionPlan, *, custom_rules: Mapping[str, ActionRule] | None = None,
                  allowed_boundary: str = 'scope') -> None:
    require(snapshot.fingerprint == plan.input_fingerprint, 'Stale plan input')
    require(plan.boundary == 'scope' or allowed_boundary == 'sample', 'Cross-scope execution was not authorized')
    source = {n.node_id: n for n in snapshot.records}
    targets = set(plan.target_ids)
    require(targets <= set(source), 'Unknown plan targets')
    require(all(source[i].eligible for i in targets), 'Plan targets ineligible assets/nodes')
    rules = action_rules(custom_rules)
    used, outputs = [], []
    for action in plan.actions:
        require(action.kind in rules, f'Undeclared action kind: {action.kind}')
        rule = rules[action.kind]
        require(rule.min_members <= len(action.member_ids) and (rule.max_members is None or len(action.member_ids) <= rule.max_members), 'Invalid action member arity')
        require(rule.min_outputs <= len(action.output_ids) and (rule.max_outputs is None or len(action.output_ids) <= rule.max_outputs), 'Invalid action output arity')
        require(set(action.member_ids) <= targets, 'Action uses unknown/untargeted member')
        members = [source[i] for i in action.member_ids]
        scopes = {n.scope for n in members}
        require(len({(s.dataset_id, s.sample_id) for s in scopes}) == 1, 'Action crosses dataset/sample')
        if plan.boundary == 'scope':
            require(len(scopes) == 1, 'Action crosses scope')
        if len(scopes) > 1:
            require(action.output_scope is not None, 'Cross-scope output requires an explicit scope')
        if action.output_scope is not None:
            require((action.output_scope.dataset_id, action.output_scope.sample_id)
                    == (members[0].scope.dataset_id, members[0].scope.sample_id), 'Output scope crosses sample')
            require(plan.boundary == 'sample' or action.output_scope == members[0].scope, 'Output scope changed')
        for n in members:
            require(all(getattr(n.retention, 'may_' + p) for p in rule.permissions), 'Action violates retention policy')
            if not rule.preserves_records and action.kind not in BUILTIN_RULES:
                require(n.retention.may_drop and n.retention.may_merge and n.retention.may_rewrite, 'Custom transform cannot bypass retention policy')
        if rule.preserves_records:
            require(set(action.output_ids) == set(action.member_ids), 'Preserving action must keep IDs')
        used.extend(action.member_ids)
        outputs.extend(action.output_ids)
    require(len(used) == len(set(used)) and set(used) == targets, 'Targets must be covered exactly once')
    require(len(outputs) == len(set(outputs)), 'Overlapping output IDs')
    require(not set(outputs) & (set(source) - targets), 'Output overwrites an untouched record')


@record('memfolder.action_outcome')
class ActionOutcome(Contract):
    action_id: str
    status: str  # success/fallback/failed
    outputs: tuple[MemoryRecord, ...] = ()
    reason_code: str | None = None
    diagnostic_refs: tuple[ArtifactRef, ...] = ()
    usage: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        identifier(self.action_id)
        require(self.status in {'success', 'fallback', 'failed'}, 'Invalid action outcome')
        require(self.status == 'success' or bool(self.reason_code), 'Fallback/failure needs an explicit reason')
        require(self.status != 'failed' or not self.outputs, 'Failed action cannot claim committed outputs')


@record('memfolder.operator_result')
class OperatorResult(Contract):
    plan_fingerprint: str
    outcomes: tuple[ActionOutcome, ...]
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        digest(self.plan_fingerprint)
        require(len({o.action_id for o in self.outcomes}) == len(self.outcomes), 'Duplicate outcomes')
        ids = [n.node_id for o in self.outcomes for n in o.outputs]
        require(len(set(ids)) == len(ids), 'Duplicate result node IDs')

    @property
    def outputs(self):
        return tuple(n for o in self.outcomes for n in o.outputs)


def validate_result(snapshot: Snapshot, plan: ActionPlan, result: OperatorResult, *,
                    custom_rules: Mapping[str, ActionRule] | None = None, allowed_boundary: str = 'scope') -> None:
    validate_plan(snapshot, plan, custom_rules=custom_rules, allowed_boundary=allowed_boundary)
    require(result.plan_fingerprint == plan.fingerprint, 'Result belongs to a different plan')
    actions = {a.action_id: a for a in plan.actions}
    require({o.action_id for o in result.outcomes} == set(actions), 'Incomplete/unknown action outcomes')
    source = {n.node_id: n for n in snapshot.records}
    rules = action_rules(custom_rules)
    for outcome in result.outcomes:
        action = actions[outcome.action_id]
        rule = rules[action.kind]
        require(outcome.status != 'failed', 'Failed actions require runtime failure handling, not materialization')
        require({n.node_id for n in outcome.outputs} == set(action.output_ids), 'Outputs differ from plan')
        members = [source[i] for i in action.member_ids]
        origins = {origin for n in members for origin in n.origins}
        produced = {origin for n in outcome.outputs for origin in n.origins}
        require(produced <= origins, 'Operator invented origins')
        if rule.conserves_lineage:
            require(produced == origins, 'Operator lost lineage')
        for output in outcome.outputs:
            require(output.scope == (action.output_scope or members[0].scope), 'Operator changed output scope')
            require(output.eligible, 'Operator cannot hide outputs from eligibility/budget accounting')
            if rule.preserves_records:
                require(output == source[output.node_id], 'Keep/preserving action changed record semantics')
                continue
            contributors = [n for n in members if set(n.origins) & set(output.origins)]
            for permission in ('drop', 'merge', 'rewrite'):
                require(all(getattr(n.retention, 'may_' + permission) for n in contributors)
                        or not getattr(output.retention, 'may_' + permission), 'Operator weakened retention policy')
            for field, comparison in (('available_at', max), ('expires_at', min)):
                bounds = [getattr(n, field) for n in contributors if getattr(n, field) is not None]
                if bounds:
                    bound = getattr(output, field)
                    require(len({b.clock for b in bounds}) == 1 and bound is not None and bound.clock == bounds[0].clock, 'Operator lost/mixed visibility clocks')
                    target = comparison(b.value for b in bounds)
                    require(bound.value >= target if field == 'available_at' else bound.value <= target, 'Operator widened memory visibility')


def result_records(snapshot: Snapshot, plan: ActionPlan, result: OperatorResult, **validation_options) -> tuple[MemoryRecord, ...]:
    """Node overlay only. Wrapper decides edge mapping and backend commit."""
    validate_result(snapshot, plan, result, **validation_options)
    targets = set(plan.target_ids)
    return tuple(n for n in snapshot.records if n.node_id not in targets) + result.outputs


def validate_projection(source: Snapshot, plan: ActionPlan, result: OperatorResult, projected: Snapshot, **options) -> None:
    expected = {n.node_id: n for n in result_records(source, plan, result, **options)}
    require({n.node_id: n for n in projected.records} == expected, 'Wrapper projection changed compression records')
    require(projected.assets == source.assets, 'Wrapper projection lost carried assets')
    require(projected.revision > source.revision, 'Projected snapshot must advance revision')
    # Snapshot already rejects dangling edges. Relation mapping is wrapper-owned.


def validate_embedding_refresh(before: Snapshot, after: Snapshot) -> None:
    from dataclasses import replace
    require(before.snapshot_id == after.snapshot_id and before.revision == after.revision
            and before.edges == after.edges and before.assets == after.assets and before.extensions == after.extensions,
            'Embedding refresh changed snapshot structure')
    source = {n.node_id: n for n in before.records}
    require({n.node_id for n in after.records} == set(source), 'Embedding refresh changed node IDs')
    for n in after.records:
        require(replace(n, embeddings=source[n.node_id].embeddings) == source[n.node_id], 'Embedding refresh changed memory semantics')
