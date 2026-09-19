"""Step 1 — grounding: what is each memory *about*?

Embeddings tell you that two memories read alike.  They do not tell you that
both are about the same book, or the same person's kids.  Step 4 needs that
second kind of evidence, so this step asks an LLM to name, for every memory
node, the content-bearing entities it mentions.

Two details do most of the work:

*   **One call per session, not per node.**  Memories from one conversation
    session share context, and a model that sees them together resolves
    pronouns and shared referents consistently.
*   **A cross-session registry.**  Sessions are grounded in chronological
    order, and each call is shown the labels already used in earlier sessions
    with instructions to reuse a label for the same referent and to
    disambiguate a different one ("max (neighbor)" vs "max (coworker)").
    Without this the same person acquires a new label every session and the
    entity signal in step 4 collapses.

Labels are normalised in code, not by the model: lowercased, whitespace
collapsed, a leading "the" dropped, and the literal word "user" resolved to the
speaker.  Whatever the model's phrasing, the same string comes out.

Output is one JSON record per sample; :mod:`g1s.entities` is what reads it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..jsonio import write_json
from ..llm import ChatClient, Truncated
from ..scope import Scope
from ..timeparse import parse_memory_time

SCHEMA_VERSION = "grounding_v2r"

ENTITY_TYPES = sorted(
    [
        "person",
        "work",
        "place",
        "org",
        "group",
        "animal",
        "object",
        "activity",
        "topic",
        "event",
        "other",
    ]
)

_RULES = [
    """Extract ALL content-bearing entities mentioned or clearly implied by the
   node text: people (including authors/creators/public figures), named works
   (books, movies, songs, shows) together with their creators, places and
   locations, organizations / communities / groups, pets or named animals,
   significant objects / possessions, activities / hobbies / jobs /
   fields of work, topics or concepts someone could ask about later, and
   concrete events.""",
    """The bare word "User" refers to the source speaker; resolve it to the
   speaker's own name and do not emit "user" as an entity.""",
    """Do NOT stop at the protagonist. A node like "Loved 'X' by Y" must yield
   both the work X and the person Y. Aim for at least 2 entities per node
   whenever the text carries any concrete content; only pure greetings or
   chit-chat may have fewer.""",
    """`canonical` must be a short noun phrase in lowercase, without a leading
   "the", without verbs. Aliases of the same thing share one canonical label.""",
]

#: Only used when a registry is supplied -- it is the rule that makes labels
#: comparable across sessions.
_COREFERENCE_RULE = """Coreference discipline:
   a. If an entity is the SAME referent as a known/recurrent label above,
      reuse that label EXACTLY.
   b. If it merely shares words but is a DIFFERENT referent (e.g. a different
      person with the same first name, different kids, a different song),
      create a disambiguated label, e.g. "max (neighbor)" vs "max (coworker)".
   c. Generic referents must carry owner qualification when an owner is
      known: "melanie's kids", not bare "kids"; "caroline's garden", not
      "garden". Truly public/generic concepts (art, pottery, mental health)
      stay unqualified."""

_TAIL_RULES = [
    "Do not invent entities that are not in the text.",
    """`relations` are optional; keep them only when clean, with a noun-phrase
   subject and object (never a verb phrase or sentence).""",
    """Set `opens_channel=true` for any entity that could plausibly recur in
   later memories.""",
]

_SCHEMA = """Allowed entity types: {types}

Return exactly one JSON object:
{{
  "nodes": [
    {{
      "id": 0,
      "entities": [
        {{"canonical": "becoming nicole", "type": "work", "roles": ["liked"], "mentions": ["Becoming Nicole"], "opens_channel": true}},
        {{"canonical": "amy ellis nutt", "type": "person", "roles": ["author"], "mentions": ["Amy Ellis Nutt"], "opens_channel": true}}
      ],
      "relations": [{{"subject": "amy ellis nutt", "predicate": "wrote", "object": "becoming nicole"}}]
    }}
  ]
}}

Every input id must occur exactly once. Output JSON only, no commentary.

INPUT NODES:
{records}"""

_HEADER = """Role: exhaustive entity extraction for a memory compression graph.

You will ground every memory node of one conversation session. The extracted
entities decide which memories are allowed to merge, so recall of
content-bearing entities matters more than precision of wording.

Session metadata:
- sample_id: {sample_id}
- exact_timestamp: {timestamp}
{registry_line}"""


def build_prompt(
    *,
    sample: int,
    timestamp: str,
    records: Sequence[Mapping[str, Any]],
    registry: Sequence[str] | None,
) -> str:
    rules = [*_RULES, *( [_COREFERENCE_RULE] if registry is not None else [] ), *_TAIL_RULES]
    header = _HEADER.format(
        sample_id=sample,
        timestamp=timestamp,
        registry_line=(
            "- known/recurrent canonical labels from earlier sessions: "
            f"{json.dumps(sorted(registry), ensure_ascii=False)}"
            if registry is not None
            else ""
        ),
    )
    numbered = "\n".join(f"{number}. {rule}" for number, rule in enumerate(rules, start=1))
    schema = _SCHEMA.format(
        types=ENTITY_TYPES,
        records=json.dumps([dict(record) for record in records], ensure_ascii=False),
    )
    return f"{header}\n\nExtraction rules:\n{numbered}\n\n{schema}"



