"""Timestamp parsing for LoCoMo memory payloads.

Mirrors ``MemForest.parse_memory_time`` from the vendored Mem0 evaluation code.
It is reproduced here (rather than imported) so that steps 1-5 of the method
have no dependency on the vendor tree at all: the vendored code is only needed
by the evaluation harness in steps 6-7.

Two payload fields are consulted, in this order:

    ``timestamp``   e.g. ``"7:39 pm on 8 May, 2023"``  (the LoCoMo session clock)
    ``created_at``  an ISO-8601 string                 (the store's write time)

Anything unparseable sorts first, as ``datetime.min`` in UTC.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Mapping

_MERIDIEM = re.compile(r"\b(am|pm)\b", re.IGNORECASE)
_FORMATS = ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y")

EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def parse_memory_time(payload: Mapping[str, object]) -> datetime:
    raw = payload.get("timestamp")
    if isinstance(raw, str) and raw.strip():
        text = _MERIDIEM.sub(lambda m: m.group(1).upper(), raw.strip())
        for fmt in _FORMATS:
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    created = payload.get("created_at")
    if isinstance(created, str):
        try:
            parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            return EPOCH
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return EPOCH
