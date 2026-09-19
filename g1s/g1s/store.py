"""Qdrant store access.

The LoCoMo memory library is a local (on-disk) qdrant collection named ``mem0``.
A single store file can only be opened by one process at a time, so every read
goes through :func:`read_lock`.

This module is the only place that knows the storage layout.  It deliberately
does not import the vendored MemForest module: the four things the pipeline
needs from it (a node record, a dense-vector decoder, an upsert and a delete)
are 40 lines and are reproduced here with identical semantics.
"""
from __future__ import annotations

import contextlib
import fcntl
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

import numpy as np

from .timeparse import parse_memory_time

COLLECTION = "mem0"


@dataclass
class Point:
    """One memory node as stored in qdrant."""

    node_id: str
    payload: dict[str, Any]
    vector: np.ndarray | None
    vector_name: str | None

    @property
    def text(self) -> str:
        return str(self.payload.get("data") or "")

    @property
    def timestamp(self) -> str:
        return str(self.payload.get("timestamp") or self.payload.get("created_at") or "")

    @property
    def user_id(self) -> str:
        return str(self.payload.get("user_id") or "")

    @property
    def event_time(self) -> datetime:
        return parse_memory_time(self.payload)


# --------------------------------------------------------------------- locking


@contextlib.contextmanager
def read_lock(store: Path) -> Iterator[None]:
    """Serialise local-qdrant opens of one store across processes and threads.

    A local qdrant store admits exactly one client at a time; two workers on
    the same sample would otherwise fail on a storage lock.  The lock name
    carries the parent directory too, because every store is called ``locomo``
    and only ``store_3/locomo`` identifies one.
    """
    store = Path(store)
    name = f"{store.parent.name}-{store.name}"
    lock_path = Path(tempfile.gettempdir()) / f"g1s-{name}.qdrant.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _qdrant_path(store: Path) -> Path:
    inner = store / "qdrant"
    return inner if inner.is_dir() else store


@contextlib.contextmanager
def open_store(store: Path):
    from qdrant_client import QdrantClient

    client = QdrantClient(path=str(_qdrant_path(store)))
    try:
        yield client
    finally:
        if hasattr(client, "close"):
            client.close()


# ---------------------------------------------------------------------- reading


def to_dense_vector(raw: object) -> tuple[np.ndarray | None, str | None]:
    """Decode qdrant's vector field, which may be unnamed or a named mapping."""
    if isinstance(raw, list):
        return np.asarray(raw, dtype=np.float64), None
    if isinstance(raw, dict) and raw:
        name = next(iter(raw))
        value = raw[name]
        if isinstance(value, list):
            return np.asarray(value, dtype=np.float64), str(name)
    return None, None


def scroll(store: Path, *, with_vectors: bool = True, batch: int = 512) -> list[Point]:
    """Read every point of a store, in qdrant's own scroll order.

    That order is the canonical node order of a sample: plan ``member_indices``
    are positions in it.
    """
    points: list[Point] = []
    with open_store(store) as client:
        offset = None
        while True:
            chunk, offset = client.scroll(
                collection_name=COLLECTION,
                limit=batch,
                offset=offset,
                with_payload=True,
                with_vectors=with_vectors,
            )
            for raw in chunk:
                payload = dict(raw.payload or {})
                vector, vector_name = (
                    to_dense_vector(raw.vector) if with_vectors else (None, None)
                )
                points.append(Point(str(raw.id), payload, vector, vector_name))
            if offset is None:
                break
    return points


def sample_points(store: Path, sample: int, *, with_vectors: bool = True) -> list[Point]:
    """Points belonging to one LoCoMo sample, with the empty-text ones dropped.

    Both filters match the original ``load_sample_nodes``: a sample owns every
    point whose ``user_id`` ends in ``_<sample>``, and a node with no text
    cannot take part in compression.
    """
    suffix = f"_{sample}"
    return [
        point
        for point in scroll(store, with_vectors=with_vectors)
        if point.user_id.endswith(suffix)
        and point.text.strip()
        and (point.vector is not None or not with_vectors)
    ]


# ---------------------------------------------------------------------- writing


def exists(store: Path) -> bool:
    """True when ``store`` holds a real collection (not a half-finished copy)."""
    return (_qdrant_path(Path(store)) / "collection").is_dir()


def copy_store(source: Path, target: Path) -> None:
    """Copy a store, atomically from the reader's point of view."""
    if exists(target):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".copying")
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(source, staging, symlinks=True)
    staging.rename(target)


def upsert(client, points: Sequence[Point], batch: int = 256) -> None:
    from qdrant_client.http import models

    for start in range(0, len(points), batch):
        chunk = points[start : start + batch]
        structs = []
        for point in chunk:
            vector = point.vector.tolist()
            structs.append(
                models.PointStruct(
                    id=point.node_id,
                    vector={point.vector_name: vector} if point.vector_name else vector,
                    payload=point.payload,
                )
            )
        client.upsert(collection_name=COLLECTION, points=structs)


def delete(client, node_ids: Sequence[str], batch: int = 256) -> None:
    from qdrant_client.http import models

    ids = list(node_ids)
    for start in range(0, len(ids), batch):
        client.delete(
            collection_name=COLLECTION,
            points_selector=models.PointIdsList(points=ids[start : start + batch]),
        )


def compact_sqlite(store: Path) -> None:
    """Checkpoint and VACUUM the store so the on-disk size reflects the deletes."""
    database = _qdrant_path(store) / "collection" / COLLECTION / "storage.sqlite"
    if not database.exists():
        return
    connection = sqlite3.connect(str(database), timeout=120)
    try:
        connection.execute("PRAGMA busy_timeout=120000")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
        connection.commit()
    finally:
        connection.close()
