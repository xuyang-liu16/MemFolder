"""Step 6 — materialize: turn the plan into a real, smaller vector store.

Up to here everything has been JSON.  This step produces the artifact the
evaluation actually queries: a copy of the original qdrant store in which each
group has collapsed onto its anchor point.

    - the anchor point keeps its id and its payload, but its ``data`` becomes
      the merged text and its vector is re-embedded from that text
    - every non-anchor point is deleted
    - provenance (which nodes went in, over which time span) is written into
      the payload, so a retrieved memory can always be traced back

The anchor id is reused deliberately: keeping the id stable means the retrieval
code, the scorer and every existing analysis script can treat the compressed
store as an ordinary store.  Nothing downstream needs to know a compression
happened.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .. import store as store_io
from ..jsonio import write_json
from ..llm import EmbeddingCache, EmbeddingClient
from ..plan import Plan
from ..scope import Scope


def materialize(
    plan: Plan,
    scope: Scope,
    embedder: EmbeddingClient,
    target: Path,
    *,
    embedding_cache: Path | None = None,
) -> dict[str, Any]:
    """Build the compressed store at ``target``. Returns the manifest."""
    if not plan.merged:
        raise RuntimeError(f"sample {plan.sample_id}: plan has groups without merged text")
    anchors = plan.anchors()
    if len(anchors) != len(set(anchors)):
        raise RuntimeError(f"sample {plan.sample_id}: duplicate anchors")

    source = Path(plan.source_store)
    with store_io.read_lock(source):
        store_io.copy_store(source, target)

    texts = [str(group.final_text) for group in plan.groups]
    vectors = embedder.embed(texts, EmbeddingCache(embedding_cache))

    by_id = scope.by_id
    updates: list[store_io.Point] = []
    for group, text, vector in zip(plan.groups, texts, vectors, strict=True):
        anchor = by_id[group.anchor_node_id]
        payload = copy.deepcopy(dict(anchor.payload))
        payload["data"] = text
        payload["compression_config"] = plan.config_id or plan.method
        payload["compression_operation"] = plan.method
        payload["compressed_source_node_ids"] = list(group.member_node_ids)
        payload["compressed_source_timestamps"] = list(group.source_timestamps)
        payload["compression_group_size"] = group.size
        payload["compression_time_start"] = group.compression_time_start
        payload["compression_time_end"] = group.compression_time_end
        updates.append(
            store_io.Point(
                node_id=anchor.node_id,
                payload=payload,
                vector=vector,
                vector_name=anchor.vector_name,
            )
        )

    kept = set(anchors)
    # Delete by what the store actually holds, not by what the plan knows:
    # a point the plan never saw (empty text, say) must still go away.
    with store_io.read_lock(target):
        existing = [point.node_id for point in store_io.scroll(target, with_vectors=False)]
        with store_io.open_store(target) as client:
            store_io.delete(client, [node_id for node_id in existing if node_id not in kept])
            store_io.upsert(client, updates)
        store_io.compact_sqlite(target)

    manifest = {
        "dataset": "LoCoMo",
        "method": plan.method,
        "sample_id": plan.sample_id,
        "config_id": plan.config_id or plan.method,
        "store": str(target),
        "source_store": str(source),
        "num_nodes_before": plan.num_nodes_before,
        "num_units_after": len(updates),
        "compression_ratio": plan.compression_ratio,
        "embedding_model": embedder.endpoint.model,
    }
    return manifest


def run(
    plan: Plan,
    scope: Scope,
    embedder: EmbeddingClient,
    target: Path,
    manifest_path: Path,
    *,
    embedding_cache: Path | None = None,
) -> dict[str, Any]:
    if manifest_path.exists() and store_io.exists(target):
        from ..jsonio import read_json

        return read_json(manifest_path)
    manifest = materialize(plan, scope, embedder, target, embedding_cache=embedding_cache)
    write_json(manifest_path, manifest)
    return manifest
