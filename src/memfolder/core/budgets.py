"""Explicit budget units, rounding, allocation, and enforcement."""
from __future__ import annotations
from collections.abc import Mapping
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP
from .memory import Snapshot
from .values import Contract, FrozenMap, digest, fingerprint, identifier, record, require


@record('memfolder.budget_request')
class BudgetRequest(Contract):
    unit: str  # nodes/tokens/words/characters/bytes/edges or namespaced custom unit
    limit: int | None = None
    ratio: float | None = None
    allocation: str = 'scope'  # global/scope/group
    rounding: str = 'half_even'
    minimum: int = 0
    enforcement: str = 'exact'  # exact/at_most/advisory
    reference: str = 'initial'  # runtime selects this snapshot once or every round explicitly
    measurement_id: str | None = None
    extensions: FrozenMap = FrozenMap()

    def __post_init__(self):
        super().__post_init__()
        require(self.unit in {'nodes', 'tokens', 'words', 'characters', 'bytes', 'edges'} or '.' in self.unit, 'Unknown budget unit')
        require((self.limit is None) != (self.ratio is None), 'Choose an absolute limit or ratio')
        require(self.limit is None or self.limit >= 0, 'Negative budget')
        require(self.ratio is None or 0 <= self.ratio <= 1, 'Budget ratio must be in [0,1]')
        require(self.minimum >= 0, 'Negative minimum')
        require(self.allocation in {'global', 'scope', 'group'}, 'Unknown budget allocation')
        require(self.rounding in ROUNDINGS, 'Unknown rounding rule')
        require(self.enforcement in {'exact', 'at_most', 'advisory'}, 'Unknown budget enforcement')
        require(self.reference in {'initial', 'current'}, 'Unknown budget reference')
        require(self.unit in {'nodes', 'characters'} or bool(self.measurement_id), 'Custom/text measurements must declare tokenizer/measurement identity')


ROUNDINGS = {'half_even': ROUND_HALF_EVEN, 'half_up': ROUND_HALF_UP, 'floor': ROUND_FLOOR, 'ceil': ROUND_CEILING}


@record('memfolder.budget_group')
class BudgetGroup(Contract):
    group_id: str
    member_ids: tuple[str, ...]

    def __post_init__(self):
        super().__post_init__()
        identifier(self.group_id)
        require(len(set(self.member_ids)) == len(self.member_ids), 'Duplicate budget group members')


@record('memfolder.budget_target')
class BudgetTarget(Contract):
    group: BudgetGroup
    input_amount: int
    limit: int

    def __post_init__(self):
        super().__post_init__()
        require(self.input_amount >= 0 and self.limit >= 0, 'Negative budget target')


@record('memfolder.resolved_budget')
class ResolvedBudget(Contract):
    request: BudgetRequest
    reference_fingerprint: str
    targets: tuple[BudgetTarget, ...]

    def __post_init__(self):
        super().__post_init__()
        digest(self.reference_fingerprint)
        require(len({t.group.group_id for t in self.targets}) == len(self.targets), 'Duplicate budget groups')
        members = [nid for t in self.targets for nid in t.group.member_ids]
        require(len(set(members)) == len(members), 'Overlapping budget groups')


def resolve_budget(snapshot: Snapshot, request: BudgetRequest, *, groups: tuple[BudgetGroup, ...] | None = None,
                   measurements: Mapping[str, int] | None = None) -> ResolvedBudget:
    records = {n.node_id: n for n in snapshot.records if n.eligible}
    if request.allocation == 'group':
        require(groups is not None, 'Group allocation requires explicit groups')
    else:
        require(groups is None, 'Groups only apply to group allocation')
        if request.allocation == 'global':
            groups = (BudgetGroup(group_id='global', member_ids=tuple(records)),)
        else:
            scopes = dict.fromkeys(n.scope for n in records.values())
            groups = tuple(BudgetGroup(group_id=fingerprint(scope), member_ids=tuple(n.node_id for n in records.values() if n.scope == scope)) for scope in scopes)
    members = [nid for g in groups for nid in g.member_ids]
    require(len(set(members)) == len(members) and set(members) == set(records), 'Budget groups must partition eligible nodes')
    if request.unit == 'nodes':
        require(measurements is None, 'Node measurements are defined as one per eligible node')
        amounts = {nid: 1 for nid in records}
    elif request.unit == 'characters':
        require(measurements is None, 'Character unit uses Python Unicode code points')
        amounts = {nid: len(n.text) for nid, n in records.items()}
    else:
        require(measurements is not None and set(measurements) == set(records), 'Supply explicit measurement for every eligible node')
        require(all(type(v) is int and v >= 0 for v in measurements.values()), 'Measurements must be nonnegative integers')
        amounts = dict(measurements)
    targets = []
    for group in groups:
        amount = sum(amounts[i] for i in group.member_ids)
        limit = request.limit if request.limit is not None else int((Decimal(str(request.ratio)) * amount).to_integral_value(rounding=ROUNDINGS[request.rounding]))
        limit = max(request.minimum, limit)
        if request.enforcement == 'exact':
            require(limit <= amount, 'Exact budget exceeds input amount')
        if request.unit == 'nodes' and request.enforcement != 'advisory':
            locked = sum(not records[i].retention.may_drop and not records[i].retention.may_merge for i in group.member_ids)
            require(limit >= locked, 'Node budget is below locked-node count')
        targets.append(BudgetTarget(group=group, input_amount=amount, limit=limit))
    return ResolvedBudget(request=request, reference_fingerprint=snapshot.fingerprint, targets=tuple(targets))


def validate_budget(budget: ResolvedBudget, realized: Mapping[str, int]) -> None:
    require(set(realized) == {t.group.group_id for t in budget.targets}, 'Missing/unknown realized budget groups')
    require(all(type(v) is int and v >= 0 for v in realized.values()), 'Invalid realized amount')
    for target in budget.targets:
        amount = realized[target.group.group_id]
        if budget.request.enforcement == 'exact':
            require(amount == target.limit, 'Exact budget not reached')
        elif budget.request.enforcement == 'at_most':
            require(amount <= target.limit, 'Budget exceeded')
