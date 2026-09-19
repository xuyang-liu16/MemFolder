"""LoCoMo adapter.

v0 reads the public fixture shipped under ``code/evaluation/adapters/fixtures/``.
The real LoCoMo dataset lives under ``repo/`` (gitignored); once available,
switch ``load_locomo_dialogs`` to point at it without changing downstream code.

Schema we expect per dialog (fixture-aligned to the LoCoMo JSON dict):
    {
      "dialog_id": "...",
      "turns": [
          {"turn_id": 0, "speaker": "Mark",
           "text": "...",
           "timestamp": "2024-...",   # ISO; we parse to float epoch
           "entities": ["Mark"],      # optional, may be empty
           "events": ["..."]},        # optional, may be empty
          ...
      ],
      "qa": [                         # test-set QA; NEVER used for probes
          {"question": "...", "answer": "...", "category": "..."}
      ]
    }
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from code.compression.schema import MemoryNode


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "locomo_fixture.jsonl"


def _to_epoch(ts: Any) -> float:
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            # Fall back to deterministic integer derived from string.
            return float(abs(hash(ts)) % 10**6)
    return 0.0


def turn_to_node(dialog_id: str, turn: Dict[str, Any]) -> MemoryNode:
    turn_id = turn.get("turn_id", 0)
    speaker = turn.get("speaker", "")
    text = turn.get("text", "") or ""
    return MemoryNode(
        node_id=f"{dialog_id}_turn_{turn_id:03d}",
        text=f"{speaker}: {text}".strip(": ") if speaker else text,
        timestamp=_to_epoch(turn.get("timestamp", turn_id)),
        embedding=None,
        entities=list(turn.get("entities", []) or []),
        events=list(turn.get("events", []) or []),
        modality="text",
        source={"dataset": "LoCoMo", "dialog_id": dialog_id, "turn_id": turn_id},
    )


def dialog_to_nodes(dialog: Dict[str, Any]) -> List[MemoryNode]:
    dialog_id = dialog.get("dialog_id", "unknown")
    return [turn_to_node(dialog_id, t) for t in dialog.get("turns", [])]


def iter_fixture_dialogs(path: Optional[Path] = None) -> Iterable[Dict[str, Any]]:
    p = path or FIXTURE_PATH
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def load_locomo_stream(
    *, path: Optional[Path] = None, dialog_ids: Optional[List[str]] = None
) -> List[MemoryNode]:
    """Load LoCoMo (or its fixture) into a flat list of MemoryNode."""
    nodes: List[MemoryNode] = []
    keep = set(dialog_ids) if dialog_ids else None
    for dialog in iter_fixture_dialogs(path):
        if keep is not None and dialog.get("dialog_id") not in keep:
            continue
        nodes.extend(dialog_to_nodes(dialog))
    return nodes


def collect_test_questions(
    *, path: Optional[Path] = None, dialog_ids: Optional[List[str]] = None
) -> List[str]:
    """Return LoCoMo test-set questions for leakage-check helpers.

    These strings must NEVER leak into probe queries; they are returned
    here so callers can pass them to ``assert_no_leakage``.
    """
    out: List[str] = []
    for dialog in iter_fixture_dialogs(path):
        if dialog_ids and dialog.get("dialog_id") not in set(dialog_ids):
            continue
        for q in dialog.get("qa", []) or []:
            qq = q.get("question", "")
            if qq:
                out.append(qq)
            aa = q.get("answer", "")
            if aa and len(aa) < 200:
                out.append(aa)
    return out


__all__ = [
    "FIXTURE_PATH",
    "turn_to_node",
    "dialog_to_nodes",
    "iter_fixture_dialogs",
    "load_locomo_stream",
    "collect_test_questions",
]
