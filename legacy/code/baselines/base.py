"""Common ``Compressor`` protocol for baselines and RecallFlow.

Each baseline exposes ``Compressor.name`` and a ``fit`` method with the same
signature so the dispatch loop in ``run_recallflow_locomo`` is uniform.
"""
from __future__ import annotations

import os
import random
from typing import Callable, Dict, List, Protocol, Sequence

import numpy as np

from code.benchmarks.embed_backends import random_numpy_embed
from code.compression import (
    CompressedMemory,
    MemoryNode,
    ProbeQuery,
)
from code.compression.recallflow import (
    fit_compress,
    recallflow_compress,
    recallflow_prune_only,
)


EmbedFn = Callable[[str], List[float]]


class Compressor(Protocol):
    name: str

    def fit(
        self,
        nodes: Sequence[MemoryNode],
        probe_queries: Sequence[ProbeQuery],
        *,
        budget: int,
        embed_fn: EmbedFn,
        tau: float = 0.1,
        seed: int = 0,
    ) -> CompressedMemory:
        ...


# ---------------------------------------------------------------------------
# Pass-through helpers
# ---------------------------------------------------------------------------

def _ret(
    *,
    nodes: Sequence[MemoryNode],
    retained: Sequence[str],
    name: str,
    extra: Dict,
    tau: float,
    budget: int,
    probes: Sequence[ProbeQuery],
) -> CompressedMemory:
    node_ids = {n.node_id for n in nodes}
    retained = [r for r in retained if r in node_ids]
    archive = sorted(n.node_id for n in nodes if n.node_id not in set(retained))
    diag = {
        "method": name,
        "num_nodes_before": len(nodes),
        "num_probes": len(probes),
        "num_capsules": 0,
        "num_retained": len(retained),
        "num_archived": len(archive),
        "tau": tau,
        "budget": budget,
        "compression_latency_sec": 0.0,
    }
    diag.update(extra)
    return CompressedMemory(
        capsules=[],
        retained_node_ids=retained,
        archive_node_ids=archive,
        diagnostics=diag,
    )


def _ensure_emb(nodes, embed_fn, dim):
    out = []
    for n in nodes:
        if n.embedding is not None:
            v = list(n.embedding)
        else:
            v = list(embed_fn(n.text))
        out.append(v)
        d = len(v)
    return out


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------

class NoCompression:
    name = "no_compression"

    def fit(self, nodes, probe_queries, *, budget, embed_fn, tau=0.1, seed=0):
        retained = [n.node_id for n in nodes]
        return _ret(
            nodes=nodes,
            retained=retained,
            name=self.name,
            extra={"budget_ratio": 1.0},
            tau=tau,
            budget=budget,
            probes=probe_queries,
        )


class Random:
    name = "random"

    def fit(self, nodes, probe_queries, *, budget, embed_fn, tau=0.1, seed=0):
        rng = random.Random(seed)
        ids = [n.node_id for n in nodes]
        retained = sorted(rng.sample(ids, k=min(budget, len(ids))))
        return _ret(
            nodes=nodes,
            retained=retained,
            name=self.name,
            extra={"seed": seed},
            tau=tau,
            budget=budget,
            probes=probe_queries,
        )


class Recency:
    name = "recency"

    def fit(self, nodes, probe_queries, *, budget, embed_fn, tau=0.1, seed=0):
        ordered = sorted(nodes, key=lambda n: n.timestamp)
        retained = [n.node_id for n in ordered[-budget:]]
        return _ret(
            nodes=nodes,
            retained=retained,
            name=self.name,
            extra={},
            tau=tau,
            budget=budget,
            probes=probe_queries,
        )


class EmbeddingKCenter:
    """Farthest-first k-center on the (text) embedding space.

    Reference baseline: docs/experiment_plan.md §"embedding clustering".
    """

    name = "embedding_kcenter"

    def fit(self, nodes, probe_queries, *, budget, embed_fn, tau=0.1, seed=0):
        if budget <= 0 or not nodes:
            return _ret(
                nodes=nodes,
                retained=[],
                name=self.name,
                extra={"reason": "empty"},
                tau=tau, budget=budget, probes=probe_queries,
            )
        # Use the same embedding space RecallFlow uses for fingerprints here.
        from code.compression.coreset import select_representatives
        from code.compression.response import l2_normalize

        embs = np.asarray(_ensure_emb(nodes, embed_fn, dim=None), dtype=np.float64)
        embs = l2_normalize(embs, axis=1)
        # Pretend "mass = 1" so the coreset is a pure farthest-first pick.
        mass = np.ones(len(nodes))
        reps = select_representatives(embs, mass, budget=budget, seed=seed)
        retained = [nodes[i].node_id for i in reps]
        return _ret(
            nodes=nodes,
            retained=retained,
            name=self.name,
            extra={"seed": seed},
            tau=tau,
            budget=budget,
            probes=probe_queries,
        )


