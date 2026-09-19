"""The compression loop — planner, compiler, verifier, at most three rounds.

This is the method of the module.  One group goes in; one compact encoding
comes out, together with the evidence that it is still readable.

    round 1   compile under the budget -> answer the questions blind -> judge
    round 2   only if a required fact was lost, or the encoding is over budget
    round 3   likewise; then stop regardless

A round is *clean* when the blind reader recovered every required fact.  The
shortest clean round wins, which is what makes the loop a compressor rather
than a rewriter: extra rounds can only be spent buying back required facts, and
among the rounds that are correct the one with the fewest tokens is taken.  If
no round is clean, the loop falls back to the round that recovered the most
weighted fact mass, breaking ties toward brevity.

Two guards sit outside the loop.  A group whose planner found no facts at all
is summarised in one plain call instead (there is nothing to verify).  A group
whose best encoding came out no smaller than its source text keeps the source
text -- compression that does not compress is not worth its risk.

Unlike step 5, singletons are compressed too.  A single memory is where the
grammar pays best ("Loved 'Becoming Nicole' by Amy Ellis Nutt" -> ``loved
'Becoming Nicole'``), and skipping them would leave most of the library
untouched: at keep 0.5 roughly half of all groups have one member.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..llm import ChatClient
from ..plan import Group, Plan
from ..scope import Scope
from ..steps.s5_merge import Member, members_of
from . import prompts
from .facts import Fact, extract_facts, json_or_empty, render_questions, render_reference, render_triage, required_facts

#: Identifies the locked recipe in plan metadata.  The standalone runner
#: carried two different tags for the same algorithm as it was developed
#: (``babel_grammar_v7_triage_loop_no_fallback`` for the keep-50 compile,
#: ``babel_grammar_v11_triage_legend_answerer`` for keep 30 and 70); both named
#: a version that no longer meant anything.  One honest tag replaces them.
DESIGN_TAG = "tele-triage-loop-v1"

MAX_ROUNDS = 3

#: A round may finish up to 15% over budget.  The budget is soft by design --
#: forcing the last few tokens out costs a round and usually costs a fact.
BUDGET_SLACK = 1.15

#: Token limits per role, matching the locked runner.  They bound cost; only a
#: response that would exceed them is affected.
PLANNER_TOKENS = 1500
COMPILER_TOKENS = 1024
ANSWER_TOKENS = 1500
JUDGE_TOKENS = 1400


@dataclass(frozen=True)
class TeleConfig:
    """The locked recipe. ``target_ratio`` is the only knob that was tuned."""

    #: Soft token budget as a fraction of the group's source tokens.
    target_ratio: float = 0.80
    #: Below 0.65 only `high` facts are protected; see :func:`required_facts`.
    max_rounds: int = MAX_ROUNDS

    @property
    def tag(self) -> str:
        return f"t{int(round(100 * self.target_ratio)):03d}"


def token_length(text: str) -> int:
    """Tokens under cl100k -- the budget is counted in the reader's units.

    Imported lazily so that the rest of the package, and the tests, stay
    importable without tiktoken installed.
    """
    import tiktoken

    global _ENCODING
    try:
        encoding = _ENCODING
    except NameError:
        encoding = _ENCODING = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))


def render_lines(members: Sequence[Member]) -> str:
    """The group as the compiler sees it: text plus the time it happened."""
    return "\n".join(
        f"Memory {position + 1}: {member.text} | Timestamp: {member.time}"
        for position, member in enumerate(members)
    )


@dataclass
class Round:
    """What one compile-and-verify attempt produced."""

    index: int
    encoding: str
    tokens: int
    ok: list[bool]
    facts: list[Fact] = field(repr=False, default_factory=list)
    required: set[int] = field(repr=False, default_factory=set)

    @property
    def lost(self) -> list[int]:
        return [i for i, good in enumerate(self.ok) if not good]

    @property
    def must_fix(self) -> list[int]:
        """Required facts the blind reader could not recover."""
        return [i for i in self.lost if i in self.required]

    @property
    def optional_lost(self) -> list[int]:
        return [i for i in self.lost if i not in self.required]

    @property
    def recovered(self) -> int:
        return sum(1 for good in self.ok if good)

    @property
    def weighted_recovery(self) -> float:
        total = sum(fact.weight for fact in self.facts)
        got = sum(fact.weight for fact, good in zip(self.facts, self.ok) if good)
        return got / max(1e-9, total)

    def summary(self) -> dict[str, Any]:
        return {
            "round": self.index,
            "tokens": self.tokens,
            "recovered": self.recovered,
            "weighted_recovery": round(self.weighted_recovery, 4),
            "must_fix": len(self.must_fix),
        }


@dataclass
class Compressed:
    """One group's outcome."""

    text: str
    status: str                 # compiled | oneshot | kept_original
    source_tokens: int
    final_tokens: int
    api_calls: int
    rounds: list[Round] = field(default_factory=list)
    chosen: int | None = None   # which round was taken

    @property
    def facts_total(self) -> int:
        return len(self.rounds[0].facts) if self.rounds else 0

    @property
    def facts_recovered(self) -> int:
        return self.rounds[self.chosen - 1].recovered if self.chosen else self.facts_total

    @property
    def recovery_rate(self) -> float | None:
        if not self.rounds:
            return None
        return self.facts_recovered / max(1, self.facts_total)


