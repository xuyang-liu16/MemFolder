"""The G1S pipeline: seven steps, one sample at a time.

This module contains no algorithm.  Its only jobs are to say where each
artifact lives, to run the steps in order, and to make every step resumable --
so that the method modules under :mod:`g1s.steps` can be read as the method and
nothing else.

The run in full, for one LoCoMo sample::

    1  grounding    text            -> entities and relations, per session
    2  synonyms     entity labels   -> merged entity labels
    3  anchors      embeddings      -> K anchors + nearest-anchor partition
    4  chaining     entities+time   -> the same K groups, re-membered by chains
    5  merge        each group      -> one merged memory
    6  materialize  the plan        -> a real, smaller vector store
    7  evaluate     that store      -> accuracy / BLEU-1 / F1

Steps 1-2 depend only on the sample, not on the compression ratio, so their
output is shared across every arm and lives outside the run directory.  Steps
3-5 are all writes to a single plan JSON; step 6 is the first time anything
other than JSON is produced.

Resumability is per artifact, not per run: every step checks for its own
finished output and returns it.  Re-running a completed sample costs no API
calls, and an interrupted run continues where it stopped.

The one optional substitution is at step 5: with ``RunConfig.tele`` set, the
group is written as a TELE compact encoding instead of a natural-language
summary (:mod:`g1s.tele`).  It is a different writer for the same slot -- the
plan it reads and the field it fills are unchanged -- so it needs no step of
its own, and the arm gets its own directory so the two can be compared.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from . import plan as plan_io
from .entities import load_grounding
from .jsonio import read_json, write_json
from .llm import ChatClient, EmbeddingCache, EmbeddingClient, PromptCache
from .plan import Plan
from .scope import Scope, load_scope
from .settings import Settings
from .steps import (
    s1_grounding,
    s2_synonyms,
    s3_anchors,
    s4_chaining,
    s5_merge,
    s6_materialize,
    s7_evaluate,
)
from .steps.s4_chaining import ChainingConfig
from .tele import TeleConfig, compress_plan, patch_overlay

#: The ten LoCoMo conversations.
ALL_SAMPLES = tuple(range(10))

STEPS = ("grounding", "synonyms", "anchors", "chaining", "merge", "materialize", "evaluate")


@dataclass(frozen=True)
class RunConfig:
    """One experiment arm."""

    keep_ratio: float = 0.5
    samples: tuple[int, ...] = ALL_SAMPLES
    grounding_tag: str = "v2rm"
    #: Point this at a grounding directory produced by an earlier run to reuse
    #: it instead of re-paying for steps 1-2.  Steps 1-2 do not depend on the
    #: keep ratio or on any chaining switch, so sharing one is always sound.
    grounding_dir: Path | None = None
    chaining: ChainingConfig = field(default_factory=ChainingConfig)
    #: Opt-in: replace step 5's natural-language summary with a TELE compact
    #: encoding.  ``None`` is the main line.  See :mod:`g1s.tele`.
    tele: TeleConfig | None = None
    merge_workers: int = 8
    judge_workers: int = 4
    top_k: int = s7_evaluate.TOP_K

    @property
    def name(self) -> str:
        """Directory name of the arm: ``g1s_keep50_full_anchor_hungarian``.

        A TELE arm appends its budget (``..._hungarian_tele_t080``) so it never
        shares a directory, a plan or a store with the native arm it is
        compared against.
        """
        parts = [
            "g1s",
            plan_io.keep_tag(self.keep_ratio),
            self.chaining.affinity,
            self.chaining.gating,
            self.chaining.matching,
        ]
        if self.tele is not None:
            parts += ["tele", self.tele.tag]
        return "_".join(parts)

    def describe(self) -> dict[str, Any]:
        return {
            "method": "g1s",
            "keep_ratio": self.keep_ratio,
            "samples": list(self.samples),
            "grounding_tag": self.grounding_tag,
            "grounding_dir": str(self.grounding_dir) if self.grounding_dir else "",
            "affinity": self.chaining.affinity,
            "gating": self.chaining.gating,
            "matching": self.chaining.matching,
            "window": self.chaining.window,
            "topk": self.chaining.topk,
            "partition_seed": self.chaining.seed,
            "top_k_retrieval": self.top_k,
            "tele": vars(self.tele) if self.tele is not None else None,
        }


@dataclass(frozen=True)
class Layout:
    """Where everything for one arm is written."""

    settings: Settings
    config: RunConfig

    # ------------------------------------------------------- shared across arms

    @property
    def grounding_dir(self) -> Path:
        """Step 2's output -- the grounding every arm reads."""
        if self.config.grounding_dir is not None:
            return Path(self.config.grounding_dir)
        return self.settings.grounding_dir(self.config.grounding_tag)

    @property
    def raw_grounding_dir(self) -> Path:
        """Step 1's output, kept so the synonym merge can be redone from it."""
        return self.grounding_dir / "raw"

    @property
    def cache_dir(self) -> Path:
        return self.settings.cache_root / "g1s_cache"

    @property
    def embedding_cache(self) -> Path:
        return self.cache_dir / "embeddings.pkl"

    # ----------------------------------------------------------- per-arm output

    @property
    def run_dir(self) -> Path:
        return self.settings.results_root / self.config.name

    @property
    def cell_dir(self) -> Path:
        """The plan/store directory. Its name is historic; see ``Settings.cell_dir``."""
        return self.settings.cell_dir(self.run_dir)

    @property
    def qa_dir(self) -> Path:
        return self.run_dir / "qa"

    def selection_plan(self, sample: int) -> Path:
        return plan_io.selection_plan_path(self.cell_dir, sample)

    def plan(self, sample: int) -> Path:
        return plan_io.final_plan_path(self.cell_dir, sample)

    def store(self, sample: int) -> Path:
        return self.cell_dir / f"store_{sample}" / "locomo"

    def manifest(self, sample: int) -> Path:
        return self.cell_dir / f"manifest_sample{sample}.json"

    def make(self) -> "Layout":
        for directory in (self.raw_grounding_dir, self.cache_dir, self.cell_dir, self.qa_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self


# --------------------------------------------------------------------- clients


def chat_client(settings: Settings, layout: Layout) -> ChatClient:
    return ChatClient(
        endpoint=settings.chat.require("chat"),
        cache=PromptCache(layout.cache_dir / "prompts"),
    )


def embedding_client(settings: Settings) -> EmbeddingClient:
    return EmbeddingClient(
        endpoint=settings.embedding.require("embedding"), dimensions=settings.embedding_dim
    )


# ----------------------------------------------------------------- the steps


def step_grounding(scope: Scope, chat: ChatClient, layout: Layout) -> dict[str, Any]:
    """1 -- what is each memory about? One LLM call per session."""
    path = layout.raw_grounding_dir / f"sample{scope.sample}_grounding.json"
    if path.exists():
        return read_json(path)
    layout.raw_grounding_dir.mkdir(parents=True, exist_ok=True)
    return s1_grounding.run(scope, chat, layout.raw_grounding_dir)


def step_synonyms(
    record: dict[str, Any], embedder: EmbeddingClient, layout: Layout
) -> dict[str, Any]:
    """2 -- collapse labels that name the same thing."""
    sample = int(record["sample_id"])
    path = layout.grounding_dir / f"sample{sample}_grounding.json"
    if path.exists():
        return read_json(path)
    layout.grounding_dir.mkdir(parents=True, exist_ok=True)
    return s2_synonyms.run(
        record, embedder, layout.grounding_dir, cache=EmbeddingCache(layout.embedding_cache)
    )


def step_anchors(scope: Scope, layout: Layout, config: RunConfig) -> Plan:
    """3 -- pick K anchors by density peaks, assign the rest to the nearest one."""
    path = layout.selection_plan(scope.sample)
    if path.exists():
        return Plan.read(path)
    plan = s3_anchors.build_plan(
        scope,
        keep_ratio=config.keep_ratio,
        generator_model=layout.settings.chat.model,
        method=config.name,
    )
    plan.write(path)
    return plan


def step_chaining(base: Plan, scope: Scope, layout: Layout, config: RunConfig) -> Plan:
    """4 -- the method: re-member the groups along entity/time chains."""
    path = layout.plan(scope.sample)
    if path.exists():
        return Plan.read(path)
    grounding = load_grounding(layout.grounding_dir, scope.sample, scope.node_ids)
    plan = s4_chaining.regroup(base, scope, grounding, config.chaining)
    plan.write(path)
    return plan


def step_merge(plan: Plan, scope: Scope, chat: ChatClient, layout: Layout, config: RunConfig) -> Plan:
    """5 -- one group, one prompt, one memory.

    TELE arms substitute a different writer here and nothing else: it consumes
    the plan step 4 produced and fills in the same ``final_text`` field, so
    steps 6 and 7 cannot tell the two apart.
    """
    if plan.merged:
        return plan
    if config.tele is not None:
        plan = compress_plan(plan, scope, chat, config.tele, workers=config.merge_workers)
    else:
        plan = s5_merge.merge_plan(plan, scope, chat, workers=config.merge_workers)
    plan.write(layout.plan(scope.sample))
    return plan


def step_materialize(
    plan: Plan, scope: Scope, embedder: EmbeddingClient, layout: Layout
) -> dict[str, Any]:
    """6 -- write the compressed store."""
    return s6_materialize.run(
        plan,
        scope,
        embedder,
        layout.store(scope.sample),
        layout.manifest(scope.sample),
        embedding_cache=layout.embedding_cache,
    )


def step_evaluate(sample: int, layout: Layout, config: RunConfig) -> dict[str, Any]:
    """7 -- retrieve and score against the compressed store.

    A TELE arm patches the decode legend into the evaluation overlay first.
    ``prepare_overlay`` is built once per run directory and then reused, so
    doing it here means the overlay ``retrieve`` picks up is already patched --
    step 7 itself needs to know nothing about TELE.
    """
    if config.tele is not None:
        s7_evaluate.prepare_overlay(layout.settings.eval_root, layout.run_dir)
        patch_overlay(layout.run_dir)
    paths = s7_evaluate.QaPaths.under(layout.qa_dir, sample)
    s7_evaluate.retrieve(
        layout.settings,
        layout.store(sample),
        paths,
        sample,
        workdir=layout.run_dir,
        top_k=config.top_k,
    )
    s7_evaluate.score(layout.settings, paths, sample, workers=config.judge_workers)
    return s7_evaluate.summarise(layout.qa_dir, [sample])


# ------------------------------------------------------------------- the runs


def run_sample(
    sample: int,
    settings: Settings,
    config: RunConfig,
    *,
    until: str = "evaluate",
) -> dict[str, Any]:
    """Run steps 1..``until`` for one sample. Returns what it produced."""
    if until not in STEPS:
        raise ValueError(f"unknown step {until!r}; expected one of {', '.join(STEPS)}")
    stop = STEPS.index(until)

    layout = Layout(settings, config).make()
    scope = load_scope(settings.store_root, sample)
    chat = chat_client(settings, layout)
    embedder = embedding_client(settings)
    result: dict[str, Any] = {"sample_id": sample, "num_nodes": len(scope)}

    record = step_grounding(scope, chat, layout)
    if stop == 0:
        return result
    record = step_synonyms(record, embedder, layout)
    if stop == 1:
        return result

    selection = step_anchors(scope, layout, config)
    result["num_groups"] = len(selection.groups)
    if stop == 2:
        return result

    plan = step_chaining(selection, scope, layout, config)
    result["chaining"] = plan.metadata.get("chaining_stats", {})
    if stop == 3:
        return result

    plan = step_merge(plan, scope, chat, layout, config)
    result["merge_api_calls"] = plan.api_calls()
    if stop == 4:
        return result

    manifest = step_materialize(plan, scope, embedder, layout)
    result["compression_ratio"] = manifest["compression_ratio"]
    result["num_units_after"] = manifest["num_units_after"]
    if stop == 5:
        return result

    result["scores"] = step_evaluate(sample, layout, config)
    return result


def run(
    settings: Settings, config: RunConfig, *, until: str = "evaluate"
) -> dict[str, Any]:
    """Run every sample of an arm, then write ``summary.json``."""
    layout = Layout(settings, config).make()
    samples = []
    for sample in config.samples:
        print(f"[g1s] sample {sample}", flush=True)
        samples.append(run_sample(sample, settings, config, until=until))

    summary: dict[str, Any] = {"config": config.describe(), "samples": samples}
    if STEPS.index(until) >= STEPS.index("evaluate"):
        summary["scores"] = s7_evaluate.summarise(layout.qa_dir, config.samples)
    write_json(layout.run_dir / "summary.json", summary, indent=2)
    return summary


def compare(settings: Settings, arms: Sequence[RunConfig]) -> dict[str, Any]:
    """Read finished ``summary.json`` files and put their headline numbers side by side.

    The first arm is the reference; deltas are against it.  Reading the
    summaries rather than recomputing means this cannot disagree with what the
    runs actually produced.
    """
    rows = []
    for config in arms:
        path = Layout(settings, config).run_dir / "summary.json"
        if not path.exists():
            continue
        scores = read_json(path).get("scores", {})
        rows.append(
            {
                "arm": config.name,
                "keep_ratio": config.keep_ratio,
                "questions": scores.get("questions", 0),
                "accuracy": scores.get("accuracy", 0.0),
                "bleu1": scores.get("bleu1", 0.0),
                "f1": scores.get("f1", 0.0),
            }
        )
    if rows:
        reference = rows[0]
        for row in rows:
            for metric in ("accuracy", "bleu1", "f1"):
                row[f"delta_{metric}"] = row[metric] - reference[metric]
    return {"reference": rows[0]["arm"] if rows else None, "arms": rows}