class SimilarityPruning:
    """StreamMeCo-like proxy: greedily prune nodes whose embedding is
    similar to an already-kept anchor.

    The anchor starts as the most "important" node (mass=1 selection on
    timestamps — here: the most recent node in the latest timestamp window).
    Then iterate: keep the node if its cosine distance to the nearest kept
    node exceeds a learned threshold (configurable via ``prune_threshold``).
    """

    name = "similarity_pruning"

    def fit(self, nodes, probe_queries, *, budget, embed_fn, tau=0.1, seed=0,
            prune_threshold: float = 0.05):
        from code.compression.response import l2_normalize

        if budget <= 0 or not nodes:
            return _ret(
                nodes=nodes,
                retained=[],
                name=self.name,
                extra={"reason": "empty"},
                tau=tau, budget=budget, probes=probe_queries,
            )
        embs = np.asarray(_ensure_emb(nodes, embed_fn, dim=None), dtype=np.float64)
        embs = l2_normalize(embs, axis=1)
        n = len(nodes)
        # Start by keeping the most-anchored node: largest timestamp.
        ordered = sorted(range(n), key=lambda i: nodes[i].timestamp)
        kept = [ordered[-1]]
        for i in ordered[:-1]:
            if len(kept) >= budget:
                break
            sim = embs[i] @ embs[kept].T
            if (1.0 - sim).min() > prune_threshold:
                kept.append(i)
        retained = [nodes[i].node_id for i in kept]
        return _ret(
            nodes=nodes,
            retained=retained,
            name=self.name,
            extra={"prune_threshold": prune_threshold, "kept": len(kept)},
            tau=tau, budget=budget, probes=probe_queries,
        )


class SimilarityMerging:
    """MemForest-like proxy: keep representatives, drop near-duplicates.

    For each node, if its cosine distance to an already-kept node is below
    ``merge_threshold`` AND its mass-from-probes is low, drop it; otherwise
    keep it (as a representative).
    """

    name = "similarity_merging"

    def fit(self, nodes, probe_queries, *, budget, embed_fn, tau=0.1, seed=0,
            merge_threshold: float = 0.10):
        from code.compression.response import l2_normalize

        if budget <= 0 or not nodes:
            return _ret(
                nodes=nodes,
                retained=[],
                name=self.name,
                extra={"reason": "empty"},
                tau=tau, budget=budget, probes=probe_queries,
            )
        embs = np.asarray(_ensure_emb(nodes, embed_fn, dim=None), dtype=np.float64)
        embs = l2_normalize(embs, axis=1)
        n = len(nodes)
        kept: list = [0]
        dropped: list = []
        for i in range(1, n):
            sim = embs[i] @ embs[kept].T
            if (1.0 - sim).min() < merge_threshold:
                dropped.append(i)
            else:
                kept.append(i)
        # Trim if we exceeded budget due to strict threshold.
        if len(kept) > budget:
            kept = kept[:budget]
        retained = [nodes[i].node_id for i in kept]
        return _ret(
            nodes=nodes,
            retained=retained,
            name=self.name,
            extra={"merge_threshold": merge_threshold, "kept": len(kept), "dropped": len(dropped)},
            tau=tau, budget=budget, probes=probe_queries,
        )


class RecallFlowPruneOnly:
    name = "recallflow_prune_only"

    def fit(self, nodes, probe_queries, *, budget, embed_fn, tau=0.1, seed=0):
        return recallflow_prune_only(
            nodes=nodes,
            probe_queries=probe_queries,
            embed_fn=embed_fn,
            budget=budget,
            tau=tau,
            coreset_seed=seed,
        )


class RecallFlowFull:
    name = "recallflow_full"

    def fit(self, nodes, probe_queries, *, budget, embed_fn, tau=0.1, seed=0):
        return recallflow_compress(
            nodes=nodes,
            probe_queries=probe_queries,
            embed_fn=embed_fn,
            budget=budget,
            tau=tau,
            coreset_seed=seed,
        )


REGISTRY: Dict[str, Compressor] = {
    cls.name: cls() for cls in [
        NoCompression,
        Random,
        Recency,
        EmbeddingKCenter,
        SimilarityPruning,
        SimilarityMerging,
        RecallFlowPruneOnly,
        RecallFlowFull,
    ]
}


def make_compressor(name: str) -> Compressor:
    if name not in REGISTRY:
        raise KeyError(
            f"unknown method '{name}'; available: {sorted(REGISTRY)}"
        )
    return REGISTRY[name]


__all__ = [
    "Compressor",
    "EmbedFn",
    "NoCompression",
    "Random",
    "Recency",
    "EmbeddingKCenter",
    "SimilarityPruning",
    "SimilarityMerging",
    "RecallFlowPruneOnly",
    "RecallFlowFull",
    "REGISTRY",
    "make_compressor",
]
