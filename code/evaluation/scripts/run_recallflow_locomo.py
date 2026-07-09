"""Dry-run entry: build probes, compress via RecallFlow (or any baseline),
and serialize per-sample diagnostics to a jsonl.

Reference: docs/recallflow_implementation_guide.md §9 (实验脚本建议) and
code/evaluation/README.md §Experiment Script Contract.

Usage:

    python -m code.evaluation.scripts.run_recallflow_locomo \\
        --input code/evaluation/adapters/fixtures/locomo_fixture.jsonl \\
        --method recallflow_full --budget-ratio 0.5 \\
        --output results/locomo_v0_dryrun.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from code.baselines.base import REGISTRY, make_compressor
from code.evaluation.adapters.locomo_adapter import (
    collect_test_questions,
    load_locomo_stream,
)
from code.benchmarks.embed_backends import random_numpy_embed
from code.compression import (
    assert_no_leakage,
    build_probe_queries,
)
from code.compression.recallflow import CompressedMemory


def _evidence_recall_proxy(
    cm: CompressedMemory, probe_queries: List, embed_fn
) -> Dict[str, float]:
    """For each probe, compute top-1 retrievable node in the *original* embedding
    space and check if that node id is still in `cm.retained_node_ids`.

    Returning this lets us compare methods on a "did the most-needed
    evidence survive compression?" proxy without doing real QA.
    """
    if not cm.retained_node_ids:
        return {
            "evidence_recall_at_1": 0.0,
            "evidence_recall_at_3": 0.0,
            "evidence_recall_at_5": 0.0,
        }
    retained_set = set(cm.retained_node_ids)
    return {"_skipped": 0.0}  # placeholder: full impl requires node-level fingerprints


def _serialize_one(
    cm: CompressedMemory,
    *,
    sample_id: str,
    dataset: str,
    method: str,
    model: str,
    budget_ratio: float,
    date: str,
    num_nodes_before: int,
    qa_score: float,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    diag = dict(cm.diagnostics)
    row: Dict[str, Any] = {
        "sample_id": sample_id,
        "dataset": dataset,
        "method": method,
        "model": model,
        "date": date,
        "budget_ratio": budget_ratio,
        "num_nodes_before": num_nodes_before,
        "num_capsules_after": len(cm.capsules),
        "num_retained": len(cm.retained_node_ids),
        "num_archived": len(cm.archive_node_ids),
        "num_probes": diag.pop("num_probes", 0),
        "compression_latency_sec": diag.pop("compression_latency_sec", 0.0),
        "retrieval_latency_sec": diag.pop("retrieval_latency_sec", 0.0),
        "qa_score": qa_score,
        "evidence_recall_at_k": diag.pop("evidence_recall_at_k", 0.0),
        "diagnostics": diag,
    }
    if extra:
        row["extra"] = extra
    return row


def run_locomo(
    *,
    input_path: Path,
    output_path: Path,
    method: str,
    budget_ratio: float,
    max_probes: int,
    window_size: int,
    tau: float,
    embedding_backend: str,
    embedding_dim: int,
    seed: int,
    dry_run: bool,
    qa_score: float = 0.0,
) -> Dict[str, Any]:
    nodes = load_locomo_stream(path=input_path)
    if not nodes:
        raise SystemExit(f"no memory nodes found in {input_path}")
    budget = max(1, int(round(budget_ratio * len(nodes))))
    probes = build_probe_queries(
        nodes, window_size=window_size, max_probes=max_probes,
    )
    assert_no_leakage(probes, collect_test_questions(path=input_path))

    if embedding_backend == "random":
        embed_fn = random_numpy_embed(dim=embedding_dim, seed=seed)
    elif embedding_backend == "sentence_transformers":
        from code.benchmarks.embed_backends import sentence_transformers_embed
        embed_fn = sentence_transformers_embed(
            "sentence-transformers/all-MiniLM-L6-v2"
        )
    else:
        raise SystemExit(f"unknown --embedding-backend {embedding_backend}")

    compressor = make_compressor(method)
    t0 = time.perf_counter()
    cm: CompressedMemory = compressor.fit(
        nodes=nodes,
        probe_queries=probes,
        budget=budget,
        embed_fn=embed_fn,
        tau=tau,
        seed=seed,
    )
    wall = time.perf_counter() - t0

    row = _serialize_one(
        cm,
        sample_id=f"locomo_dryrun_seed{seed}",
        dataset="LoCoMo-fixture",
        method=method,
        model=embedding_backend,
        budget_ratio=budget_ratio,
        date=time.strftime("%Y-%m-%d"),
        num_nodes_before=len(nodes),
        qa_score=qa_score,
        extra={"wall_sec": wall, "dry_run": dry_run, "tau": tau},
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path,
                   help="Path to LoCoMo-format jsonl (or fixture).")
    p.add_argument("--method", default="recallflow_full",
                   choices=sorted(REGISTRY), help="Compression method id.")
    p.add_argument("--budget-ratio", type=float, default=0.5,
                   help="Retained memory fraction (e.g. 0.25 / 0.5 / 0.75).")
    p.add_argument("--max-probes", type=int, default=64)
    p.add_argument("--window-size", type=int, default=8)
    p.add_argument("--tau", type=float, default=0.1,
                   help="Softmax temperature for response matrix (v0=0.1).")
    p.add_argument("--embedding-backend", default="random",
                   choices=["random", "sentence_transformers"])
    p.add_argument("--embedding-dim", type=int, default=64)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--output", required=True, type=Path,
                   help="Append-mode jsonl for per-run diagnostics.")
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="v0 always dry-runs (no QA / no model call).")
    return p


def main(argv: List[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    row = run_locomo(
        input_path=args.input,
        output_path=args.output,
        method=args.method,
        budget_ratio=args.budget_ratio,
        max_probes=args.max_probes,
        window_size=args.window_size,
        tau=args.tau,
        embedding_backend=args.embedding_backend,
        embedding_dim=args.embedding_dim,
        seed=args.seed,
        dry_run=args.dry_run,
    )
    summary = {k: row[k] for k in (
        "method", "model", "budget_ratio", "num_nodes_before",
        "num_capsules_after", "num_retained", "num_archived",
        "num_probes", "compression_latency_sec",
    )}
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
