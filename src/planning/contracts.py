"""Planning stage interfaces and immutable selection/group results."""

from __future__ import annotations
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Awaitable, Protocol, TypeVar, Union
from ..core import (
    AlgorithmContext,
    CandidateBatch,
    CandidateSelection,
    FeatureBatch,
    MemoryRecord,
    PlanningRequest,
    PluginSpec,
    Snapshot,
)
from ..core.values import identifier, require


@dataclass(frozen=True)
class Group:
    anchor_id: str
    member_ids: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, 'member_ids', tuple(self.member_ids))
        identifier(self.anchor_id)
        require(bool(self.member_ids) and len(set(self.member_ids)) == len(self.member_ids), 'Group members must be unique and nonempty')
        for value in self.member_ids:
            identifier(value)
        require(self.anchor_id in self.member_ids, 'Anchor must be a real group member')


@dataclass(frozen=True)
class AnchorSelection:
    """Shared selection output, usable by prune and merge/group planners alike."""
    input_fingerprint: str
    selected_ids: tuple[str,...]

    def __post_init__(self):
        object.__setattr__(self, 'selected_ids', tuple(self.selected_ids))
        require(type(self.input_fingerprint) is str and len(self.input_fingerprint) == 64, 'Selection needs a snapshot digest')
        require(len(set(self.selected_ids)) == len(self.selected_ids), 'Selected IDs must be unique')
        for value in self.selected_ids:
            identifier(value)


T = TypeVar('T')


Result = Union[T, Awaitable[T]]


class FeatureProvider(Protocol):
    spec: PluginSpec
    def extract(self, snapshot: Snapshot, context: AlgorithmContext) -> Result[FeatureBatch]: ...


class AnchorSelector(Protocol):
    spec: PluginSpec
    def select(self, request: PlanningRequest, target: int, context: AlgorithmContext) -> Result[AnchorSelection]: ...


class GroupAssigner(Protocol):
    spec: PluginSpec
    def assign(self, request: PlanningRequest, selection: AnchorSelection, context: AlgorithmContext) -> Result[Sequence[Group]]: ...


class Partitioner(Protocol):
    spec: PluginSpec
    def partition(self, request: PlanningRequest, target: int, context: AlgorithmContext) -> Result[Sequence[Group]]: ...


class GroupRouter(Protocol):
    spec: PluginSpec
    def route(self, request: PlanningRequest, base: Sequence[Group], candidates: CandidateBatch,
              selection: CandidateSelection, context: AlgorithmContext) -> Result[Sequence[Group]]: ...


class BudgetAllocator(Protocol):
    spec: PluginSpec
    def allocate(self, groups: Sequence[Group], target: int, context: AlgorithmContext) -> Result[Mapping[str, int]]: ...


class PairRouter(Protocol):
    spec: PluginSpec
    def pair(self, request: PlanningRequest, nodes: Sequence[MemoryRecord], context: AlgorithmContext) -> Result[Group]: ...


class GraphClassifier(Protocol):
    spec: PluginSpec
    def classify(self, request: PlanningRequest, context: AlgorithmContext) -> Result[tuple[Sequence[str], Sequence[str], Mapping[str, float]]]: ...


class GraphCoverageSelector(Protocol):
    spec: PluginSpec
    def select(self, request: PlanningRequest, ids: Sequence[str], context: AlgorithmContext) -> Result[Sequence[str]]: ...


class GraphImportanceSelector(Protocol):
    spec: PluginSpec
    def select(self, request: PlanningRequest, ids: Sequence[str], importance: Mapping[str, float],
               context: AlgorithmContext) -> Result[Sequence[str]]: ...


__all__ = ['FeatureProvider', 'AnchorSelector', 'GroupAssigner', 'Partitioner',
           'GroupRouter', 'BudgetAllocator', 'PairRouter', 'GraphClassifier',
           'GraphCoverageSelector', 'GraphImportanceSelector']
