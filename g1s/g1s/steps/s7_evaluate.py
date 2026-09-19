"""Step 7 — evaluate: does the compressed store still answer the questions?

The measurement is end-to-end and deliberately unmodified: run Mem0's own
LoCoMo evaluation against the compressed store, then score with the official
metrics.  Nothing here is part of the method; this module's whole job is to
drive the vendored harness correctly and reproducibly.

    retrieve   Mem0's ``run_experiments.py --method search --top_k 30``
    score      ``python -m g1s.judge`` -- BLEU-1, F1, LLM accuracy

Both run as subprocesses, for two reasons: the vendored code reads its
configuration from the environment at import time, and its metrics package
pulls in nltk/bert_score.  Keeping it behind a process boundary means the
method package stays importable on its own.

The one thing we do change is an *overlay*: a patched copy of the vendor's
search module that reads query embeddings from a pre-computed cache instead of
calling the embedding API once per question.  Query embeddings do not depend on
which compression arm is being evaluated, so embedding them once and reusing
them makes arms cheaper and strictly more comparable -- every arm retrieves
with bit-identical query vectors.  The patch is applied by exact string match
and raises if the vendor code has moved on, so it can never silently apply to
something it was not written for.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..jsonio import read_json
from ..settings import Settings

OVERLAY_VERSION = "g1s-eval-overlay-v1"
OVERLAY_NAME = "_eval_overlay"
TOP_K = 30


# ------------------------------------------------------------------ the overlay

_IMPORTS = ("import json\nimport os\n", "import json\nimport os\nimport pickle\n")

_INIT_ANCHOR = '        self.answer_enable_thinking = os.getenv("CHAT_ANSWER_ENABLE_THINKING")\n'
_INIT_ADDITION = '''        self.answer_thinking_mode = os.getenv("CHAT_ANSWER_THINKING_MODE")
        self.query_embedding_cache = {}
        query_cache_path = os.getenv("QUERY_EMBEDDING_CACHE_PATH")
        if query_cache_path:
            with open(query_cache_path, "rb") as handle:
                cache = pickle.load(handle)
            if not isinstance(cache, dict):
                raise TypeError(f"Query embedding cache must be a dict: {query_cache_path}")
            self.query_embedding_cache = cache
'''

_REQUEST_OLD = (
    '        if self.answer_enable_thinking is not None:\n'
    '            request_kwargs["extra_body"] = {\n'
    '                "enable_thinking": self.answer_enable_thinking.lower() == "true"\n'
    '            }\n'
)
# Keep the vendor's own branch, reached only when no explicit mode is set.
_REQUEST_NEW = (
    '        if self.answer_thinking_mode:\n'
    '            request_kwargs["extra_body"] = {"thinking": {"type": self.answer_thinking_mode}}\n'
    + _REQUEST_OLD.replace('        if ', '        elif ', 1)
)

_EMBED_OLD = '            query_vec = embedding_model.embed(query, "search")\n'
_EMBED_NEW = '''            if self.query_embedding_cache:
                query_vec = self.query_embedding_cache.get(query)
                if query_vec is None:
                    query_vec = self.query_embedding_cache.get(query.strip())
                if query_vec is None:
                    raise KeyError(f"Missing cached query embedding: {query!r}")
            else:
                query_vec = embedding_model.embed(query, "search")
'''


def prepare_overlay(eval_root: Path, destination: Path) -> Path:
    """Build (or reuse) the patched copy of the vendor evaluation code."""
    overlay = Path(destination) / OVERLAY_NAME
    marker = overlay / ".overlay_version"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == OVERLAY_VERSION:
        return overlay

    staging = overlay.with_name(overlay.name + ".building")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    for name in ("run_experiments.py", "config_loader.py", "prompts.py"):
        shutil.copy2(Path(eval_root) / name, staging / name)
    shutil.copytree(Path(eval_root) / "src", staging / "src", symlinks=True)

    search = staging / "src" / "memzero" / "search.py"
    text = search.read_text(encoding="utf-8")
    patches = (
        _IMPORTS,
        (_INIT_ANCHOR, _INIT_ANCHOR + _INIT_ADDITION),
        (_REQUEST_OLD, _REQUEST_NEW),
        (_EMBED_OLD, _EMBED_NEW),
    )
    for old, _ in patches:
        if old not in text:
            raise RuntimeError(
                "evaluation overlay no longer matches the vendored search.py; "
                "re-derive the patch before trusting any numbers"
            )
    for old, new in patches:
        text = text.replace(old, new, 1)
    search.write_text(text, encoding="utf-8")

    (staging / ".overlay_version").write_text(OVERLAY_VERSION + "\n", encoding="utf-8")
    if overlay.exists():
        shutil.rmtree(overlay)
    staging.rename(overlay)
    return overlay


def link_store(overlay: Path, store: Path) -> None:
    """The vendor harness takes a ``--store_name`` relative to its own cwd."""
    link = Path(overlay) / store.name
    if link.exists() or link.is_symlink():
        if link.resolve() != store.resolve():
            raise RuntimeError(f"overlay store link points elsewhere: {link}")
        return
    link.symlink_to(store.resolve(), target_is_directory=True)


# -------------------------------------------------------------- the environment


def child_env(settings: Settings) -> dict[str, str]:
    """Environment for the vendored harness, which is configured by env vars."""
    settings.chat.require("chat")
    environment = os.environ.copy()
    environment.update(
        {
            "OPENAI_API_KEY": settings.chat.api_key,
            "OPENAI_BASE_URL": settings.chat.base_url,
            "MODEL": settings.chat.model,
            "CHAT_API_KEY": settings.chat.api_key,
            "CHAT_BASE_URL": settings.chat.base_url,
            "CHAT_MODEL": settings.chat.model,
            "CHAT_ANSWER_MESSAGE_ROLE": "user",
            "CHAT_ANSWER_MAX_TOKENS": "256",
            "CHAT_ANSWER_RETRIES": "10",
            "CHAT_ANSWER_RETRY_SLEEP": "8",
            "JUDGE_API_KEY": settings.chat.api_key,
            "JUDGE_BASE_URL": settings.chat.base_url,
            "JUDGE_MODEL": settings.judge_model,
            "JUDGE_MAX_TOKENS": "128",
            "EMBEDDING_API_KEY": settings.embedding.api_key,
            "EMBEDDING_BASE_URL": settings.embedding.base_url,
            "EMBEDDING_MODEL": settings.embedding.model,
            "EMBEDDING_DIM": str(settings.embedding_dim),
        }
    )
    if settings.query_embedding_cache:
        environment["QUERY_EMBEDDING_CACHE_PATH"] = str(settings.query_embedding_cache)
    # `enable_thinking` is a DeepSeek extension; OpenAI-compatible endpoints
    # reject it outright, so omit rather than send an explicit false.
    if "gpt-4o" in settings.chat.model.lower():
        for name in ("CHAT_ANSWER_ENABLE_THINKING", "JUDGE_ENABLE_THINKING"):
            environment.pop(name, None)
    else:
        environment["CHAT_ANSWER_ENABLE_THINKING"] = "false"
        environment["JUDGE_ENABLE_THINKING"] = "false"
    for name in ("CHAT_ANSWER_THINKING_MODE", "JUDGE_THINKING_MODE"):
        environment.pop(name, None)
    return environment


def with_path(environment: dict[str, str], *entries: Path) -> dict[str, str]:
    """Set ``PYTHONPATH`` explicitly.

    Explicitly rather than by prepending: the repository root has a top-level
    ``src`` package that shadows the vendored ``src`` the harness imports, and
    an inherited ``PYTHONPATH`` is exactly how that shadowing happens.
    """
    return {**environment, "PYTHONPATH": os.pathsep.join(str(entry) for entry in entries)}


def run_command(command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write("$ " + " ".join(str(item) for item in command) + "\n")
        handle.flush()
        result = subprocess.run(
            [str(item) for item in command],
            cwd=str(cwd),
            env=dict(env),
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}); see {log}")


# ------------------------------------------------------------------ completion


@dataclass(frozen=True)
class QaPaths:
    root: Path
    answers: Path
    attempts: Path
    scores: Path
    log: Path

    @classmethod
    def under(cls, directory: Path, sample: int) -> "QaPaths":
        root = Path(directory) / f"sample_{sample:03d}"
        return cls(
            root=root,
            answers=root / "qa.json",
            attempts=root / "attempts.jsonl",
            scores=root / "scores.json",
            log=root / "run.log",
        )


def expected_counts(dataset: Path, sample: int) -> tuple[int, int]:
    """``(questions asked, questions scored)``; category 5 is never scored."""
    data = json.loads(Path(dataset).read_text(encoding="utf-8"))[sample]
    questions = data.get("qa", [])
    return len(questions), sum(1 for row in questions if str(row.get("category", "")) != "5")


def _count(path: Path) -> int:
    if not Path(path).exists():
        return 0
    try:
        payload = read_json(path)
    except Exception:  # noqa: BLE001 - a half-written file is simply incomplete
        return 0
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        return sum(len(rows) for rows in payload.values() if isinstance(rows, list))
    return 0


# ---------------------------------------------------------------- the two stages


def retrieve(
    settings: Settings,
    store: Path,
    paths: QaPaths,
    sample: int,
    *,
    workdir: Path,
    top_k: int = TOP_K,
) -> None:
    """Answer every question of one sample against ``store``."""
    asked, _ = expected_counts(settings.dataset_path, sample)
    if _count(paths.answers) >= asked:
        return
    overlay = prepare_overlay(settings.eval_root, workdir)
    link_store(overlay, store)
    paths.root.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            settings.python,
            str(overlay / "run_experiments.py"),
            "--technique_type", "mem0",
            "--method", "search",
            "--dataset_path", str(settings.dataset_path),
            "--store_name", store.name,
            "--output_folder", str(paths.root),
            "--top_k", str(top_k),
            "--start_idx", str(sample),
            "--end_idx", str(sample + 1),
        ],
        overlay,
        with_path(child_env(settings), overlay, settings.eval_root),
        paths.log,
    )
    produced = paths.root / f"{store.name}_mem0_results_top_{top_k}_filter_False_graph_False.json"
    if produced.exists() and produced != paths.answers:
        produced.rename(paths.answers)
    if _count(paths.answers) < asked:
        raise RuntimeError(f"sample {sample}: incomplete QA output at {paths.answers}")


def score(settings: Settings, paths: QaPaths, sample: int, *, workers: int = 4) -> None:
    _, scored = expected_counts(settings.dataset_path, sample)
    if _count(paths.scores) >= scored:
        return
    run_command(
        [
            settings.python,
            "-m", "g1s.judge",
            "--input-file", str(paths.answers),
            "--attempts-file", str(paths.attempts),
            "--output-file", str(paths.scores),
            "--sample-idx", str(sample),
            "--eval-root", str(settings.eval_root),
            # Sample 7 repeats question text; key on position there.
            "--question-id-mode", "unique" if sample == 7 else "question",
            "--workers", str(workers),
        ],
        settings.project_dir,
        with_path(child_env(settings), settings.project_dir, settings.eval_root),
        paths.log,
    )
    if _count(paths.scores) < scored:
        raise RuntimeError(f"sample {sample}: incomplete scores at {paths.scores}")


# --------------------------------------------------------------------- summary


def score_rows(path: Path) -> list[dict[str, Any]]:
    if not Path(path).exists():
        return []
    payload = read_json(path)
    if isinstance(payload, list):
        return payload
    return [row for rows in payload.values() if isinstance(rows, list) for row in rows]


def summarise(qa_dir: Path, samples: Sequence[int]) -> dict[str, Any]:
    """Mean accuracy / BLEU-1 / F1 over every scored question of every sample."""
    per_sample = []
    accuracy: list[float] = []
    bleu: list[float] = []
    f1: list[float] = []
    for sample in samples:
        rows = score_rows(QaPaths.under(qa_dir, sample).scores)
        if not rows:
            continue
        sample_accuracy = [float(row.get("llm_score") or 0.0) for row in rows]
        sample_bleu = [float(row.get("bleu_score") or 0.0) for row in rows]
        sample_f1 = [float(row.get("f1_score") or 0.0) for row in rows]
        accuracy.extend(sample_accuracy)
        bleu.extend(sample_bleu)
        f1.extend(sample_f1)
        per_sample.append(
            {
                "sample_id": sample,
                "questions": len(rows),
                "accuracy": sum(sample_accuracy) / len(rows),
                "bleu1": sum(sample_bleu) / len(rows),
                "f1": sum(sample_f1) / len(rows),
            }
        )

    def mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    return {
        "questions": len(accuracy),
        "accuracy": mean(accuracy),
        "bleu1": mean(bleu),
        "f1": mean(f1),
        "samples": per_sample,
    }
