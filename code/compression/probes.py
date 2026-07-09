"""Probe query generator for RecallFlow v0.

Reference: docs/recallflow_implementation_guide.md §3 (Probe queries).

Hard rules:
    * Probe text must NEVER come from test-set questions or gold answers.
    * Only entity / temporal / event / preference probes in v0.
    * Dedup uses text keys in v0; embedding-based dedup is a stub for later.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable, List, Optional

from .schema import MemoryNode, ProbeQuery


# Templates are constant strings so leakage is structurally impossible.
ENTITY_TEMPLATE = "关于 {entity} 我们知道什么？"
TEMPORAL_TEMPLATE = "这段时间发生了什么重要变化？"
EVENT_TEMPLATE = "{event} 是怎么发生的？"
PREFERENCE_TEMPLATE = "{entity} 的偏好或状态是什么？"

DEFAULT_PROBE_TYPES: tuple = ("entity", "temporal", "event")
_ALLOWED_TYPES = {"entity", "temporal", "event", "task", "preference", "multimodal"}


def _safe_text(s: str) -> str:
    """Strip whitespace and reject empty / whitespace-only strings."""
    s = (s or "").strip()
    if not s:
        raise ValueError("probe source text must be non-empty")
    return s


def _entity_probes(window_nodes: List[MemoryNode], w_idx: int) -> List[ProbeQuery]:
    counts: Counter = Counter()
    for node in window_nodes:
        for ent in node.entities:
            counts[ent] += 1
    top = sorted(counts, key=counts.get, reverse=True)[:3]
    out: List[ProbeQuery] = []
    for ent in top:
        safe_ent = _safe_text(ent)
        out.append(
            ProbeQuery(
                probe_id=f"w{w_idx}_entity_{safe_ent}",
                text=ENTITY_TEMPLATE.format(entity=safe_ent),
                probe_type="entity",
                source_node_ids=[n.node_id for n in window_nodes if safe_ent in n.entities],
                metadata={"entity": safe_ent, "window_id": w_idx},
            )
        )
    return out


def _temporal_probe(window_nodes: List[MemoryNode], w_idx: int) -> ProbeQuery:
    return ProbeQuery(
        probe_id=f"w{w_idx}_temporal",
        text=TEMPORAL_TEMPLATE,
        probe_type="temporal",
        source_node_ids=[n.node_id for n in window_nodes],
        metadata={"window_id": w_idx},
    )


def _event_probes(window_nodes: List[MemoryNode], w_idx: int) -> List[ProbeQuery]:
    events: List[str] = []
    for node in window_nodes:
        events.extend(node.events[:2])
    out: List[ProbeQuery] = []
    for e_idx, ev in enumerate(events[:3]):
        safe_ev = _safe_text(ev)
        out.append(
            ProbeQuery(
                probe_id=f"w{w_idx}_event_{e_idx}",
                text=EVENT_TEMPLATE.format(event=safe_ev),
                probe_type="event",
                source_node_ids=[n.node_id for n in window_nodes],
                metadata={"event": safe_ev, "window_id": w_idx},
            )
        )
    return out


def _preference_probe(window_nodes: List[MemoryNode], w_idx: int) -> Optional[ProbeQuery]:
    """Optional preference probe; emits only if at least one entity appears."""
    counts: Counter = Counter()
    for node in window_nodes:
        for ent in node.entities:
            counts[ent] += 1
    if not counts:
        return None
    ent, _ = counts.most_common(1)[0]
    safe_ent = _safe_text(ent)
    return ProbeQuery(
        probe_id=f"w{w_idx}_pref_{safe_ent}",
        text=PREFERENCE_TEMPLATE.format(entity=safe_ent),
        probe_type="preference",
        source_node_ids=[n.node_id for n in window_nodes if safe_ent in n.entities],
        metadata={"entity": safe_ent, "window_id": w_idx},
    )


def build_probe_queries(
    nodes: Iterable[MemoryNode],
    *,
    window_size: int = 8,
    max_probes: int = 64,
    probe_types: Iterable[str] = DEFAULT_PROBE_TYPES,
) -> List[ProbeQuery]:
    """Rule-based probe generator. See §3.3 of the implementation guide.

    For each window:
        * one temporal probe (mandatory if "temporal" in probe_types);
        * up-to-three entity probes (top entities by window-internal count);
        * up-to-three event probes (first slice of window events);
        * optional preference probe (top-1 entity).
    """
    types = tuple(probe_types)
    unknown = [t for t in types if t not in _ALLOWED_TYPES]
    if unknown:
        raise ValueError(f"unknown probe types: {unknown}")

    nodes_list = list(nodes)
    if not nodes_list:
        return []

    ws = max(1, int(window_size))
    windows = [nodes_list[i:i + ws] for i in range(0, len(nodes_list), ws)]
    out: List[ProbeQuery] = []

    for w_idx, window in enumerate(windows):
        if "temporal" in types:
            out.append(_temporal_probe(window, w_idx))
        if "entity" in types:
            out.extend(_entity_probes(window, w_idx))
        if "event" in types:
            out.extend(_event_probes(window, w_idx))
        if "preference" in types:
            p = _preference_probe(window, w_idx)
            if p is not None:
                out.append(p)

    deduped = deduplicate_probes(out)
    return deduped[:max(int(max_probes), 0)]


def deduplicate_probes(
    probes: List[ProbeQuery],
    embed_fn=None,
    threshold: float = 0.9,
) -> List[ProbeQuery]:
    """Deduplicate probes. v0 uses text key; embedding-based dedup is stubbed.

    Reference: §3.4 of the implementation guide.
    """
    if embed_fn is not None:
        # Embedding-based dedup is intentionally not implemented in v0;
        # keep the interface for later.
        raise NotImplementedError(
            "embedding-based probe dedup is a v0.2 extension; pass embed_fn=None"
        )

    seen: set = set()
    out: List[ProbeQuery] = []
    for p in probes:
        key = p.text.strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def assert_no_leakage(probes: List[ProbeQuery], forbidden_strings: Iterable[str]) -> None:
    """Hard guardrail: raise if any probe text matches a forbidden string.

    The oracle-leakage ban (docs/recallflow_method.md §3.2, §"当前不能 claim")
    requires that probe text is never constructed from test-set questions
    or gold answers. Forbidden strings should be supplied by the caller from
    the evaluation set (e.g. LoCoMo QA questions).
    """
    forb = {f.strip() for f in forbidden_strings if f and f.strip()}
    if not forb:
        return
    lowered = {f.lower() for f in forb}
    for p in probes:
        if p.text.strip().lower() in lowered:
            raise AssertionError(
                f"oracle leakage: probe {p.probe_id} text matches forbidden string"
            )


__all__ = [
    "build_probe_queries",
    "deduplicate_probes",
    "assert_no_leakage",
    "DEFAULT_PROBE_TYPES",
]