# --------------------------------------------------------------- the three roles


def compile_once(
    chat: ChatClient,
    lines: str,
    members: Sequence[Member],
    triage: str,
    *,
    source_tokens: int,
    target: int,
    feedback: str,
    sample: int,
) -> str:
    """Compiler: facts + text + (optionally) last round's complaints -> encoding."""
    prompt = prompts.COMPRESS.format(
        n=len(members), src=source_tokens, target=target, facts_list=triage, lines=lines
    )
    encoding = chat.complete(prompt + feedback, sample=sample, max_tokens=COMPILER_TOKENS)
    # Models like to fence their output even when told not to.
    return encoding.strip("`").strip()


def verify(
    chat: ChatClient,
    encoding: str,
    facts: Sequence[Fact],
    *,
    sample: int,
) -> list[bool]:
    """Verifier: answer the questions blind, then judge what survived.

    Two calls, deliberately separated.  The answerer must not see the source
    text -- otherwise it answers from the memory rather than from the encoding,
    and the whole check is worthless.  The judge then compares its answers with
    what the planner said they should be.
    """
    answered = json_or_empty(
        chat.complete(
            prompts.ANSWER.format(
                enc=encoding, questions=render_questions(facts), k=len(facts)
            ),
            sample=sample,
            max_tokens=ANSWER_TOKENS,
        )
    )
    answers = [str(answer) for answer in (answered.get("answers") or [])]
    block = "\n".join(f"{i + 1}. {answer}" for i, answer in enumerate(answers))
    judged = json_or_empty(
        chat.complete(
            prompts.JUDGE.format(
                facts=render_reference(facts), answers=block, k=len(facts)
            ),
            sample=sample,
            max_tokens=JUDGE_TOKENS,
        )
    )
    ok = [bool(value) for value in (judged.get("ok") or [])][: len(facts)]
    # A judge that returned too few verdicts has not vouched for the rest.
    return ok + [False] * (len(facts) - len(ok))


def write_feedback(round_: Round, target: int) -> str:
    """Turn a round's losses into the next round's instructions."""
    issues = []
    if round_.must_fix:
        issues.append(
            "MUST-FIX (required facts the blind reader could not recover):\n"
            + "\n".join(f"- {round_.facts[i].fact}" for i in round_.must_fix)
            + "\nExpress THESE explicitly; clarity first for them."
        )
    if round_.tokens > target:
        issues.append(
            f"OVER BUDGET: {round_.tokens} vs {target} tokens. Tighten wording, merge lines, "
            f"or drop the {len(round_.optional_lost)} optional facts entirely."
        )
    elif round_.optional_lost:
        issues.append(
            f"Note: {len(round_.optional_lost)} optional (low/inferable) facts were dropped; "
            "that is acceptable."
        )
    return prompts.FEEDBACK.format(
        prev_tokens=round_.tokens, prev=round_.encoding, target=target, issues="\n".join(issues)
    )


# ------------------------------------------------------------------- the loop


