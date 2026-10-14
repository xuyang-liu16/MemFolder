"""Text operation requests, results and replaceable component interfaces."""

from __future__ import annotations
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Awaitable, Protocol, TypeVar, Union
from ..core import Action, FrozenMap, MemoryRecord, OperatorContext, PluginSpec, Snapshot
from ..core.values import require


class ChatTruncated(RuntimeError):
    """A structured response reached its output limit and must be split."""


@dataclass(frozen=True)
class ChatRequest:
    role: str
    prompt: str
    max_tokens: int | None = None
    temperature: float = 0.0
    message_role: str = 'user'
    response_format: str | None = None
    prompt_id: str | None = None
    require_complete: bool = False

    def __post_init__(self):
        require(self.message_role in ('system', 'user', 'assistant'), 'Invalid chat message role')
        require(self.response_format in (None, 'json_object'), 'Unsupported chat response format')
        require(type(self.require_complete) is bool,
                'Invalid chat response policy')


class Chat(Protocol):
    def complete(self, request: ChatRequest) -> str | Awaitable[str]: ...


class Tokenizer(Protocol):
    measurement_id: str
    def count(self, text: str) -> int: ...


@dataclass(frozen=True)
class Member:
    node_id: str
    text: str
    time: str


@dataclass(frozen=True)
class TextWriteResult:
    text: str
    status: str = 'success'
    reason_code: str | None = None
    usage: FrozenMap = FrozenMap()
    metadata: FrozenMap = FrozenMap()

    def __post_init__(self):
        require(type(self.text) is str, 'Text writer must return text')
        require(self.status in ('success', 'fallback'), 'Text writer status must be success or fallback')
        require(self.status != 'fallback' or bool(self.reason_code), 'Fallback needs an explicit reason')
        object.__setattr__(self, 'usage', FrozenMap(self.usage))
        object.__setattr__(self, 'metadata', FrozenMap(self.metadata))


@dataclass(frozen=True)
class Fact:
    fact: str
    question: str
    answer: str
    importance: str
    inferable: bool

    @property
    def weight(self):
        return {'high':3.,'med':2.,'low':1.}.get(self.importance.lower(),2.)*(.5 if self.inferable else 1.)

    @property
    def label(self):
        return f"[{self.importance or 'med'}{'|inferable' if self.inferable else ''}]"


@dataclass(frozen=True)
class EncodingRound:
    index: int
    encoding: str
    tokens: int
    ok: tuple[bool,...]
    facts: tuple[Fact,...]
    required: frozenset[int]

    def __post_init__(self):
        object.__setattr__(self, 'ok', tuple(self.ok))
        object.__setattr__(self, 'facts', tuple(self.facts))
        object.__setattr__(self, 'required', frozenset(self.required))
        require(len(self.ok) == len(self.facts) and all(type(v) is bool for v in self.ok), 'Round verdicts must align with facts')
        require(all(type(i) is int and 0 <= i < len(self.facts) for i in self.required), 'Round required indices are invalid')

    @property
    def must_fix(self): return tuple(i for i in self.required if not self.ok[i])
    @property
    def optional_lost(self): return tuple(i for i,ok in enumerate(self.ok) if not ok and i not in self.required)
    @property
    def weighted_recovery(self):
        return sum(f.weight for f,ok in zip(self.facts,self.ok) if ok)/max(1e-9,sum(f.weight for f in self.facts))


class Cl100kTokenizer:
    measurement_id = 'tiktoken.cl100k_base'
    def __init__(self):
        try:
            import tiktoken
        except ImportError:
            from ..core import ContractError
            raise ContractError('Install memfolder[contextfolder] for cl100k token measurement') from None
        self._encoding=tiktoken.get_encoding('cl100k_base')
    def count(self,text): return len(self._encoding.encode(text))


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
