"""Typed replacement points for text compression and ContextFolder's loop."""
from __future__ import annotations
from collections.abc import Sequence
from typing import Awaitable, Protocol, TypeVar, Union
from ..core import Action, MemoryRecord, OperatorContext, PluginSpec, Snapshot
from .types import EncodingRound, Fact, Member, TextWriteResult

T = TypeVar('T')
Result = Union[T, Awaitable[T]]


class MemberResolver(Protocol):
    spec: PluginSpec
    def resolve(self, action: Action, snapshot: Snapshot, context: OperatorContext) -> Result[tuple[Sequence[MemoryRecord], Sequence[Member]]]: ...


class TextWriter(Protocol):
    spec: PluginSpec
    def write(self, members: Sequence[Member], action: Action, context: OperatorContext) -> Result[TextWriteResult]: ...


class RecordBuilder(Protocol):
    spec: PluginSpec
    def build(self, inputs: Sequence[MemoryRecord], action: Action, written: TextWriteResult,
              context: OperatorContext) -> Result[MemoryRecord]: ...


class FactExtractor(Protocol):
    spec: PluginSpec
    def extract(self, lines: str, context: OperatorContext) -> Result[Sequence[Fact]]: ...


class TriagePolicy(Protocol):
    spec: PluginSpec
    def required(self, facts: Sequence[Fact], ratio: float, context: OperatorContext) -> Result[Sequence[int]]: ...


class Compiler(Protocol):
    spec: PluginSpec
    def compile(self, lines: str, n: int, facts: Sequence[Fact], source_tokens: int,
                target: int, feedback: str, context: OperatorContext) -> Result[str]: ...


class Verifier(Protocol):
    spec: PluginSpec
    def verify(self, encoding: str, facts: Sequence[Fact], context: OperatorContext) -> Result[Sequence[bool]]: ...


class FeedbackBuilder(Protocol):
    spec: PluginSpec
    def feedback(self, round_: EncodingRound, target: int, context: OperatorContext) -> Result[str]: ...


class RoundSelector(Protocol):
    spec: PluginSpec
    def choose(self, rounds: Sequence[EncodingRound], context: OperatorContext) -> Result[EncodingRound]: ...


__all__ = ['MemberResolver', 'TextWriter', 'RecordBuilder', 'FactExtractor',
           'TriagePolicy', 'Compiler', 'Verifier', 'FeedbackBuilder', 'RoundSelector']
