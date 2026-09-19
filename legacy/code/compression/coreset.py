"""Response-space coreset selection.

Reference: docs/recallflow_implementation_guide.md §6 (Coverage coreset).

v0 rule: farthest-first k-center with mass tiebreak. The greedy score at
each step is
    score_i = min_dist_i * log1p(mass_i)
where ``min_dist_i`` is the cosine distance from node ``i`` to the nearest
representative picked so far. This balances coverage (farthest-first) with
retrieval demand (mass). No additional lambdas are introduced.
"""
from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np

from .response import l2_normalize


def select_representatives(
    fingerprints: Sequence[Sequence[float]],
    mass: Sequence[float],
    *,
    budget: int,
    seed: int = 0,
) -> list:
    """Pick ``budget`` representative node indices via farthest-first k-center.

    Returns a list of integer indices into ``fingerprints``.

    Edge cases (documented in §6.1):
        * ``budget >= n`` → returns ``range(n)``.
        * ``budget <= 0`` → returns ``[]``.
        * Ties in ``score`` are broken deterministically by ``np.argmax``
          (first occurrence wins) modulated by the optional ``seed``.
    """
    f = l2_normalize(np.asarray(fingerprints, dtype=np.float64), axis=1)
    n = f.shape[0]
    if n == 0:
        return []

    b = int(budget)
    if b <= 0:
        return []
    if b >= n:
        return list(range(n))

    mass_arr = np.asarray(mass, dtype=np.float64)
    log_mass = np.log1p(np.maximum(mass_arr, 0.0))

    # First pick: node with the largest mass (mass tiebreak).
    seed_idx = int(np.argmax(log_mass))
    selected = [seed_idx]

    # Distance to the nearest representative so far; start with -1 so the
    # first iteration's argmax naturally picks the largest log_mass node.
    sim_to_sel = f @ f[seed_idx]
    min_dist = 1.0 - sim_to_sel
    min_dist[seed_idx] = -1.0  # already selected

    rng = np.random.default_rng(seed)

    while len(selected) < b:
        score = min_dist * log_mass
        score[selected] = -1.0
        # Tie-breaking jitter: when several nodes share the same score,
        # ``argmax`` picks the first. Add a tiny deterministic jitter so
        # smoke tests are reproducible across reruns while still diverse.
        jitter = rng.uniform(0.0, 1e-9, size=score.shape)
        score = score + jitter
        nxt = int(np.argmax(score))
        if nxt in selected:
            # numerical fallback: take the unselected node with max mass.
            unselected = [i for i in range(n) if i not in selected]
            nxt = max(unselected, key=lambda i: log_mass[i])
        selected.append(nxt)
        # Update min_dist with the new representative.
        sim_to_new = f @ f[nxt]
        min_dist = np.minimum(min_dist, 1.0 - sim_to_new)
        min_dist[nxt] = -1.0

    return selected


__all__ = ["select_representatives"]
