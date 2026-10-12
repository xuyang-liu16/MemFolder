"""Structural interfaces for independently contributed planning stages.

Stages may return a value or an awaitable. No inheritance or builtin method name
is required; the registry checks ``spec.role`` and the callable at construction.
"""
from __future__ import annotations

from typing import Awaitable, Protocol, TypeVar, Union
from collections.abc import Mapping, Sequence
from ..core import (AlgorithmContext, CandidateBatch, CandidateSelection, FeatureBatch,
    MemoryRecord, PlanningRequest, PluginSpec, Snapshot)
from .common import AnchorSelection, Group

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
