"""RecallFlow main entry point.

Reference: docs/recallflow_implementation_guide.md §8 (RecallFlow v0 主流程).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from .capsule import (
    assign_to_representatives,
    build_capsules,
    capsules_retained_ids,
)
from .coreset import select_representatives
from .probes import build_probe_queries
from .response import compute_response_fingerprints
from .schema import MemoryCapsule, MemoryNode, ProbeQuery


EmbedFn = Callable[[str], List[float]]


@dataclass
class CompressedMemory:
    """Compressor output, in the protocol used by all baselines."""

    capsules: List[MemoryCapsule] = field(default_factory=list)
    retained_node_ids: List[str] = field(default_factory=list)
    archive_node_ids: List[str] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)


def _ensure_embeddings(
    nodes: Sequence[MemoryNode],
    embed_fn: EmbedFn,
    dim: Optional[int] = None,
) -> List[List[float]]:
    out: List[List[float]] = []
    for n in nodes:
        if n.embedding is not None:
            emb = list(n.embedding)
        else:
            emb = list(embed_fn(n.text))
        if dim is None:
            dim = len(emb)
        elif len(emb) != dim:
            raise ValueError(
                f"node {n.node_id} embedding dim {len(emb)} != expected {dim}"
            )
        out.append(emb)
    return out


def recallflow_compress(
    nodes: Sequence[MemoryNode],
    probe_queries: Sequence[ProbeQuery],
    embed_fn: EmbedFn,
    *,
    budget: int,
    tau: float = 0.1,
    low_mass_quantile: float = 0.2,
    exception_quantile: float = 0.8,
    coreset_seed: int = 0,
) -> CompressedMemory:
    """Run the full RecallFlow v0 pipeline and return a ``CompressedMemory``.

    Hard-coded ``tau`` default is 0.1; override only for sensitivity studies.
    """
    n_list = list(nodes)
    if budget < 0:
        raise ValueError("budget must be non-negative")
    if not n_list:
        return CompressedMemory(
            capsules=[],
            retained_node_ids=[],
            archive_node_ids=[],
            diagnostics={"reason": "empty memory stream"},
        )

    t0 = perf_counter()
    node_embs = _ensure_embeddings(n_list, embed_fn)
    query_embs = [embed_fn(q.text) for q in probe_queries]
    t_embed = perf_counter() - t0

    # §4.2 — response matrix and fingerprints.
    response, fingerprints, mass = compute_response_fingerprints(
        query_embs=query_embs,
        node_embs=node_embs,
        tau=tau,
    )
    # §6 — farthest-first k-center with mass tiebreak.
    b = int(min(budget, len(n_list)))
    reps = select_representatives(
        fingerprints=fingerprints,
        mass=mass,
        budget=b,
        seed=coreset_seed,
    )
    # §5.2 — assignment + residuals in response space.
    assignments, residuals = assign_to_representatives(
        fingerprints=fingerprints,
        representative_indices=reps,
    )
    # §7 — capsules.
    capsules = build_capsules(
        nodes=n_list,
        representative_indices=reps,
        assignments=assignments,
        residuals=residuals,
        mass=mass,
        low_mass_quantile=low_mass_quantile,
        exception_quantile=exception_quantile,
    )

    retained = capsules_retained_ids(capsules)
    archive_all = sorted(
        {nid for cap in capsules for nid in cap.archive_node_ids}
    )
    # Any node that the coreset did not retain is implicitly archived.
    retained_set = set(retained)
    implicit_archive = sorted(
        n.node_id for n in n_list if n.node_id not in retained_set
    )

    diagnostics: Dict[str, Any] = {
        "tau": tau,
        "budget": b,
        "num_nodes_before": len(n_list),
        "num_probes": len(probe_queries),
        "num_capsules": len(capsules),
        "num_retained": len(retained),
        "num_exceptions": sum(len(c.exception_node_ids) for c in capsules),
        "num_archived": len(implicit_archive),
        "low_mass_quantile": low_mass_quantile,
        "exception_quantile": exception_quantile,
        "compression_latency_sec": float(perf_counter() - t0),
        "embedding_latency_sec": float(t_embed),
        "response_mass_total": float(mass.sum()),
        "response_mass_max": float(mass.max()) if mass.size else 0.0,
        "response_mass_mean": float(mass.mean()) if mass.size else 0.0,
        "representative_indices": [int(x) for x in reps],
        "assignments": assignments.tolist(),
        "residuals": residuals.tolist(),
        "mass": mass.tolist(),
    }

    return CompressedMemory(
        capsules=capsules,
        retained_node_ids=retained,
        archive_node_ids=implicit_archive,
        diagnostics=diagnostics,
    )


def recallflow_prune_only(
    nodes: Sequence[MemoryNode],
    probe_queries: Sequence[ProbeQuery],
    embed_fn: EmbedFn,
    *,
    budget: int,
    tau: float = 0.1,
    coreset_seed: int = 0,
) -> CompressedMemory:
    """Ablation: representative-only, no capsules.

    Retained ids = representative ids. Useful as the "no capsule" baseline
    paired with ``recallflow_compress`` for the §6.3 ablation in
    ``docs/recallflow_method.md``.
    """
    n_list = list(nodes)
    if budget < 0:
        raise ValueError("budget must be non-negative")
    if not n_list:
        return CompressedMemory()
    node_embs = _ensure_embeddings(n_list, embed_fn)
    query_embs = [embed_fn(q.text) for q in probe_queries]
    _, fingerprints, mass = compute_response_fingerprints(
        query_embs=query_embs,
        node_embs=node_embs,
        tau=tau,
    )
    b = int(min(budget, len(n_list)))
    reps = select_representatives(
        fingerprints=fingerprints,
        mass=mass,
        budget=b,
        seed=coreset_seed,
    )
    retained = [n_list[i].node_id for i in reps]
    implicit_archive = sorted(
        n.node_id for n in n_list if n.node_id not in set(retained)
    )
    return CompressedMemory(
        capsules=[],
        retained_node_ids=retained,
        archive_node_ids=implicit_archive,
        diagnostics={
            "tau": tau,
            "budget": b,
            "num_nodes_before": len(n_list),
            "num_probes": len(probe_queries),
            "num_capsules": 0,
            "num_retained": len(retained),
            "num_archived": len(implicit_archive),
            "compression_latency_sec": 0.0,
        },
    )


def _node_embeddings_present(nodes: Sequence[MemoryNode]) -> List[List[float]]:
    out: List[List[float]] = []
    for node in nodes:
        if node.embedding is None:
            raise ValueError("all MemoryNode.embedding values must be present before URB compression")
        out.append(list(node.embedding))
    return out


def recallflow_urb_prune_only(
    nodes: Sequence[MemoryNode],
    urb_centroids: Sequence[Sequence[float]],
    *,
    budget: int,
    tau: float = 0.1,
    coreset_seed: int = 0,
) -> CompressedMemory:
    """Compress with fixed URB response fingerprints.

    Reference: docs/recallflow_urb_experiment_protocol.md §5, §9.3.
    """
    n_list = list(nodes)
    if budget < 0:
        raise ValueError("budget must be non-negative")
    if not n_list:
        return CompressedMemory()

    node_embs = _node_embeddings_present(n_list)
    response, fingerprints, mass = compute_response_fingerprints(
        query_embs=urb_centroids,
        node_embs=node_embs,
        tau=tau,
    )
    b = int(min(budget, len(n_list)))
    reps = select_representatives(fingerprints, mass, budget=b, seed=coreset_seed)
    retained = [n_list[i].node_id for i in reps]
    archive = sorted(n.node_id for n in n_list if n.node_id not in set(retained))
    return CompressedMemory(
        retained_node_ids=retained,
        archive_node_ids=archive,
        diagnostics={
            "tau": tau,
            "budget": b,
            "representative_budget": b,
            "num_nodes_before": len(n_list),
            "num_nodes_after": len(retained),
            "num_representatives": len(reps),
            "response_shape": list(response.shape),
            "fingerprint_shape": list(fingerprints.shape),
            "representative_indices": [int(x) for x in reps],
            "assignments": [],
            "residuals": [],
            "mass": mass.tolist(),
        },
    )


def recallflow_compress_with_urb(
    nodes: Sequence[MemoryNode],
    urb_centroids: Sequence[Sequence[float]],
    *,
    budget: int,
    tau: float = 0.1,
    low_mass_quantile: float = 0.2,
    exception_quantile: float = 0.8,
    coreset_seed: int = 0,
) -> CompressedMemory:
    """Full RecallFlow-URB compression with capsules.

    Reference: docs/recallflow_urb_experiment_protocol.md §6, §9.3.
    """
    n_list = list(nodes)
    if budget < 0:
        raise ValueError("budget must be non-negative")
    if not n_list:
        return CompressedMemory()

    node_embs = _node_embeddings_present(n_list)
    response, fingerprints, mass = compute_response_fingerprints(
        query_embs=urb_centroids,
        node_embs=node_embs,
        tau=tau,
    )
    b = int(min(budget, len(n_list)))
    reps = select_representatives(fingerprints, mass, budget=b, seed=coreset_seed)
    assignments, residuals = assign_to_representatives(fingerprints, reps)
    capsules = build_capsules(
        nodes=n_list,
        representative_indices=reps,
        assignments=assignments,
        residuals=residuals,
        mass=mass,
        low_mass_quantile=low_mass_quantile,
        exception_quantile=exception_quantile,
    )
    retained = capsules_retained_ids(capsules)
    archive = sorted(n.node_id for n in n_list if n.node_id not in set(retained))
    return CompressedMemory(
        capsules=capsules,
        retained_node_ids=retained,
        archive_node_ids=archive,
        diagnostics={
            "tau": tau,
            "budget": b,
            "representative_budget": b,
            "num_nodes_before": len(n_list),
            "num_nodes_after": len(retained),
            "num_retained_after_exceptions": len(retained),
            "num_representatives": len(reps),
            "num_exceptions": sum(len(c.exception_node_ids) for c in capsules),
            "num_capsules": len(capsules),
            "response_shape": list(response.shape),
            "fingerprint_shape": list(fingerprints.shape),
            "representative_indices": [int(x) for x in reps],
            "assignments": assignments.tolist(),
            "residuals": residuals.tolist(),
            "mass": mass.tolist(),
        },
    )


def fit_compress(
    nodes: Sequence[MemoryNode],
    embed_fn: EmbedFn,
    *,
    budget: int,
    tau: float = 0.1,
    window_size: int = 8,
    max_probes: int = 64,
    probe_types: Sequence[str] = ("entity", "temporal", "event"),
) -> CompressedMemory:
    """Convenience wrapper: build probes + run recallflow_compress."""
    probes = build_probe_queries(
        nodes,
        window_size=window_size,
        max_probes=max_probes,
        probe_types=probe_types,
    )
    return recallflow_compress(
        nodes=nodes,
        probe_queries=probes,
        embed_fn=embed_fn,
        budget=budget,
        tau=tau,
    )


__all__ = [
    "CompressedMemory",
    "recallflow_compress",
    "recallflow_prune_only",
    "recallflow_urb_prune_only",
    "recallflow_compress_with_urb",
    "fit_compress",
]
