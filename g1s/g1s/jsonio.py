"""JSON / JSONL helpers with the hashing policy the plan files depend on."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def sha256_json(value: Any) -> str:
    """Canonical content hash of a JSON-serialisable value.

    Key order is normalised and separators are tight, so the hash depends on
    the *content* of a plan and not on how it happens to be pretty-printed.
    Byte-identical to the original ``base.sha256_json``, which is what makes
    previously generated ``plan_hash`` values comparable.
    """
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, value: Any, *, indent: int | None = 1) -> None:
    """Write JSON atomically: a crash mid-write never leaves a half file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_jsonl(path: Path, rows: Mapping[str, Any] | Iterable[Mapping[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(rows, Mapping):
        rows = [rows]
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")


def model_tag(model: str) -> str:
    """Filesystem-safe form of a model name (``gpt-4o-mini`` -> ``gpt-4o-mini``)."""
    return "".join(c if c.isalnum() else "-" for c in model.lower()).strip("-")
