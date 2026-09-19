"""Step 2 — synonyms: collapse labels that name the same thing.

Even with a registry, step 1 produces near-duplicate labels: "pottery class"
and "pottery classes", "mom" and "melanie's mom".  To the entity mass in step 4
those are different entities, so a genuinely shared referent contributes
nothing and the signal is quietly weakened.

The fix does not need another LLM call.  Embed the sample's label vocabulary,
join any two labels at cosine >= 0.85 with union-find, and take one
representative per component -- the shortest label, ties broken
lexicographically, so the representative is the plainest form.  Then rewrite
the grounding record with the merged keys.

The threshold is the only knob.  At 0.85 the merges are dull and safe
("pottery class" ~ "pottery classes"); pushing it lower starts to join things
that merely co-occur, which would manufacture entity overlap that isn't there.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..jsonio import write_json
from ..llm import EmbeddingCache, EmbeddingClient

THRESHOLD = 0.85
SCHEMA_VERSION = "grounding_v2rm"


def vocabulary(record: Mapping[str, Any]) -> list[str]:
    """Every entity key used anywhere in a grounding record, sorted."""
    labels: set[str] = set()
    for node in record.get("nodes", []):
        for entity in node.get("entities", []):
            if str(entity.get("key", "")).strip():
                labels.add(str(entity["key"]).strip())
        for relation in node.get("relations", []):
            for side in ("subject", "object"):
                if str(relation.get(side, "")).strip():
                    labels.add(str(relation[side]).strip())
    return sorted(labels)


def merge_map(labels: Sequence[str], vectors: np.ndarray, threshold: float = THRESHOLD) -> dict[str, str]:
    """label -> representative label, by union-find over the similarity graph."""
    count = len(labels)
    if count == 0:
        return {}
    parent = list(range(count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    similarity = vectors @ vectors.T
    np.fill_diagonal(similarity, 0.0)
    left, right = np.where(similarity >= threshold)
    for a, b in zip(left.tolist(), right.tolist()):
        root_a, root_b = find(a), find(b)
        if root_a == root_b:
            continue
        # The representative is the shortest label, then the lexicographic
        # first -- deterministic, and it prefers the plain form.
        if (len(labels[root_b]), labels[root_b]) < (len(labels[root_a]), labels[root_a]):
            parent[root_a] = root_b
        else:
            parent[root_b] = root_a
    return {labels[index]: labels[find(index)] for index in range(count)}


def apply_map(record: Mapping[str, Any], mapping: Mapping[str, str]) -> dict[str, Any]:
    """Rewrite a grounding record with merged keys, de-duplicating as it goes."""
    nodes = []
    for node in record.get("nodes", []):
        merged: dict[str, dict[str, Any]] = {}
        for entity in node.get("entities", []):
            original = str(entity.get("key", "")).strip()
            key = mapping.get(original, original)
            if not key:
                continue
            if key in merged:
                existing = merged[key]
                existing["roles"] = sorted(
                    set(existing.get("roles", [])) | set(entity.get("roles", []))
                )
                existing["mentions"] = sorted(
                    set(existing.get("mentions", [])) | set(entity.get("mentions", []))
                )[:4]
                continue
            merged[key] = {**dict(entity), "key": key, "canonical": key}

        relations = []
        for relation in node.get("relations", []):
            subject = str(relation.get("subject", "")).strip()
            obj = str(relation.get("object", "")).strip()
            subject, obj = mapping.get(subject, subject), mapping.get(obj, obj)
            # A relation whose two ends merged into one label says nothing.
            if subject and obj and subject != obj:
                relations.append({**dict(relation), "subject": subject, "object": obj})

        nodes.append({**dict(node), "entities": list(merged.values()), "relations": relations})

    return {**dict(record), "schema_version": SCHEMA_VERSION, "nodes": nodes}


def merge_synonyms(
    record: Mapping[str, Any],
    embedder: EmbeddingClient,
    *,
    threshold: float = THRESHOLD,
    cache: EmbeddingCache | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Returns the rewritten record and the label changes it applied."""
    labels = vocabulary(record)
    if not labels:
        return dict(record), {}
    vectors = embedder.embed(labels, cache).astype(np.float64)
    mapping = merge_map(labels, vectors, threshold)
    changed = {source: target for source, target in mapping.items() if source != target}
    return apply_map(record, mapping), changed


def run(
    record: Mapping[str, Any],
    embedder: EmbeddingClient,
    directory: Path,
    *,
    threshold: float = THRESHOLD,
    cache: EmbeddingCache | None = None,
) -> dict[str, Any]:
    sample = int(record["sample_id"])
    merged, changed = merge_synonyms(record, embedder, threshold=threshold, cache=cache)
    write_json(directory / f"sample{sample}_grounding.json", merged, indent=None)
    write_json(directory / f"sample{sample}_label_map.json", changed, indent=2)
    return merged
