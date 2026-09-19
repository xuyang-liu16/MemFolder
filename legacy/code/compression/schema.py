"""RecallFlow memory schema.

Reference: docs/recallflow_implementation_guide.md §2 (数据结构).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class MemoryNode:
    """A single memory unit before compression.

    Fields follow §2.1 of the implementation guide. `embedding` is optional
    so an external `embed_fn` can populate it lazily.
    """

    node_id: str
    text: str
    timestamp: float
    embedding: Optional[List[float]] = None
    entities: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    modality: str = "text"
    source: Dict[str, Any] = field(default_factory=dict)
    raw_pointer: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryNode":
        return cls(**data)


@dataclass
class ProbeQuery:
    """A calibration probe used at compression time.

    Fields follow §2.2 of the implementation guide. NEVER generated from
    test-set questions or gold answers (oracle leakage ban).
    """

    probe_id: str
    text: str
    probe_type: str  # entity / temporal / event / task / multimodal / preference
    source_node_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryCapsule:
    """A compressed grouping in RecallFlow.

    Fields follow §2.3 of the implementation guide. `summary` is filled by
    `simple_capsule_summary` in v0 (no LLM).
    """

    capsule_id: str
    representative_id: str
    member_node_ids: List[str] = field(default_factory=list)
    merge_node_ids: List[str] = field(default_factory=list)
    exception_node_ids: List[str] = field(default_factory=list)
    archive_node_ids: List[str] = field(default_factory=list)
    summary: str = ""
    timestamp_span: Optional[Tuple[float, float]] = None
    entities: List[str] = field(default_factory=list)
    raw_pointers: List[str] = field(default_factory=list)

    def retained_node_ids(self) -> List[str]:
        """Set of node_ids that survive compression inside this capsule."""
        kept = {self.representative_id}
        kept.update(self.exception_node_ids)
        return sorted(kept & set(self.member_node_ids) | {self.representative_id})

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d["timestamp_span"] is not None:
            d["timestamp_span"] = list(d["timestamp_span"])
        return d


def serialize_node(node: MemoryNode) -> str:
    return json.dumps(node.to_dict(), ensure_ascii=False, sort_keys=True)


def deserialize_node(line: str) -> MemoryNode:
    return MemoryNode.from_dict(json.loads(line))


__all__ = ["MemoryNode", "ProbeQuery", "MemoryCapsule",
           "serialize_node", "deserialize_node"]