def compress_group(
    group: Group,
    scope: Scope,
    chat: ChatClient,
    config: TeleConfig = TeleConfig(),
) -> Compressed:
    """Compress one group to a compact encoding. Never raises on model output.

    Sets the group's time span, like :func:`g1s.steps.s5_merge.merge_group`
    does; the caller stores the returned text.
    """
    members = members_of(group, scope)
    group.compression_time_start = members[0].time
    group.compression_time_end = members[-1].time
    lines = render_lines(members)
    source_tokens = sum(token_length(member.text) for member in members)
    target = max(3, int(round(config.target_ratio * source_tokens)))

    facts = extract_facts(chat, lines, sample=scope.sample, max_tokens=PLANNER_TOKENS)
    if not facts:
        # Nothing to verify against; fall back to a plain summary so the group
        # is no worse off than the native step 5 would have left it.
        text = chat.complete(
            prompts.ONESHOT.format(n=len(members), lines=lines), sample=scope.sample
        ).strip()
        return Compressed(
            text=text,
            status="oneshot",
            source_tokens=source_tokens,
            final_tokens=token_length(text),
            api_calls=2,
        )

    triage = render_triage(facts)
    required = required_facts(facts, config.target_ratio)
    rounds: list[Round] = []
    feedback = ""
    calls = 1  # the planner

    for index in range(1, max(1, config.max_rounds) + 1):
        encoding = compile_once(
            chat, lines, members, triage,
            source_tokens=source_tokens, target=target, feedback=feedback, sample=scope.sample,
        )
        ok = verify(chat, encoding, facts, sample=scope.sample)
        calls += 3
        current = Round(
            index=index,
            encoding=encoding,
            tokens=token_length(encoding),
            ok=ok,
            facts=list(facts),
            required=required,
        )
        rounds.append(current)
        if not current.must_fix and current.tokens <= int(target * BUDGET_SLACK):
            break
        feedback = write_feedback(current, target)

    clean = [round_ for round_ in rounds if not round_.must_fix]
    best = (
        min(clean, key=lambda round_: round_.tokens)
        if clean
        else max(rounds, key=lambda round_: (round_.weighted_recovery, -round_.tokens))
    )
    if best.tokens >= source_tokens:
        # The encoding did not pay for itself. Prefer any round that did;
        # otherwise keep the original text -- a compressor is allowed to
        # decline, and a longer "compressed" memory is strictly worse.
        shortest = min(rounds, key=lambda round_: round_.tokens)
        if shortest.tokens < source_tokens:
            best = shortest
        else:
            text = "; ".join(member.text.strip() for member in members if member.text.strip())
            return Compressed(
                text=text,
                status="kept_original",
                source_tokens=source_tokens,
                final_tokens=source_tokens,
                api_calls=calls,
                rounds=rounds,
            )
    return Compressed(
        text=best.encoding,
        status="compiled",
        source_tokens=source_tokens,
        final_tokens=best.tokens,
        api_calls=calls,
        rounds=rounds,
        chosen=best.index,
    )


# ------------------------------------------------------------------ the step


def compress_plan(
    plan: Plan,
    scope: Scope,
    chat: ChatClient,
    config: TeleConfig = TeleConfig(),
    *,
    workers: int = 8,
) -> Plan:
    """Step 5, TELE variant: fill in every group's ``final_text``.

    Signature-compatible with :func:`g1s.steps.s5_merge.merge_plan`, so the
    pipeline can choose between them without knowing which it picked.
    """
    results: dict[str, Compressed] = {}

    def one(group: Group) -> tuple[Group, Compressed]:
        return group, compress_group(group, scope, chat, config)

    if workers <= 1:
        finished = [one(group) for group in plan.groups]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(one, group) for group in plan.groups]
            finished = [future.result() for future in as_completed(futures)]

    for group, result in finished:
        group.final_text = result.text
        group.merge_api_calls_realized = result.api_calls
        results[group.anchor_node_id] = result

    missing = [group.anchor_node_id for group in plan.groups if not group.final_text]
    if missing:
        raise RuntimeError(f"sample {scope.sample}: {len(missing)} groups have no compressed text")

    plan.metadata = {
        **plan.metadata,
        "step": "merge",
        "merge_prompt": f"tele_triage_loop(target_ratio={config.target_ratio}, temperature=0)",
        "merge_model": chat.endpoint.model,
        "tele": statistics(results, config),
    }
    return plan


def statistics(results: dict[str, Compressed], config: TeleConfig) -> dict[str, Any]:
    """What the compile actually did, for the plan's metadata.

    ``token_ratio`` is the number that matters: stored tokens over source
    tokens, measured on the texts that were really written, not on the budget
    that was asked for.
    """
    values = list(results.values())
    source = sum(result.source_tokens for result in values)
    final = sum(result.final_tokens for result in values)
    rates = [result.recovery_rate for result in values if result.recovery_rate is not None]
    rounds: dict[str, int] = {}
    for result in values:
        if result.chosen:
            rounds[str(result.chosen)] = rounds.get(str(result.chosen), 0) + 1
    return {
        "design": DESIGN_TAG,
        "target_ratio": config.target_ratio,
        "max_rounds": config.max_rounds,
        "groups": len(values),
        "compiled": sum(1 for result in values if result.status == "compiled"),
        "oneshot": sum(1 for result in values if result.status == "oneshot"),
        "kept_original": sum(1 for result in values if result.status == "kept_original"),
        "accepted_in_round": rounds,
        "source_tokens": source,
        "final_tokens": final,
        "token_ratio": final / max(1, source),
        "mean_recovery_rate": sum(rates) / max(1, len(rates)) if rates else None,
        "chat_calls": sum(result.api_calls for result in values),
    }
