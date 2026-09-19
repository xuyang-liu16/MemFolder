"""Run RecallFlow-URB P0 compression diagnostics.

P0 reads Mem0 memory nodes only and does not read QA/gold/evidence fields.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
from openai import OpenAI

from code.baselines.base import EmbeddingKCenter
from code.compression.recallflow import recallflow_compress_with_urb, recallflow_urb_prune_only
from code.compression.schema import MemoryNode
from code.compression.urb import default_urb, load_or_compute_centroids


FORBIDDEN_FIELDS = {
    "question", "questions", "qa", "answer", "answers",
    "gold", "gold_answer", "evidence", "supporting_facts",
}


def load_nodes(path: Path, *, allow_extra_fields: bool = False) -> List[MemoryNode]:
    allowed = set(MemoryNode.__dataclass_fields__)
    nodes: List[MemoryNode] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        forbidden = FORBIDDEN_FIELDS & set(row)
        if forbidden:
            raise ValueError(f"forbidden fields at line {line_no}: {sorted(forbidden)}")
        extra = set(row) - allowed
        if extra and not allow_extra_fields:
            raise ValueError(f"unexpected fields at line {line_no}: {sorted(extra)}")
        nodes.append(MemoryNode.from_dict({k: row[k] for k in allowed if k in row}))
    return nodes


def make_openai_embedder(model: str, dim: int):
    api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    if not api_key:
        raise RuntimeError("missing EMBEDDING_API_KEY/DASHSCOPE_API_KEY for URB centroid embedding")
    client = OpenAI(api_key=api_key, base_url=base_url)

    def embed(text: str) -> List[float]:
        result = client.embeddings.create(model=model, input=text, dimensions=dim)
        return list(result.data[0].embedding)

    return embed


def ensure_node_embeddings(nodes: List[MemoryNode], embed_fn, dim: int) -> None:
    for node in nodes:
        if node.embedding is None:
            node.embedding = list(embed_fn(node.text))
        if len(node.embedding) != dim:
            raise ValueError(f"{node.node_id} embedding dim {len(node.embedding)} != {dim}")


def write_nodes(nodes: Iterable[MemoryNode], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for node in nodes:
            f.write(json.dumps(node.to_dict(), ensure_ascii=False) + "\n")


def leakage_audit() -> Dict[str, bool]:
    return {
        "compression_reads_qa": False,
        "compression_reads_gold": False,
        "compression_reads_evidence": False,
        "basis_is_fixed": True,
        "basis_conditioned_on_sample": False,
    }


def capsule_dicts(cm) -> List[Dict]:
    return [cap.to_dict() for cap in cm.capsules]


def method_summary(method: str, cm, budget: int, diagnostics_path: Path) -> Dict:
    diag = cm.diagnostics
    return {
        "method": method,
        "budget": budget,
        "num_nodes_before": diag.get("num_nodes_before"),
        "num_nodes_after": len(cm.retained_node_ids),
        "num_representatives": diag.get("num_representatives", len(cm.retained_node_ids)),
        "num_exceptions": diag.get("num_exceptions", 0),
        "diagnostics_path": str(diagnostics_path),
    }


def dump_detail(path: Path, method: str, cm, extra: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    diag = dict(cm.diagnostics)
    detail = {
        "method": method,
        "retained_node_ids": cm.retained_node_ids,
        "archive_node_ids": cm.archive_node_ids,
        "representative_ids": extra.get("representative_ids", cm.retained_node_ids),
        "capsules": capsule_dicts(cm),
        "leakage_audit": leakage_audit(),
    }
    detail.update(diag)
    detail.update(extra)
    path.write_text(json.dumps(detail, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="RecallFlow-URB P0 diagnostics.")
    parser.add_argument("--input-memory-nodes", required=True)
    parser.add_argument("--methods", required=True)
    parser.add_argument("--budget-ratio", type=float, default=0.5)
    parser.add_argument("--embedding-model", default="text-embedding-v4")
    parser.add_argument("--embedding-dim", type=int, default=1024)
    parser.add_argument("--basis-version", default="urb_v0")
    parser.add_argument("--tau", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--fill-missing-embeddings", action="store_true")
    parser.add_argument("--embedded-output", default=None)
    parser.add_argument("--allow-extra-fields", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--diagnostics-dir", required=True)
    args = parser.parse_args()

    nodes = load_nodes(Path(args.input_memory_nodes), allow_extra_fields=args.allow_extra_fields)
    if not nodes:
        raise ValueError("input contains no memory nodes")
    embed_fn = make_openai_embedder(args.embedding_model, args.embedding_dim)
    if any(n.embedding is None for n in nodes):
        if not args.fill_missing_embeddings:
            raise ValueError("missing node embeddings; pass --fill-missing-embeddings")
        ensure_node_embeddings(nodes, embed_fn, args.embedding_dim)
        if args.embedded_output:
            write_nodes(nodes, Path(args.embedded_output))
    else:
        ensure_node_embeddings(nodes, embed_fn=lambda text: [], dim=args.embedding_dim)

    basis = default_urb(args.basis_version)
    centroids, basis_meta = load_or_compute_centroids(
        basis,
        embed_fn,
        embedding_model=args.embedding_model,
        embedding_dim=args.embedding_dim,
    )
    budget = max(1, int(round(args.budget_ratio * len(nodes)))) if nodes else 0
    diag_dir = Path(args.diagnostics_dir)
    rows = []

    for method in [m.strip() for m in args.methods.split(",") if m.strip()]:
        if method == "embedding_kcenter":
            cm = EmbeddingKCenter().fit(nodes, [], budget=budget, embed_fn=embed_fn, tau=args.tau, seed=args.seed)
            rep_ids = list(cm.retained_node_ids)
        elif method == "recallflow_urb_prune_only":
            cm = recallflow_urb_prune_only(nodes, centroids, budget=budget, tau=args.tau, coreset_seed=args.seed)
            rep_ids = [nodes[i].node_id for i in cm.diagnostics["representative_indices"]]
        elif method == "recallflow_urb_full":
            cm = recallflow_compress_with_urb(nodes, centroids, budget=budget, tau=args.tau, coreset_seed=args.seed)
            rep_ids = [nodes[i].node_id for i in cm.diagnostics["representative_indices"]]
        else:
            raise ValueError(f"unknown method: {method}")

        detail_path = diag_dir / f"{method}_budget{int(args.budget_ratio * 100)}_seed{args.seed}.json"
        dump_detail(detail_path, method, cm, {
            "basis_meta": basis_meta,
            "representative_ids": rep_ids,
            "leakage_audit": leakage_audit(),
        })
        rows.append(method_summary(method, cm, budget, detail_path))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(out), "num_rows": len(rows), "num_nodes": len(nodes), "budget": budget}))


if __name__ == "__main__":
    main()
