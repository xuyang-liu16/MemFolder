"""Ported from the user-designated standard release; see docs/METHOD_PROVENANCE.json."""
from __future__ import annotations
from .common import numpy
NEIGHBOR_K = 5
def cosine_distance(cosine: np.ndarray) -> np.ndarray:
    np = numpy()
    distance = 2.0 * (1.0 - cosine)
    np.fill_diagonal(distance, 0.0)
    return distance

def stable_argmax(scores: np.ndarray, candidates: np.ndarray, node_ids: tuple[str, ...]) -> int:
    """``argmax`` with ties broken by node id, not by array position.

    Floating-point scores tie often enough here to matter; breaking on the id
    string makes a run reproducible regardless of how the store was scrolled.
    """
    np = numpy()
    candidate_scores = scores[candidates]
    maximum = float(np.max(candidate_scores))
    tied = candidates[np.isclose(candidate_scores, maximum, atol=1e-12, rtol=0.0)]
    return int(min(tied, key=lambda row: node_ids[int(row)]))

def delta(density: np.ndarray, distance: np.ndarray, candidates: np.ndarray) -> np.ndarray:
    """Distance from each candidate to the nearest strictly denser candidate.

    The densest candidate has no denser neighbour, so it falls back to its
    furthest distance -- which is what makes it win ``rho * delta`` and become
    the peak.
    """
    np = numpy()
    output = np.zeros(len(density), dtype=np.float64)
    local_density = density[candidates]
    thresholds = local_density + 1e-12 * np.maximum(1.0, np.abs(local_density))
    denser = local_density[None, :] > thresholds[:, None]
    local_distance = distance[np.ix_(candidates, candidates)]
    nearest = np.min(np.where(denser, local_distance, np.inf), axis=1)
    fallback = np.max(local_distance, axis=1)
    output[candidates] = np.where(np.any(denser, axis=1), nearest, fallback)
    return output

def density_peaks(
    *,
    node_ids: tuple[str, ...],
    distance: np.ndarray,
    target: int,
    neighbor_k: int = NEIGHBOR_K,
) -> list[int]:
    """Select ``target`` anchors by the TG-DPC recurrence. Returns row indices."""
    np = numpy()
    matrix = np.asarray(distance, dtype=np.float64)
    count = len(node_ids)
    if matrix.shape != (count, count) or not np.all(np.isfinite(matrix)):
        raise ValueError("anchor selection needs a finite all-pairs distance matrix")

    # --- first anchor: the global density peak -----------------------------
    masked = matrix.copy()
    np.fill_diagonal(masked, np.inf)
    k = min(int(neighbor_k), count - 1)
    nearest = np.partition(masked, k - 1, axis=1)[:, :k]
    density = np.exp(-np.mean(nearest, axis=1))
    everything = np.arange(count, dtype=np.int64)
    first = stable_argmax(density * delta(density, matrix, everything), everything, node_ids)

    selected = [first]
    selected_mask = np.zeros(count, dtype=bool)
    selected_mask[first] = True

    # --- remaining anchors: density measured against the selected set ------
    while len(selected) < target:
        candidates = np.flatnonzero(~selected_mask)
        selected_rows = np.asarray(selected, dtype=np.int64)
        current_k = min(int(neighbor_k), len(selected))
        to_selected = matrix[np.ix_(candidates, selected_rows)]
        nearest_selected = np.partition(to_selected, current_k - 1, axis=1)[:, :current_k]
        density = np.zeros(count, dtype=np.float64)
        density[candidates] = 1.0 - np.exp(-np.mean(nearest_selected, axis=1))
        score = density * delta(density, matrix, candidates)
        winner = stable_argmax(score, candidates, node_ids)
        selected.append(winner)
        selected_mask[winner] = True
    return selected

def baseline_partition(
    *, node_ids: tuple[str, ...], distance: np.ndarray, anchors: list[int]
) -> dict[int, list[int]]:
    """``pi0``: assign every non-anchor to its nearest anchor."""
    np = numpy()
    anchor_rows = np.asarray(anchors, dtype=np.int64)
    anchor_set = set(anchors)
    groups: dict[int, list[int]] = {anchor: [anchor] for anchor in anchors}
    for index in range(len(node_ids)):
        if index in anchor_set:
            continue
        values = distance[index, anchor_rows]
        minimum = float(np.min(values))
        tied = [
            anchors[position]
            for position, value in enumerate(values)
            if np.isclose(value, minimum, atol=1e-12)
        ]
        groups[min(tied, key=lambda row: node_ids[row])].append(index)
    return groups
