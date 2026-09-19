"""The plan file: the single artifact every step reads and writes.

A plan says, for one sample, which memory nodes are grouped together and -- once
step 5 has run -- what each group was rewritten into.  Steps 3-5 are the only
producers; steps 6-7 are pure consumers.  Everything the method decides lives
here, so a plan file is a complete, inspectable record of one run.

    {
      "method": "g1s",              "sample_id": 3,
      "scope_id": "sample_003",     "keep_ratio": 0.5,
      "num_nodes_before": 646,      "num_units_after": 323,
      "groups": [
        {"anchor_node_id": "...",   "member_node_ids": ["...", "..."],
         "member_indices": [4, 17], "source_timestamps": ["...", "..."],
         "chains": [["...", "..."]],
         "final_text": "...",       "compression_time_start": "...",
                                    "compression_time_end": "..."},
        ...
      ],
      "metadata": {...},
      "plan_hash": "...",           "final_plan_hash": "..."
    }

``member_indices`` are positions in the sample's node order (see
:mod:`g1s.scope`); the anchor is always the first member.  ``plan_hash`` covers
the partition, ``final_plan_hash`` additionally covers the merged texts, so the
two together identify a run exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .jsonio import read_json, sha256_json, write_json
from .scope import Scope

SCHEMA_VERSION = 1

#: Fields written by step 5.  Re-running the partition steps must clear them:
#: a text merged from a different member set is not a valid product of the new
#: plan.
MERGE_PRODUCT_FIELDS = (
    "final_text",
    "compression_time_start",
    "compression_time_end",
    "merge_api_calls_realized",
    "route_rounds",
)


def target_count(total: int, keep_ratio: float) -> int:
    """How many groups a keep ratio asks for.

    ``keep_ratio=0.5`` over 646 nodes means 323 groups, i.e. the store shrinks
    to half its unit count.
    """
    if not 0.0 < keep_ratio <= 1.0:
        raise ValueError(f"keep_ratio must be in (0, 1], found {keep_ratio}")
    return max(1, min(total, int(round(keep_ratio * total))))


def keep_tag(keep_ratio: float) -> str:
    return f"keep{int(round(100.0 * keep_ratio))}"


@dataclass
class Group:
    """One anchor and the nodes folded into it."""

    anchor_node_id: str
    member_indices: list[int]
    member_node_ids: list[str]
    source_timestamps: list[str]
    chains: list[list[str]] = field(default_factory=list)
    final_text: str | None = None
    compression_time_start: str = ""
    compression_time_end: str = ""
    merge_api_calls_realized: int = 0

    @property
    def size(self) -> int:
        return len(self.member_node_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_node_id": self.anchor_node_id,
            "member_indices": list(self.member_indices),
            "member_node_ids": list(self.member_node_ids),
            "source_timestamps": list(self.source_timestamps),
            "chains": [list(chain) for chain in self.chains],
            "final_text": self.final_text,
            "compression_time_start": self.compression_time_start,
            "compression_time_end": self.compression_time_end,
            "merge_api_calls_realized": self.merge_api_calls_realized,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Group":
        return cls(
            anchor_node_id=str(raw["anchor_node_id"]),
            member_indices=[int(index) for index in raw["member_indices"]],
            member_node_ids=[str(node_id) for node_id in raw["member_node_ids"]],
            source_timestamps=[str(value) for value in raw.get("source_timestamps", [])],
            chains=[[str(node_id) for node_id in chain] for chain in raw.get("chains", [])],
            final_text=raw.get("final_text"),
            compression_time_start=str(raw.get("compression_time_start") or ""),
            compression_time_end=str(raw.get("compression_time_end") or ""),
            merge_api_calls_realized=int(raw.get("merge_api_calls_realized") or 0),
        )


def make_group(scope: Scope, anchor: str, members: Iterable[str]) -> Group:
    """Build a group, anchor first and the rest in node order."""
    rest = sorted(
        {node_id for node_id in members if node_id != anchor},
        key=lambda node_id: scope.index_of[node_id],
    )
    ordered = [anchor, *rest]
    indices = [scope.index_of[node_id] for node_id in ordered]
    return Group(
        anchor_node_id=anchor,
        member_indices=indices,
        member_node_ids=ordered,
        source_timestamps=[scope.timestamps[index] for index in indices],
    )


@dataclass
class Plan:
    method: str
    sample_id: int
    scope_id: str
    source_store: str
    keep_ratio: float
    generator_model: str
    num_nodes_before: int
    groups: list[Group]
    metadata: dict[str, Any] = field(default_factory=dict)
    config_id: str = ""
    schema_version: int = SCHEMA_VERSION

    # --------------------------------------------------------------- queries

    @property
    def num_units_after(self) -> int:
        return len(self.groups)

    @property
    def compression_ratio(self) -> float:
        return self.num_units_after / max(self.num_nodes_before, 1)

    @property
    def merged(self) -> bool:
        return all(group.final_text is not None for group in self.groups)

    def anchors(self) -> list[str]:
        return [group.anchor_node_id for group in self.groups]

    def partition(self) -> dict[str, str]:
        """node id -> anchor node id."""
        return {
            node_id: group.anchor_node_id
            for group in self.groups
            for node_id in group.member_node_ids
        }

    def api_calls(self) -> int:
        return sum(group.merge_api_calls_realized for group in self.groups)

    # ------------------------------------------------------------ invariants

    def check(self, total: int, keep_ratio: float | None = None) -> "Plan":
        """Assert that the groups form the partition the run promised.

        Three things must hold, and are worth stating because every step
        downstream silently depends on them: the group count is exactly the
        keep target, every node appears, and no node appears twice.
        """
        expected = target_count(total, keep_ratio if keep_ratio is not None else self.keep_ratio)
        if len(self.groups) != expected:
            raise AssertionError(f"expected {expected} groups, found {len(self.groups)}")
        indices = [index for group in self.groups for index in group.member_indices]
        if sorted(indices) != list(range(total)):
            raise AssertionError("groups must be a complete non-overlapping partition")
        for group in self.groups:
            if group.member_node_ids[0] != group.anchor_node_id:
                raise AssertionError(f"group {group.anchor_node_id}: anchor must come first")
        return self

    def check_same_universe(self, other: "Plan") -> "Plan":
        """Assert that a regrouping moved members without gaining or losing any."""
        mine = [node_id for group in self.groups for node_id in group.member_node_ids]
        theirs = [node_id for group in other.groups for node_id in group.member_node_ids]
        if len(mine) != len(theirs) or set(mine) != set(theirs):
            raise AssertionError("regrouping changed the node universe")
        if self.anchors() != other.anchors():
            raise AssertionError("regrouping changed the anchor set or its order")
        return self

    # ------------------------------------------------------------------- I/O

    def clear_merge_products(self) -> "Plan":
        for group in self.groups:
            group.final_text = None
            group.compression_time_start = ""
            group.compression_time_end = ""
            group.merge_api_calls_realized = 0
        return self

    def to_dict(self) -> dict[str, Any]:
        """Serialise, then stamp the two content hashes.

        ``plan_hash`` is taken over the plan without either hash present, and
        ``final_plan_hash`` over the plan with ``plan_hash`` in place -- the
        same order the original scripts used, so hashes stay comparable with
        previously generated artifacts.
        """
        body: dict[str, Any] = {
            "schema_version": self.schema_version,
            "dataset": "LoCoMo",
            "method": self.method,
            "operation": "native_memforest_prompt_merge",
            "sample_id": self.sample_id,
            "scope_id": self.scope_id,
            "source_store": self.source_store,
            "keep_ratio": self.keep_ratio,
            "config_id": self.config_id or self.method,
            "experiment_key": self.config_id or self.method,
            "generator_model": self.generator_model,
            "reader_model": self.generator_model,
            "num_nodes_before": self.num_nodes_before,
            "num_units_after": self.num_units_after,
            "merge_api_calls_realized": self.api_calls(),
            "groups": [group.to_dict() for group in self.groups],
            "metadata": dict(self.metadata),
        }
        body["plan_hash"] = sha256_json(body)
        body["final_plan_hash"] = sha256_json(body)
        return body

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Plan":
        return cls(
            method=str(raw["method"]),
            sample_id=int(raw["sample_id"]),
            scope_id=str(raw.get("scope_id") or f"sample_{int(raw['sample_id']):03d}"),
            source_store=str(raw.get("source_store") or ""),
            keep_ratio=float(raw.get("keep_ratio") or 0.5),
            generator_model=str(raw.get("generator_model") or ""),
            num_nodes_before=int(raw.get("num_nodes_before") or 0),
            groups=[Group.from_dict(group) for group in raw["groups"]],
            metadata=dict(raw.get("metadata") or {}),
            config_id=str(raw.get("config_id") or ""),
            schema_version=int(raw.get("schema_version") or SCHEMA_VERSION),
        )

    def write(self, path: Path) -> dict[str, Any]:
        body = self.to_dict()
        write_json(path, body)
        return body

    @classmethod
    def read(cls, path: Path) -> "Plan":
        return cls.from_dict(read_json(path))


def selection_plan_path(cell: Path, sample: int) -> Path:
    """``<cell>/selection_plans/sample_003.json`` -- the partition, unmerged."""
    return Path(cell) / "selection_plans" / f"sample_{sample:03d}.json"


def final_plan_path(cell: Path, sample: int) -> Path:
    """``<cell>/final_plans/sample_003.json`` -- the same plan, plus merged text."""
    return Path(cell) / "final_plans" / f"sample_{sample:03d}.json"


def group_size_stats(groups: Sequence[Group]) -> dict[str, float]:
    sizes = [group.size for group in groups]
    return {
        "mean": sum(sizes) / max(len(sizes), 1),
        "max": max(sizes, default=0),
        "singletons": sum(1 for size in sizes if size == 1),
    }
