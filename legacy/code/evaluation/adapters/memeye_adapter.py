"""MemEye adapter (fixture-based stub for v0).

v0 schema: one ``MemoryNode`` per image / video frame caption, plus optional
``raw_pointer`` linking back to the frame path on disk (under ``repo/``,
which is gitignored).

Real ``MemEye`` data is expected to live under ``repo/MemEye/...`` and will
be wired in once available. The function signatures below are kept stable so
the wiring is purely additive.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from code.compression.schema import MemoryNode


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "memeye_fixture.jsonl"


def clip_to_node(clip: Dict[str, Any]) -> MemoryNode:
    clip_id = clip.get("clip_id", "clip_unknown")
    return MemoryNode(
        node_id=f"memeye_{clip_id}",
        text=clip.get("caption", ""),
        timestamp=float(clip.get("frame_ts", 0.0)),
        embedding=None,
        entities=list(clip.get("entities", []) or []),
        events=list(clip.get("events", []) or []),
        modality="multimodal",
        source={
            "dataset": "MemEye",
            "clip_id": clip_id,
            "frame_id": clip.get("frame_id", 0),
        },
        raw_pointer=clip.get("frame_path"),
    )


def iter_fixture_clips(path: Optional[Path] = None) -> Iterable[Dict[str, Any]]:
    p = path or FIXTURE_PATH
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def load_memeye_stream(
    *, path: Optional[Path] = None, clip_ids: Optional[List[str]] = None
) -> List[MemoryNode]:
    keep = set(clip_ids) if clip_ids else None
    out: List[MemoryNode] = []
    for clip in iter_fixture_clips(path):
        if keep is not None and clip.get("clip_id") not in keep:
            continue
        out.append(clip_to_node(clip))
    return out


def collect_test_questions(
    *, path: Optional[Path] = None, clip_ids: Optional[List[str]] = None
) -> List[str]:
    out: List[str] = []
    keep = set(clip_ids) if clip_ids else None
    for clip in iter_fixture_clips(path):
        if keep is not None and clip.get("clip_id") not in keep:
            continue
        for q in clip.get("qa", []) or []:
            qq = q.get("question", "")
            if qq:
                out.append(qq)
            aa = q.get("answer", "")
            if aa and len(aa) < 200:
                out.append(aa)
    return out


__all__ = [
    "FIXTURE_PATH",
    "clip_to_node",
    "iter_fixture_clips",
    "load_memeye_stream",
    "collect_test_questions",
]
