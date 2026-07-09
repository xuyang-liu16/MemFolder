"""Capsule builder with residual routing.

Reference: docs/recallflow_implementation_guide.md §5, §7.

Residual routing uses two percentile cutoffs:
    * ``low_mass_bar`` is computed on the GLOBAL mass distribution (a node
      that almost no probe ever lights up is archive-worthy, regardless of
      which cluster it belongs to).
    * ``exception_bar`` is computed CLUSTER-LOCALLY (the most atypical nodes
      in a cluster may carry rare evidence and deserve to be kept as
      exceptions).
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np

from .response import l2_normalize
from .schema import MemoryCapsule, MemoryNode


def assign_to_representatives(
    fingerprints: Sequence[Sequence[float]],
    representative_indices: Sequence[int],
) -> Tuple[np.ndarray, np.ndarray]:
    """Assign every node to its nearest representative by cosine distance.

    Returns ``(assignments, residuals)`` arrays of shape ``[N]``.
    See §5.2.
    """
    f = l2_normalize(np.asarray(fingerprints, dtype=np.float64), axis=1)
    reps = np.asarray(representative_indices, dtype=np.int64)
    if reps.size == 0:
        raise ValueError("representative_indices must be non-empty")
    if f.shape[0] == 0:
        raise ValueError("fingerprints must be non-empty")
    rep_feats = f[reps]
    sim = f @ rep_feats.T  # [N, R]
    dist = 1.0 - sim
    assignments = np.argmin(dist, axis=1)
    residuals = dist[np.arange(f.shape[0]), assignments]
    return assignments, residuals


def route_cluster_members(
    member_indices: Sequence[int],
    residuals: np.ndarray,
    mass: np.ndarray,
    *,
    low_mass_quantile: float = 0.2,
    exception_quantile: float = 0.8,
) -> Tuple[List[int], List[int], List[int]]:
    """Decide per-cluster actions: merge / exception / archive.

    See §5.3 of the implementation guide. ``low_mass_bar`` is computed on the
    global ``mass`` (cluster-independent); ``exception_bar`` is computed
    inside the cluster's residual distribution.
    """
    if not 0.0 < low_mass_quantile < 1.0:
        raise ValueError("low_mass_quantile must be in (0, 1)")
    if not 0.0 < exception_quantile < 1.0:
        raise ValueError("exception_quantile must be in (0, 1)")

    member_indices = list(member_indices)
    if not member_indices:
        return [], [], []

    res = np.asarray(residuals, dtype=np.float64)
    m = np.asarray(mass, dtype=np.float64)
    low_mass_bar = float(np.quantile(m, low_mass_quantile))
    exception_bar = float(np.quantile(res[member_indices], exception_quantile))

    merge_ids: List[int] = []
    exception_ids: List[int] = []
    archive_ids: List[int] = []
    for idx in member_indices:
        if m[idx] <= low_mass_bar:
            archive_ids.append(idx)
        elif res[idx] >= exception_bar:
            exception_ids.append(idx)
        else:
            merge_ids.append(idx)
    return merge_ids, exception_ids, archive_ids


def simple_capsule_summary(
    nodes: Sequence[MemoryNode],
    merge_indices: Sequence[int],
    *,
    max_items: int = 5,
) -> str:
    """No-LLM summary: ``/``-joined first ``max_items`` merge texts. §7."""
    parts = [nodes[i].text for i in merge_indices[:max_items]]
    parts = [p for p in parts if p]
    return " / ".join(parts) if parts else ""


def build_capsules(
    nodes: Sequence[MemoryNode],
    representative_indices: Sequence[int],
    assignments: np.ndarray,
    residuals: np.ndarray,
    mass: np.ndarray,
    *,
    low_mass_quantile: float = 0.2,
    exception_quantile: float = 0.8,
    capsule_id_prefix: str = "cap",
) -> List[MemoryCapsule]:
    """Build capsules for every representative node. See §7."""
    nodes_list = list(nodes)
    reps = list(representative_indices)
    capsules: List[MemoryCapsule] = []
    reps_arr = np.asarray(reps, dtype=np.int64)

    for local_rep_id, rep_idx in enumerate(reps):
        member_indices = np.where(assignments == local_rep_id)[0].tolist()
        if rep_idx not in member_indices:
            member_indices.append(int(rep_idx))

        merge_ids, exception_ids, archive_ids = route_cluster_members(
            member_indices=member_indices,
            residuals=residuals,
            mass=mass,
            low_mass_quantile=low_mass_quantile,
            exception_quantile=exception_quantile,
        )
        # The representative itself is preserved verbatim, never archived.
        merge_ids = [i for i in merge_ids if i != rep_idx]
        exception_ids = [i for i in exception_ids if i != rep_idx]
        archive_ids = [i for i in archive_ids if i != rep_idx]

        member_node_ids = [nodes_list[i].node_id for i in member_indices]
        timestamps = [nodes_list[i].timestamp for i in member_indices]
        entities = sorted({e for i in member_indices for e in nodes_list[i].entities})
        raw_pointers = [
            nodes_list[i].raw_pointer
            for i in member_indices
            if getattr(nodes_list[i], "raw_pointer", None)
        ]

        cap = MemoryCapsule(
            capsule_id=f"{capsule_id_prefix}_{local_rep_id:04d}",
            representative_id=nodes_list[rep_idx].node_id,
            member_node_ids=member_node_ids,
            merge_node_ids=[nodes_list[i].node_id for i in merge_ids],
            exception_node_ids=[nodes_list[i].node_id for i in exception_ids],
            archive_node_ids=[nodes_list[i].node_id for i in archive_ids],
            summary=simple_capsule_summary(nodes_list, merge_ids),
            timestamp_span=(float(min(timestamps)), float(max(timestamps)))
            if timestamps
            else None,
            entities=entities,
            raw_pointers=raw_pointers,
        )
        capsules.append(cap)
    return capsules


def capsules_retained_ids(capsules: Sequence[MemoryCapsule]) -> List[str]:
    """Union of representative + exception node ids across capsules."""
    kept = set()
    for cap in capsules:
        kept.add(cap.representative_id)
        kept.update(cap.exception_node_ids)
    return sorted(kept)


__all__ = [
    "assign_to_representatives",
    "route_cluster_members",
    "simple_capsule_summary",
    "build_capsules",
    "capsules_retained_ids",
]
