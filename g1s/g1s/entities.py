"""Entity sets and their IDF weights.

Step 1 writes one grounding record per node: a list of entities and a list of
relations.  This module turns those records into the only form the method
consumes -- a set of entity keys per node, and a weight per entity key -- and
defines the two masses the chaining step scores pairs with.

Three filters are applied when a record becomes a set, all of them for the same
reason: an entity that appears in nearly every node carries no information
about *which* nodes belong together.

    speakers      the two conversation participants appear everywhere
    ``event::``   synthetic per-node keys, unique by construction
    (IDF)         everything else is down-weighted in proportion to frequency
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .jsonio import read_json
from .timeparse import parse_memory_time

EVENT_PREFIX = "event::"


def _key(value: Any) -> str:
    return str(value or "").strip().casefold()


def speakers_of(record: Mapping[str, Any]) -> set[str]:
    """The conversation participants, read off the ``source`` field.

    ``source`` is a user id like ``caroline_melanie_3``; the speaker name is
    everything before the sample suffix.
    """
    return {
        _key(str(row.get("source", "")).rsplit("_", 1)[0])
        for row in record.get("nodes", [])
        if str(row.get("source", "")).strip()
    }


def entity_set(node: Mapping[str, Any], speakers: set[str]) -> frozenset[str]:
    """Informative entity keys of one node."""
    from_entities = {
        _key(entity.get("key"))
        for entity in node.get("entities", [])
        if str(entity.get("key", "")).strip()
        and _key(entity.get("canonical")) not in speakers
        and not str(entity.get("key", "")).startswith(EVENT_PREFIX)
    }
    from_relations = {
        _key(relation.get(side))
        for relation in node.get("relations", [])
        for side in ("subject", "object")
        if str(relation.get(side, "")).strip() and _key(relation.get(side)) not in speakers
    }
    return frozenset(from_entities | from_relations)


@dataclass(frozen=True)
class Grounding:
    """Per-node entity sets for one sample, with IDF weights."""

    sample: int
    sets: dict[str, frozenset[str]]
    weight: dict[str, float]
    timestamps: dict[str, str]

    # ------------------------------------------------------------------ masses

    def mass(self, entities: frozenset[str]) -> float:
        # sorted() keeps the float summation order independent of set iteration
        # order, so the affinities -- and hence the plan hash -- are stable.
        return sum(self.weight.get(entity, 0.0) for entity in sorted(entities))

    def shared_mass(self, left: str, right: str) -> float:
        return self.mass(self.of(left) & self.of(right))

    def union_mass(self, left: str, right: str) -> float:
        return self.mass(self.of(left) | self.of(right))

    def of(self, node_id: str) -> frozenset[str]:
        return self.sets.get(node_id, frozenset())

    def coverage(self, node_ids: Sequence[str]) -> float:
        """Fraction of nodes that grounded to at least one entity."""
        if not node_ids:
            return 0.0
        return sum(1 for node_id in node_ids if self.of(node_id)) / len(node_ids)

    # ------------------------------------------------------------------- time

    def event_time(self, node_id: str, payload: Mapping[str, Any]) -> datetime:
        """Event time of a node, preferring the timestamp seen at grounding.

        The grounding record and the store payload agree in practice; the
        grounding copy wins so that the temporal order of the method is a
        function of the grounding artifact alone.
        """
        return parse_memory_time(
            {
                "timestamp": self.timestamps.get(node_id) or payload.get("timestamp") or "",
                "created_at": payload.get("created_at"),
            }
        )


def build_grounding(record: Mapping[str, Any], sample: int, universe: Sequence[str]) -> Grounding:
    """Turn a raw grounding record into weighted entity sets over ``universe``.

    IDF is computed over the nodes of ``universe`` only, so the weights do not
    depend on whether the grounding file happens to hold extra rows.
    """
    speakers = speakers_of(record)
    by_node = {
        str(node["node_id"]): entity_set(node, speakers) for node in record.get("nodes", [])
    }
    sets = {node_id: by_node.get(node_id, frozenset()) for node_id in universe}

    total = len(universe)
    document_frequency: dict[str, int] = {}
    for entities in sets.values():
        for entity in entities:
            document_frequency[entity] = document_frequency.get(entity, 0) + 1
    weight = {
        entity: math.log(total / count) for entity, count in document_frequency.items()
    }
    timestamps = {
        str(node["node_id"]): str(node.get("timestamp", "")) for node in record.get("nodes", [])
    }
    return Grounding(sample=sample, sets=sets, weight=weight, timestamps=timestamps)


def load_grounding(grounding_dir: Path, sample: int, universe: Sequence[str]) -> Grounding:
    path = Path(grounding_dir) / f"sample{sample}_grounding.json"
    if not path.is_file():
        raise FileNotFoundError(f"grounding record not found: {path}")
    return build_grounding(read_json(path), sample, universe)
