"""Response matrix and fingerprints.

Reference: docs/recallflow_implementation_guide.md §4 (Response 分数).
"""
from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np


def l2_normalize(x: np.ndarray, *, axis: int = -1, eps: float = 1e-12) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64)
    norm = np.linalg.norm(arr, axis=axis, keepdims=True)
    return arr / np.maximum(norm, eps)


def softmax(x: np.ndarray, *, axis: int = -1) -> np.ndarray:
    x = np.asarray(x)
    x = x - np.max(x, axis=axis, keepdims=True)
    exp = np.exp(x)
    return exp / np.sum(exp, axis=axis, keepdims=True)


def compute_response_fingerprints(
    query_embs: Sequence[Sequence[float]],
    node_embs: Sequence[Sequence[float]],
    *,
    tau: float = 0.1,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute response matrix, fingerprints, and per-node mass.

    Returns:
        response: np.ndarray, shape [num_queries, num_nodes]
        fingerprints: np.ndarray, shape [num_nodes, num_queries]
        mass: np.ndarray, shape [num_nodes]
    """
    if tau <= 0:
        raise ValueError("tau must be positive")
    q = np.asarray(query_embs, dtype=np.float64)
    n = np.asarray(node_embs, dtype=np.float64)
    if q.ndim != 2 or n.ndim != 2:
        raise ValueError("query_embs and node_embs must be 2-D")
    if q.shape[0] == 0 or n.shape[0] == 0:
        raise ValueError("query_embs and node_embs must be non-empty")
    if q.shape[1] != n.shape[1]:
        raise ValueError(
            f"embedding dim mismatch: query={q.shape[1]} vs node={n.shape[1]}"
        )

    q = l2_normalize(q, axis=1)
    n = l2_normalize(n, axis=1)
    scores = q @ n.T  # [Q, N]
    response = softmax(scores / tau, axis=1)
    fingerprints = response.T  # [N, Q]
    mass = fingerprints.sum(axis=1)  # [N]
    return response, fingerprints, mass


__all__ = ["l2_normalize", "softmax", "compute_response_fingerprints"]
