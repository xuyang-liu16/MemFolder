"""The planner: a group's text becomes a list of checkable facts.

Each fact carries a verification question (so the verifier can test whether it
survived), an importance label and an ``inferable`` flag.  Those two labels are
the whole basis of triage -- they decide which facts the compiler is told to
protect and which losses the loop is allowed to accept.

Importance is the planner's own judgement, requested in the prompt:

    high   key events, final states, exact dates/numbers/names, entity
           bindings, negations
    med    preferences, plans, relation directions, quantities
    low    reasons, modifiers, emotional framing, superseded older states

``inferable`` marks a fact a reader could re-derive from the *other* facts or
from common knowledge.  An inferable fact is never required and is worth half
as much, however important it looks: spending tokens on it buys nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..llm import ChatClient, extract_json
from . import prompts

#: Importance -> weight, for the tie-break among rounds that all lose something.
WEIGHTS = {"high": 3.0, "med": 2.0, "low": 1.0}

#: Below this target ratio only `high` facts are required; at or above it,
#: `med` is required too.  A tighter budget cannot afford to protect as much.
STRICT_BELOW_RATIO = 0.65


@dataclass(frozen=True)
class Fact:
    """One atomic fact, with the question that tests whether it survived."""

    fact: str
    question: str
    answer: str
    importance: str
    inferable: bool

    @property
    def weight(self) -> float:
        """How much losing this fact costs, used only to rank unclean rounds."""
        return WEIGHTS.get(self.importance.lower(), WEIGHTS["med"]) * (0.5 if self.inferable else 1.0)

    @property
    def label(self) -> str:
        """``[high]`` / ``[med|inferable]`` -- how the compiler sees the fact."""
        return f"[{self.importance or 'med'}{'|inferable' if self.inferable else ''}]"


def json_or_empty(raw: str) -> dict[str, Any]:
    """Parse a JSON object, or give up quietly.

    Every caller in this module degrades gracefully on an empty dict -- no
    facts means the one-shot fallback, no answers means "nothing was
    recovered" and another round.  Raising here would turn a single malformed
    completion into a failed run of several thousand groups.
    """
    try:
        value = extract_json(raw)
    except Exception:  # noqa: BLE001 - any parse failure is simply "no answer"
        return {}
    return value if isinstance(value, dict) else {}


def extract_facts(chat: ChatClient, lines: str, *, sample: int = 0, max_tokens: int = 1500) -> list[Fact]:
    """The planner call: group text -> checkable facts. One request."""
    answer = chat.complete(
        prompts.FACT_EXTRACT.format(lines=lines), sample=sample, max_tokens=max_tokens
    )
    return parse_facts(json_or_empty(answer))


def parse_facts(payload: Mapping[str, Any]) -> list[Fact]:
    """Read the planner's JSON answer.

    A fact without a question cannot be verified, so it is dropped rather than
    trusted.  The ``importance`` default differs on purpose between
    :attr:`Fact.weight` (``med``) and :func:`required_facts` (neither): an
    unlabelled fact still counts toward the recovery score, but is never
    something the compiler is forced to repair.  This is the locked behaviour;
    aligning the two defaults changes which rounds count as clean.
    """
    raw = payload.get("facts")
    if not isinstance(raw, Sequence):
        return []
    facts = []
    for item in raw:
        if not isinstance(item, Mapping) or not item.get("question"):
            continue
        facts.append(
            Fact(
                fact=str(item.get("fact", "")),
                question=str(item["question"]),
                answer=str(item.get("answer", "")),
                importance=str(item.get("importance", "")).lower(),
                inferable=bool(item.get("inferable")),
            )
        )
    return facts


def required_facts(facts: Sequence[Fact], target_ratio: float) -> set[int]:
    """Indices the compiler is not allowed to lose.

    Required means important *and* not inferable.  How much counts as important
    depends on the budget: a run that keeps 80% of the tokens can protect both
    ``high`` and ``med``, one that keeps 60% can only protect ``high``.
    """
    levels = {"high"} if target_ratio < STRICT_BELOW_RATIO else {"high", "med"}
    return {
        index
        for index, fact in enumerate(facts)
        if fact.importance in levels and not fact.inferable
    }


def render_questions(facts: Sequence[Fact]) -> str:
    return "\n".join(f"{i + 1}. {fact.question}" for i, fact in enumerate(facts))


def render_reference(facts: Sequence[Fact]) -> str:
    """The judge's crib sheet: what each question was meant to be about."""
    return "\n".join(
        f"{i + 1}. fact: {fact.fact} | expected: {fact.answer}" for i, fact in enumerate(facts)
    )


def render_triage(facts: Sequence[Fact]) -> str:
    """The compiler's budget sheet: every fact with its label."""
    return "\n".join(f"{i + 1}. {fact.label} {fact.fact}" for i, fact in enumerate(facts))
