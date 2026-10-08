"""MIT licensed upstream StreamMeCo selection routines; see METHOD_PROVENANCE.json."""
from __future__ import annotations
import math
from collections import defaultdict
from typing import Dict,List,Set,Sequence
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import normalize

def _assign_rank_weights(scores: Dict[int, float], invert: bool = False) -> Dict[int, float]:
    """Normalize scores to [0, 1] and optionally invert for dissimilarity."""
    if not scores:
        return {}
    values = list(scores.values())
    min_v, max_v = min(values), max(values)
    if max_v == min_v:
        normalized = {k: 1.0 for k in scores}
    else:
        normalized = {k: (v - min_v) / (max_v - min_v) for k, v in scores.items()}
    if invert:
        return {k: 1.0 - v for k, v in normalized.items()}
    return normalized

def _adjust_keep_counts(
    cluster_members: Dict[int, List[int]],
    keep_ratio: float,
    target_total: int,
) -> Dict[int, int]:
    """Distribute keep counts per cluster so totals hit the desired ratio."""
    keep_counts: Dict[int, int] = {}
    raw_keeps: Dict[int, float] = {}
    base_total = 0
    for label, members in cluster_members.items():
        size = len(members)
        raw_keep = size * keep_ratio
        base_keep = max(1, min(size, int(math.ceil(raw_keep))))
        keep_counts[label] = base_keep
        raw_keeps[label] = raw_keep
        base_total += base_keep

    diff = target_total - base_total
    if diff > 0:
        # Allocate remaining quota to clusters with the largest fractional part, respecting capacity.
        order = sorted(
            cluster_members.keys(),
            key=lambda lbl: (raw_keeps[lbl] - math.floor(raw_keeps[lbl]), len(cluster_members[lbl])),
            reverse=True,
        )
        while diff > 0:
            progressed = False
            for label in order:
                capacity = len(cluster_members[label])
                if keep_counts[label] < capacity:
                    keep_counts[label] += 1
                    diff -= 1
                    progressed = True
                    if diff == 0:
                        break
            if not progressed:
                break
    elif diff < 0:
        # Trim extras from clusters with the smallest fractional part while keeping at least one element.
        order = sorted(
            cluster_members.keys(),
            key=lambda lbl: (raw_keeps[lbl] - math.floor(raw_keeps[lbl]), len(cluster_members[lbl])),
        )
        while diff < 0:
            progressed = False
            for label in order:
                if keep_counts[label] > 1:
                    keep_counts[label] -= 1
                    diff += 1
                    progressed = True
                    if diff == 0:
                        break
            if not progressed:
                break
    return keep_counts

def _greedy_farthest_selection(
    member_indices: List[int],
    data: np.ndarray,
    center: np.ndarray,
    keep_count: int,
) -> Set[int]:
    """Pick center-nearest, then iteratively farthest-from-selected within a cluster."""
    if keep_count >= len(member_indices):
        return set(member_indices)
    # First pick: closest to the cluster center.
    first_idx = max(member_indices, key=lambda ridx: float(np.dot(data[ridx], center)))
    selected: List[int] = [first_idx]
    while len(selected) < keep_count:
        best_candidate = None
        best_distance = -1.0
        for idx in member_indices:
            if idx in selected:
                continue
            # Cosine distance because data is normalized.
            nearest = min(1.0 - float(np.dot(data[idx], data[sidx])) for sidx in selected)
            if nearest > best_distance:
                best_distance = nearest
                best_candidate = idx
        if best_candidate is None:
            break
        selected.append(best_candidate)
    return set(selected)

def _select_via_spherical_kmeans(
    node_ids: Sequence[int],
    embeddings: Sequence[np.ndarray],
    cluster_ratio: float,
    keep_ratio: float,
) -> Set[int]:
    """Run spherical K-Means, keep 70% overall, distribute by cluster size with farthest-first inside each cluster."""
    if not node_ids:
        return set()
    if len(node_ids) == 1:
        return {node_ids[0]}
    data = normalize(np.stack(embeddings), axis=1)
    n_clusters = max(1, math.ceil(len(node_ids) * cluster_ratio))
    n_clusters = min(n_clusters, len(node_ids))
    if n_clusters == 1:
        target_total = max(1, min(len(node_ids), int(math.ceil(len(node_ids) * keep_ratio))))
        center = normalize(data.mean(axis=0).reshape(1, -1))[0]
        selected_indices = _greedy_farthest_selection(list(range(len(node_ids))), data, center, target_total)
        return {node_ids[idx] for idx in selected_indices}
    model = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
    labels = model.fit_predict(data)
    centers = normalize(model.cluster_centers_, axis=1)
    cluster_members: Dict[int, List[int]] = defaultdict(list)
    for idx, label in enumerate(labels):
        cluster_members[label].append(idx)

    target_total = max(1, min(len(node_ids), int(math.ceil(len(node_ids) * keep_ratio))))
    keep_counts = _adjust_keep_counts(cluster_members, keep_ratio, target_total)

    kept_indices: Set[int] = set()
    for label, member_indices in cluster_members.items():
        count = keep_counts.get(label, 0)
        if count <= 0:
            continue
        center = centers[label]
        selected = _greedy_farthest_selection(member_indices, data, center, count)
        kept_indices.update(selected)
    # Ensure we do not exceed total target due to rounding in rare cases.
    if len(kept_indices) > target_total:
        kept_indices = set(sorted(kept_indices)[: target_total])
    return {node_ids[idx] for idx in kept_indices}
