"""Embedding backends for local smoke tests."""
from __future__ import annotations

import hashlib
from typing import Callable, List

import numpy as np


def random_numpy_embed(dim: int = 32, seed: int = 0) -> Callable[[str], List[float]]:
    """Return a deterministic pseudo-embedding function for tests."""

    def embed(text: str) -> List[float]:
        digest = hashlib.sha256(f"{seed}:{text}".encode("utf-8")).digest()
        local_seed = int.from_bytes(digest[:8], "big", signed=False)
        rng = np.random.default_rng(local_seed)
        return rng.standard_normal(dim).astype(float).tolist()

    return embed


__all__ = ["random_numpy_embed"]
