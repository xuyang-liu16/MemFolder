"""The node universe of one LoCoMo sample.

A :class:`Scope` is the immutable input to the whole method: an ordered list of
memory nodes with L2-normalised embeddings.  The order is qdrant's scroll order
and is the meaning of ``member_indices`` in every plan file, so it is fixed here
once and never re-derived.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from pathlib import Path

import numpy as np

from . import store as store_io
from .jsonio import sha256_json


@dataclass(frozen=True)
class Scope:
    sample: int
    source_store: Path
    points: tuple[store_io.Point, ...]

    # ------------------------------------------------------------- projections

    @cached_property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(point.node_id for point in self.points)

    @cached_property
    def texts(self) -> tuple[str, ...]:
        return tuple(point.text for point in self.points)

    @cached_property
    def timestamps(self) -> tuple[str, ...]:
        return tuple(point.timestamp for point in self.points)

    @cached_property
    def embeddings(self) -> np.ndarray:
        """``(N, D)`` row-normalised embedding matrix."""
        matrix = np.stack([point.vector for point in self.points]).astype(np.float64)
        norms = np.clip(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12, None)
        return matrix / norms

    @cached_property
    def index_of(self) -> dict[str, int]:
        return {node_id: index for index, node_id in enumerate(self.node_ids)}

    @cached_property
    def event_times(self) -> tuple[datetime, ...]:
        return tuple(point.event_time for point in self.points)

    @cached_property
    def by_id(self) -> dict[str, store_io.Point]:
        return {point.node_id: point for point in self.points}

    # ------------------------------------------------------------------ helpers

    def __len__(self) -> int:
        return len(self.points)

    @property
    def scope_id(self) -> str:
        return f"sample_{self.sample:03d}"

    def cosine(self) -> np.ndarray:
        """All-pairs cosine similarity, clipped to ``[-1, 1]``."""
        return np.clip(self.embeddings @ self.embeddings.T, -1.0, 1.0)

    def chronological_order(self) -> list[str]:
        """Node ids sorted by event time, ties broken by id.

        This is the temporal axis the chaining step walks forward along.  It is
        *not* the storage order: ``member_indices`` always refer to
        :attr:`node_ids`.
        """
        return sorted(
            self.node_ids,
            key=lambda node_id: (
                self.event_times[self.index_of[node_id]],
                node_id,
            ),
        )

    def provenance(self) -> dict[str, object]:
        return {
            "kind": "source_qdrant_node_vectors",
            "source_store": str(self.source_store),
            "collection": store_io.COLLECTION,
            "scope_id": self.scope_id,
            "ordered_node_ids_hash": sha256_json(list(self.node_ids)),
            "vector_shape": list(self.embeddings.shape),
        }


def load_scope(store_root: Path, sample: int) -> Scope:
    source_store = Path(store_root) / f"store_{sample}" / "locomo"
    with store_io.read_lock(source_store):
        points = store_io.sample_points(source_store, sample, with_vectors=True)
    if not points:
        raise RuntimeError(f"sample {sample}: no points in {source_store}")
    return Scope(sample=sample, source_store=source_store, points=tuple(points))
