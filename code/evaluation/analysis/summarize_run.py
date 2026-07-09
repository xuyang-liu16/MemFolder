"""Analyse a results jsonl produced by run_recallflow_locomo.

Reads each row and groups by method×budget_ratio, printing a small table
suitable for inclusion in `results/README.md`.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List


def load_rows(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def summarize(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    bucket: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        key = (r["method"], r["budget_ratio"])
        bucket[key].append(r)

    summary: List[Dict[str, Any]] = []
    for (method, br), group in sorted(bucket.items()):
        summary.append({
            "method": method,
            "budget_ratio": br,
            "runs": len(group),
            "avg_num_nodes_before": mean(r["num_nodes_before"] for r in group),
            "avg_num_capsules": mean(r["num_capsules_after"] for r in group),
            "avg_num_retained": mean(r["num_retained"] for r in group),
            "avg_num_archived": mean(r["num_archived"] for r in group),
            "avg_compression_latency_sec": mean(r["compression_latency_sec"] for r in group),
        })
    return summary


def render_markdown(summary: List[Dict[str, Any]]) -> str:
    lines = [
        "| method | budget | avg_nodes_before | avg_capsules | avg_retained | avg_archived | avg_latency_s |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(
            f"| {row['method']} | {row['budget_ratio']:.2f} | "
            f"{row['avg_num_nodes_before']:.1f} | "
            f"{row['avg_num_capsules']:.1f} | "
            f"{row['avg_num_retained']:.1f} | "
            f"{row['avg_num_archived']:.1f} | "
            f"{row['avg_compression_latency_sec']:.4f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--format", choices=["json", "markdown"], default="markdown")
    args = p.parse_args()

    rows = load_rows(args.input)
    if not rows:
        print("(no rows)")
        return 0
    summary = summarize(rows)
    if args.format == "markdown":
        print(render_markdown(summary))
    else:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