# ---------------------------------------------------------------- normalising


def normalise_label(value: str, speaker: str) -> str:
    label = re.sub(r"\s+", " ", str(value or "").strip().casefold())
    label = re.sub(r"^the\s+", "", label)
    return speaker if label in {"user", "user's", "speaker"} else label


def normalise_row(row: Mapping[str, Any], speaker: str) -> dict[str, Any]:
    entities = []
    for entity in row.get("entities") or []:
        key = normalise_label(entity.get("canonical", ""), speaker)
        if not key:
            continue
        entities.append(
            {
                "canonical": key,
                "key": key,
                "type": str(entity.get("type") or "other").casefold(),
                "roles": [str(value) for value in (entity.get("roles") or [])][:4],
                "mentions": [str(value) for value in (entity.get("mentions") or [])][:4],
                "opens_channel": bool(entity.get("opens_channel", True)),
            }
        )
    relations = []
    for relation in row.get("relations") or []:
        subject = normalise_label(relation.get("subject", ""), speaker)
        obj = normalise_label(relation.get("object", ""), speaker)
        predicate = re.sub(r"\s+", " ", str(relation.get("predicate") or "").strip().casefold())
        if subject and obj and subject != obj and len(predicate.split()) <= 4:
            relations.append({"subject": subject, "predicate": predicate, "object": obj})
    return {"entities": entities, "relations": relations}


# --------------------------------------------------------------------- the step


@dataclass
class _Node:
    node_id: str
    text: str
    timestamp: str
    source: str
    index: int

    @property
    def speaker(self) -> str:
        return self.source.rsplit("_", 1)[0].strip().casefold()


def _nodes_of(scope: Scope) -> list[_Node]:
    """Grounding order: by session time, so the registry grows chronologically."""
    rows = [
        _Node(
            node_id=point.node_id,
            text=point.text,
            timestamp=point.timestamp,
            source=point.user_id,
            index=0,
        )
        for point in scope.points
    ]
    rows.sort(key=lambda row: (row.timestamp, row.node_id))
    for position, row in enumerate(rows):
        row.index = position
    return rows


def _sessions(nodes: Sequence[_Node]) -> list[tuple[str, list[_Node]]]:
    grouped: dict[str, list[_Node]] = {}
    for node in nodes:
        grouped.setdefault(node.timestamp, []).append(node)
    return sorted(
        grouped.items(),
        key=lambda item: (parse_memory_time({"timestamp": item[0]}), item[0]),
    )


def ground(
    scope: Scope,
    chat: ChatClient,
    *,
    registry: bool = True,
    max_tokens: int = 4096,
    attempts: int = 4,
) -> dict[str, Any]:
    """Ground every node of a sample. Returns the grounding record."""
    nodes = _nodes_of(scope)
    results: dict[int, dict[str, Any]] = {}
    known: set[str] = set()

    def call(timestamp: str, rows: Sequence[_Node], depth: int = 0) -> dict[str, Any]:
        wanted = {row.index for row in rows}
        prompt = build_prompt(
            sample=scope.sample,
            timestamp=timestamp,
            records=[
                {"id": row.index, "source": row.speaker, "text": row.text} for row in rows
            ],
            registry=sorted(known) if registry else None,
        )

        def validate(payload: Mapping[str, Any]) -> None:
            got = payload.get("nodes")
            if not isinstance(got, list):
                raise ValueError("missing nodes list")
            if sorted(int(row.get("id")) for row in got) != sorted(wanted):
                raise ValueError(f"id coverage mismatch: got {len(got)} want {len(wanted)}")

        try:
            return chat.complete_json(
                prompt, validate=validate, attempts=attempts, max_tokens=max_tokens
            )
        except Truncated:
            # A long session does not fit in one answer; halve it and retry.
            if depth >= 2 or len(rows) <= 1:
                raise
            half = len(rows) // 2
            left = call(timestamp, rows[:half], depth + 1)
            right = call(timestamp, rows[half:], depth + 1)
            return {"nodes": [*left["nodes"], *right["nodes"]]}

    for timestamp, rows in _sessions(nodes):
        payload = call(timestamp, rows)
        by_id = {int(row["id"]): row for row in payload["nodes"]}
        for row in rows:
            normalised = normalise_row(by_id[row.index], row.speaker)
            known.update(entity["key"] for entity in normalised["entities"])
            results[row.index] = {
                "node_index": row.index,
                "node_id": row.node_id,
                "timestamp": row.timestamp,
                "source": row.source,
                **normalised,
            }

    return {
        "schema_version": SCHEMA_VERSION,
        "sample_id": scope.sample,
        "model": chat.endpoint.model,
        "cross_session_registry": registry,
        "node_count": len(nodes),
        "nodes": [results[index] for index in range(len(nodes))],
    }


def run(scope: Scope, chat: ChatClient, directory, **kwargs) -> dict[str, Any]:
    record = ground(scope, chat, **kwargs)
    write_json(directory / f"sample{scope.sample}_grounding.json", record, indent=None)
    return record
