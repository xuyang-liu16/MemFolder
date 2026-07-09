"""Universal Recall Basis for RecallFlow-URB P0.

Reference: docs/recallflow_urb_experiment_protocol.md §4, §5, §9.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Sequence, Tuple

import numpy as np

from .response import l2_normalize


UNIVERSAL_RECALL_BASIS: Dict[str, List[str]] = {
    "profile_identity": [
        "What stable personal facts should be remembered?",
        "What background information is important?",
        "What identity or profile details are mentioned?",
        "What long-term attributes describe a person or user?",
    ],
    "preference_habit": [
        "What preferences are mentioned?",
        "What does the user like or dislike?",
        "Which tastes, habits, or choices should be remembered?",
        "What personal preferences may matter in the future?",
    ],
    "goal_plan": [
        "What goals or intentions are mentioned?",
        "What future plans should be remembered?",
        "What does someone want or plan to do?",
        "Which intended actions may be useful later?",
    ],
    "event_action": [
        "What important events happened?",
        "What actions or decisions were made?",
        "What happened that may need to be recalled later?",
        "Which completed activities are worth remembering?",
    ],
    "temporal_change": [
        "What changed over time?",
        "What happened earlier versus later?",
        "Which updates or changes should be remembered?",
        "What temporal sequence or transition is important?",
    ],
    "relationship_role": [
        "What relationships between people are important?",
        "What roles, affiliations, or organizations are mentioned?",
        "Who is connected to whom and how?",
        "What social or professional relationship should be remembered?",
    ],
    "location_object": [
        "What places or locations are mentioned?",
        "What objects, possessions, or physical details matter?",
        "Which environment or setting information should be remembered?",
        "What location or object detail may be useful later?",
    ],
    "commitment_task": [
        "What commitments or promises were made?",
        "What tasks or obligations should be remembered?",
        "What needs to be done later?",
        "Which responsibilities or follow-ups are mentioned?",
    ],
    "constraint_need": [
        "What constraints or requirements are mentioned?",
        "What needs, limitations, or conditions matter?",
        "What restrictions should be remembered for future decisions?",
        "Which practical requirements may affect future actions?",
    ],
    "specific_exception": [
        "What unusual or specific detail may be important later?",
        "What rare fact should not be lost?",
        "Which precise detail could be needed for future recall?",
        "What exception or special case is worth preserving?",
    ],
}


EmbedFn = Callable[[str], Sequence[float]]


@dataclass(frozen=True)
class UniversalRecallBasis:
    """Versioned fixed URB bank."""

    version: str
    families: Mapping[str, Sequence[str]]

    @property
    def family_names(self) -> List[str]:
        return list(self.families.keys())

    @property
    def num_families(self) -> int:
        return len(self.families)

    @property
    def num_paraphrases(self) -> int:
        return sum(len(v) for v in self.families.values())

    def to_ordered_payload(self) -> Dict[str, object]:
        return {"version": self.version, "families": {k: list(v) for k, v in self.families.items()}}


def default_urb(version: str = "urb_v0") -> UniversalRecallBasis:
    """Return the fixed URB v0 bank."""
    if version != "urb_v0":
        raise ValueError(f"unknown URB version: {version}")
    return UniversalRecallBasis(version=version, families=UNIVERSAL_RECALL_BASIS)


def basis_hash(basis: UniversalRecallBasis) -> str:
    """Hash exact ordered URB text bank for cache invalidation."""
    payload = json.dumps(basis.to_ordered_payload(), ensure_ascii=False, sort_keys=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_family_centroids(
    basis: UniversalRecallBasis,
    embed_fn: EmbedFn,
    *,
    embedding_dim: int,
) -> np.ndarray:
    """Compute normalized family centroids per protocol §5."""
    rows = []
    for paraphrases in basis.families.values():
        embs = np.asarray([list(embed_fn(text)) for text in paraphrases], dtype=np.float64)
        if embs.shape != (len(paraphrases), embedding_dim):
            raise ValueError(f"URB embedding shape {embs.shape} != ({len(paraphrases)}, {embedding_dim})")
        embs = l2_normalize(embs, axis=1)
        rows.append(l2_normalize(embs.mean(axis=0, keepdims=True), axis=1)[0])
    return np.asarray(rows, dtype=np.float64)


def load_or_compute_centroids(
    basis: UniversalRecallBasis,
    embed_fn: EmbedFn,
    *,
    embedding_model: str,
    embedding_dim: int,
    cache_dir: str | Path = "external/cache/urb",
) -> Tuple[np.ndarray, Dict[str, object]]:
    """Load cached URB centroids or compute and cache them."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    stem = f"{basis.version}_{embedding_model}_{embedding_dim}"
    npy_path = cache / f"{stem}.npy"
    meta_path = cache / f"{stem}.meta.json"
    expected_hash = basis_hash(basis)

    if npy_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        arr = np.load(npy_path)
        if meta.get("basis_hash") == expected_hash and list(arr.shape) == [basis.num_families, embedding_dim]:
            return arr, meta

    arr = compute_family_centroids(basis, embed_fn, embedding_dim=embedding_dim)
    meta = {
        "basis_version": basis.version,
        "basis_hash": expected_hash,
        "family_names": basis.family_names,
        "num_families": basis.num_families,
        "num_paraphrases": basis.num_paraphrases,
        "embedding_model": embedding_model,
        "embedding_dim": embedding_dim,
        "centroid_shape": list(arr.shape),
    }
    np.save(npy_path, arr)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return arr, meta


__all__ = [
    "UNIVERSAL_RECALL_BASIS",
    "UniversalRecallBasis",
    "default_urb",
    "basis_hash",
    "compute_family_centroids",
    "load_or_compute_centroids",
]
