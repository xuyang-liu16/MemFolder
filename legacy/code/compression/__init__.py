"""RecallFlow: recall-preserving memory compression.

Reference: docs/recallflow_implementation_guide.md and
docs/recallflow_method.md.

Public surface:
    * ``schema`` — dataclasses for ``MemoryNode`` / ``ProbeQuery`` / ``MemoryCapsule``.
    * ``probes`` — rule-based probe generator with hard oracle-leakage guard.
    * ``response`` — response matrix and fingerprint helpers.
    * ``coreset`` — farthest-first k-center with mass tiebreak.
    * ``capsule`` — residual routing and capsule builder.
    * ``recallflow`` — main pipeline entry ``recallflow_compress`` /
      ``recallflow_prune_only`` / ``fit_compress``.
"""
from .capsule import (
    assign_to_representatives,
    build_capsules,
    capsules_retained_ids,
    route_cluster_members,
    simple_capsule_summary,
)
from .coreset import select_representatives
from .probes import (
    DEFAULT_PROBE_TYPES,
    assert_no_leakage,
    build_probe_queries,
    deduplicate_probes,
)
from .recallflow import (
    CompressedMemory,
    fit_compress,
    recallflow_compress,
    recallflow_compress_with_urb,
    recallflow_prune_only,
    recallflow_urb_prune_only,
)
from .response import compute_response_fingerprints, l2_normalize, softmax
from .schema import MemoryCapsule, MemoryNode, ProbeQuery
from .urb import (
    UNIVERSAL_RECALL_BASIS,
    UniversalRecallBasis,
    basis_hash,
    compute_family_centroids,
    default_urb,
    load_or_compute_centroids,
)

__all__ = [
    "MemoryNode",
    "ProbeQuery",
    "MemoryCapsule",
    "compute_response_fingerprints",
    "l2_normalize",
    "softmax",
    "select_representatives",
    "assign_to_representatives",
    "route_cluster_members",
    "build_capsules",
    "simple_capsule_summary",
    "capsules_retained_ids",
    "build_probe_queries",
    "deduplicate_probes",
    "assert_no_leakage",
    "recallflow_compress",
    "recallflow_prune_only",
    "recallflow_urb_prune_only",
    "recallflow_compress_with_urb",
    "fit_compress",
    "CompressedMemory",
    "DEFAULT_PROBE_TYPES",
    "UNIVERSAL_RECALL_BASIS",
    "UniversalRecallBasis",
    "default_urb",
    "basis_hash",
    "compute_family_centroids",
    "load_or_compute_centroids",
]
