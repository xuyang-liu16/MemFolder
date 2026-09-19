"""Tests for the TELE compression loop.

No network, no store, no API key, and no tiktoken download: the model is a
scripted double and the token counter is monkeypatched to count words.  What is
pinned here is the part that decides what gets stored -- triage, the stopping
rule, and which round wins -- because those are the choices that silently
change results if someone "tidies" them.

    python -m pytest g1s/tests -q
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from g1s import store
from g1s.plan import Group, Plan
from g1s.tele import TeleConfig, compress_group, legend, required_facts
from g1s.tele import compress as compress_module
from g1s.tele.compress import compress_plan
from g1s.tele.facts import Fact, parse_facts

# --------------------------------------------------------------------- doubles


class FakeEndpoint:
    model = "fake-model"


class FakeChat:
    """Answers each of the five prompts from a script.

    ``encodings`` is consumed one per compiler call and ``verdicts`` one per
    judge call, so a test writes the rounds it wants to happen and nothing else.
    """

    def __init__(self, *, facts=None, encodings=(), verdicts=(), oneshot="a summary"):
        self.endpoint = FakeEndpoint()
        self.facts = facts
        self.encodings = list(encodings)
        self.verdicts = list(verdicts)
        self.oneshot = oneshot
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, sample: int = 0, max_tokens: int | None = None) -> str:
        self.prompts.append(prompt)
        if "extract the KEY facts" in prompt:
            return json.dumps({"facts": self.facts if self.facts is not None else []})
        if "You are a memory compressor" in prompt:
            return self.encodings.pop(0)
        if "You see ONLY a compact memory encoding" in prompt:
            return json.dumps({"answers": ["whatever"] * len(self.facts or [])})
        if "Reference key facts with expected answers" in prompt:
            return json.dumps({"ok": self.verdicts.pop(0)})
        if "memory summarization assistant" in prompt:
            return self.oneshot
        raise AssertionError(f"unexpected prompt: {prompt[:60]!r}")

    def count(self, needle: str) -> int:
        return sum(1 for prompt in self.prompts if needle in prompt)


class FakeScope:
    """Just enough Scope for ``members_of``."""

    def __init__(self, texts):
        self.sample = 0
        self.node_ids = tuple(f"n{index:02d}" for index in range(len(texts)))
        self.by_id = {
            node_id: store.Point(
                node_id=node_id,
                payload={"data": text, "timestamp": f"2023-05-{index + 1:02d} 10:00:00"},
                vector=np.zeros(4, dtype=np.float32),
                vector_name=None,
            )
            for index, (node_id, text) in enumerate(zip(self.node_ids, texts))
        }


def group_of(scope: FakeScope, node_ids) -> Group:
    return Group(
        anchor_node_id=node_ids[0],
        member_indices=[scope.node_ids.index(node_id) for node_id in node_ids],
        member_node_ids=list(node_ids),
        source_timestamps=["" for _ in node_ids],
    )


def fact(question="q?", *, importance="high", inferable=False, text="f"):
    return {
        "fact": text,
        "question": question,
        "answer": "a",
        "importance": importance,
        "inferable": inferable,
    }


@pytest.fixture(autouse=True)
def words_as_tokens(monkeypatch):
    """Count words, not cl100k tokens -- tiktoken would want to download."""
    monkeypatch.setattr(compress_module, "token_length", lambda text: len(text.split()))


# ------------------------------------------------------------------- 1. triage


def test_required_is_important_and_not_inferable():
    facts = [
        Fact("f", "q", "a", "high", False),
        Fact("f", "q", "a", "med", False),
        Fact("f", "q", "a", "low", False),
        Fact("f", "q", "a", "high", True),
    ]
    # A generous budget can afford to protect med as well as high.
    assert required_facts(facts, 0.80) == {0, 1}
    # A tight one protects only high. An inferable fact is never required,
    # however important it looks: the reader can re-derive it.
    assert required_facts(facts, 0.60) == {0}


def test_an_unlabelled_fact_counts_for_score_but_is_never_required():
    # The two defaults disagree on purpose; see parse_facts. Aligning them
    # would change which rounds count as clean.
    unlabelled = Fact("f", "q", "a", "", False)
    assert unlabelled.weight == 2.0
    assert required_facts([unlabelled], 0.80) == set()


def test_inferable_facts_are_worth_half():
    assert Fact("f", "q", "a", "high", True).weight == 1.5
    assert Fact("f", "q", "a", "high", False).weight == 3.0


def test_a_fact_without_a_question_cannot_be_verified_so_it_is_dropped():
    parsed = parse_facts({"facts": [fact("q1?"), {"fact": "no question"}, fact("q2?")]})
    assert [item.question for item in parsed] == ["q1?", "q2?"]


# ------------------------------------------------------------------ 2. the loop


def test_a_clean_round_within_budget_stops_the_loop():
    scope = FakeScope(["one two three four five six seven eight"])
    chat = FakeChat(facts=[fact()], encodings=["one two three"], verdicts=[[True]])
    result = compress_group(group_of(scope, ["n00"]), scope, chat, TeleConfig())

    assert result.status == "compiled"
    assert result.text == "one two three"
    assert chat.count("You are a memory compressor") == 1
    assert result.api_calls == 4  # planner + compile + answer + judge


def test_a_lost_required_fact_buys_another_round():
    scope = FakeScope(["one two three four five six seven eight"])
    chat = FakeChat(
        facts=[fact("q1?"), fact("q2?")],
        encodings=["short", "short but complete"],
        verdicts=[[True, False], [True, True]],
    )
    result = compress_group(group_of(scope, ["n00"]), scope, chat, TeleConfig())

    assert result.chosen == 2
    assert result.text == "short but complete"
    # Round 2 is told what to repair, and edits rather than re-rolls.
    feedback = [p for p in chat.prompts if "VERIFIER FEEDBACK" in p]
    assert len(feedback) == 1
    assert "MUST-FIX" in feedback[0]


def test_an_optional_loss_does_not_buy_a_round():
    scope = FakeScope(["one two three four five six seven eight"])
    # The only lost fact is [low], so it is not required at any ratio.
    chat = FakeChat(
        facts=[fact("q1?"), fact("q2?", importance="low")],
        encodings=["one two"],
        verdicts=[[True, False]],
    )
    result = compress_group(group_of(scope, ["n00"]), scope, chat, TeleConfig())

    assert result.chosen == 1
    assert chat.count("You are a memory compressor") == 1


def test_over_budget_buys_a_round_even_when_nothing_was_lost():
    # 8 source words, budget 0.5 -> 4, slack -> 4. Round 1 is clean but long.
    scope = FakeScope(["one two three four five six seven eight"])
    chat = FakeChat(
        facts=[fact()],
        encodings=["a b c d e f g", "a b c"],
        verdicts=[[True], [True]],
    )
    result = compress_group(
        group_of(scope, ["n00"]), scope, chat, TeleConfig(target_ratio=0.5)
    )

    assert chat.count("You are a memory compressor") == 2
    # Both rounds are clean, so the shorter one wins.
    assert result.text == "a b c"
    assert result.chosen == 2


def test_the_shortest_clean_round_wins_not_the_last_one():
    # 10 source words at ratio 0.3 -> a budget of 3, so round 2 is clean but
    # still over budget and the loop keeps going. Round 3 is clean too, and
    # longer. The shortest clean round is therefore *not* the last one.
    scope = FakeScope(["one two three four five six seven eight nine ten"])
    chat = FakeChat(
        facts=[fact("q1?"), fact("q2?")],
        encodings=["a b", "a b c d", "a b c d e f"],
        verdicts=[[True, False], [True, True], [True, True]],
    )
    result = compress_group(
        group_of(scope, ["n00"]), scope, chat, TeleConfig(target_ratio=0.3)
    )

    assert [round_.tokens for round_ in result.rounds] == [2, 4, 6]
    assert [bool(round_.must_fix) for round_ in result.rounds] == [True, False, False]
    assert result.chosen == 2
    assert result.text == "a b c d"


def test_with_no_clean_round_the_best_recovery_wins_ties_going_to_brevity():
    scope = FakeScope(["one two three four five six seven eight"])
    chat = FakeChat(
        facts=[fact("q1?"), fact("q2?")],
        encodings=["a", "b b b", "c"],
        verdicts=[[False, False], [True, False], [True, False]],
    )
    result = compress_group(group_of(scope, ["n00"]), scope, chat, TeleConfig())

    assert all(round_.must_fix for round_ in result.rounds)
    # Rounds 2 and 3 recovered the same weight; the shorter one is taken.
    assert result.chosen == 3
    assert result.text == "c"


def test_the_loop_never_runs_more_than_three_rounds():
    scope = FakeScope(["one two three four five six seven eight"])
    chat = FakeChat(
        facts=[fact()],
        encodings=["a", "b", "c", "d"],
        verdicts=[[False], [False], [False], [False]],
    )
    compress_group(group_of(scope, ["n00"]), scope, chat, TeleConfig())
    assert chat.count("You are a memory compressor") == 3


# -------------------------------------------------------------- 3. the guards


def test_an_encoding_that_does_not_compress_is_thrown_away():
    scope = FakeScope(["one two", "three four"])
    chat = FakeChat(
        facts=[fact()],
        encodings=["a b c d e", "a b c d e f", "a b c d e f g"],
        verdicts=[[True], [True], [True]],
    )
    result = compress_group(group_of(scope, ["n00", "n01"]), scope, chat, TeleConfig())

    assert result.status == "kept_original"
    assert result.text == "one two; three four"
    assert result.final_tokens == result.source_tokens


def test_a_group_with_no_extractable_facts_falls_back_to_one_summary_call():
    scope = FakeScope(["ok"])
    chat = FakeChat(facts=[], oneshot="the summary")
    result = compress_group(group_of(scope, ["n00"]), scope, chat, TeleConfig())

    assert result.status == "oneshot"
    assert result.text == "the summary"
    assert result.recovery_rate is None
    assert chat.count("You are a memory compressor") == 0
    assert result.api_calls == 2


def test_singletons_are_compressed_unlike_the_native_merge():
    # Step 5 passes a one-member group through untouched; TELE does not,
    # because a single memory is where the grammar pays best.
    scope = FakeScope(["Loved 'Becoming Nicole' by Amy Ellis Nutt on Tuesday"])
    chat = FakeChat(facts=[fact()], encodings=["loved 'Becoming Nicole'"], verdicts=[[True]])
    result = compress_group(group_of(scope, ["n00"]), scope, chat, TeleConfig())

    assert result.text == "loved 'Becoming Nicole'"
    assert result.final_tokens < result.source_tokens


# ---------------------------------------------------------------- 4. the step


def test_compress_plan_fills_every_group_and_records_what_it_did():
    scope = FakeScope(["one two three four", "five six seven eight"])
    plan = Plan(
        method="test",
        sample_id=0,
        scope_id="scope",
        source_store="/dev/null",
        keep_ratio=0.5,
        generator_model="",
        num_nodes_before=2,
        groups=[group_of(scope, ["n00"]), group_of(scope, ["n01"])],
    )
    chat = FakeChat(
        facts=[fact()], encodings=["a b", "c d"], verdicts=[[True], [True]]
    )
    compress_plan(plan, scope, chat, TeleConfig(), workers=1)

    assert [group.final_text for group in plan.groups] == ["a b", "c d"]
    assert all(group.compression_time_start for group in plan.groups)
    stats = plan.metadata["tele"]
    assert stats["groups"] == 2 and stats["compiled"] == 2
    assert stats["source_tokens"] == 8 and stats["final_tokens"] == 4
    assert stats["token_ratio"] == 0.5
    assert plan.merged


# --------------------------------------------------------------- 5. the legend


def overlay_at(root: Path, body: str) -> Path:
    directory = root / legend.OVERLAY_NAME
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "prompts.py").write_text(body, encoding="utf-8")
    return directory


def test_the_legend_lands_before_the_instructions_and_only_once(tmp_path):
    overlay = overlay_at(tmp_path, 'P = """\n    # INSTRUCTIONS:\n    answer.\n"""\n')

    assert legend.patch_overlay(tmp_path) is True
    patched = (overlay / "prompts.py").read_text(encoding="utf-8")
    assert patched.index(legend.MARKER) < patched.index("# INSTRUCTIONS:")

    # A resumed run reuses the overlay, so patching twice must be harmless.
    assert legend.patch_overlay(tmp_path) is False
    assert (overlay / "prompts.py").read_text(encoding="utf-8") == patched


def test_a_prompt_with_no_anchor_is_an_error_not_a_silent_skip(tmp_path):
    # Failing loudly matters: an unpatched reader scores every encoding as
    # gibberish and the arm looks like a bad method rather than a bad setup.
    overlay_at(tmp_path, 'P = "answer the question"\n')
    with pytest.raises(RuntimeError, match="INSTRUCTIONS"):
        legend.patch_overlay(tmp_path)
