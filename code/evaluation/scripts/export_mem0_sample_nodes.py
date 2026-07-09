"""Export Mem0/Qdrant memory points as RecallFlow MemoryNode JSONL.

This is a read-only bridge for P0 diagnostics. It does not read LoCoMo
questions, answers, gold labels, or evidence fields.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from qdrant_client import QdrantClient


def parse_time(value) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    text = re.sub(r"\b(am|pm)\b", lambda m: m.group(1).upper(), value.strip(), flags=re.I)
    for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    return 0.0


def iter_points(qdrant_dir: Path, collection: str):
    with tempfile.TemporaryDirectory(prefix="rf_mem0_export_") as tmp:
        tmp_qdrant = Path(tmp) / "qdrant"
        shutil.copytree(qdrant_dir, tmp_qdrant, ignore=shutil.ignore_patterns(".lock*"))
        client = QdrantClient(path=str(tmp_qdrant))
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=collection,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            for point in points:
                yield point
            if offset is None:
                break
        client.close()


def payload_user_id(payload: dict) -> str:
    return str(payload.get("user_id") or payload.get("metadata", {}).get("user_id") or "")


def memory_text(payload: dict) -> str:
    for key in ("data", "memory", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Export local Mem0 Qdrant points to MemoryNode JSONL.")
    parser.add_argument("--store-dir", required=True)
    parser.add_argument("--sample-idx", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--collection", default="mem0")
    args = parser.parse_args()

    store = Path(args.store_dir)
    qdrant_dir = store / "qdrant"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = f"_{args.sample_idx}"
    rows = []
    for point in iter_points(qdrant_dir, args.collection):
        payload = point.payload if isinstance(point.payload, dict) else {}
        user_id = payload_user_id(payload)
        text = memory_text(payload)
        vector = point.vector
        if isinstance(vector, dict):
            vector = next(iter(vector.values()))
        if not user_id.endswith(suffix) or not text or vector is None:
            continue
        timestamp_raw = payload.get("timestamp") or payload.get("metadata", {}).get("timestamp")
        row = {
            "node_id": f"locomo_{args.sample_idx}_memory_{len(rows):06d}",
            "text": text,
            "timestamp": parse_time(timestamp_raw),
            "embedding": list(vector),
            "entities": [],
            "events": [],
            "modality": "text",
            "source": {
                "dataset": "LoCoMo",
                "sample_id": f"locomo_{args.sample_idx}",
                "point_id": str(point.id),
                "user_id": user_id,
            },
            "raw_pointer": str(point.id),
        }
        rows.append(row)

    with output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(output), "num_nodes": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
