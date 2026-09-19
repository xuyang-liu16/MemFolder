"""OpenAI-compatible clients, with the caches that make a run resumable.

Two caches, for two different jobs:

``PromptCache``    one JSONL file per sample, keyed by ``sha256(prompt)``.
                   A merge that already happened is never paid for twice, and
                   an interrupted run resumes exactly where it stopped.  The key
                   is the prompt itself, so changing the prompt (or the group it
                   describes) correctly misses the cache.

``EmbeddingCache`` one pickle per sample, keyed by text.  Step 6 needs a vector
                   for every merged text; re-materialising an unchanged plan
                   then costs nothing.

Both are append-only and safe to share between threads within a process.
"""
from __future__ import annotations

import json
import pickle
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from .jsonio import append_jsonl, read_jsonl, sha256_text
from .settings import Endpoint

EMBEDDING_BATCH = 64

#: Retry hint appended to a prompt whose answer came back unusable.
RETRY_SUFFIX = (
    "\n\nRETRY REQUIREMENT: one complete JSON object, every input id exactly "
    "once, no Markdown, no commentary."
)


class Truncated(RuntimeError):
    """The model hit its token limit; the caller should split the request."""


def extract_json(raw: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating a model that wrapped it in prose."""
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        value, _ = json.JSONDecoder().raw_decode(match.group(0))
        return value



def _retry(call: Callable[[], Any], *, attempts: int, base_seconds: float, what: str) -> Any:
    """Run ``call``, retrying transient provider failures with backoff.

    The relay endpoints used for these experiments fail in bursts, so the sleep
    grows exponentially (capped) with jitter to avoid a thundering herd of
    workers retrying in lockstep.
    """
    last: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - provider errors are not a fixed type
            last = exc
            if attempt + 1 >= max(1, attempts):
                break
            time.sleep(min(120.0, base_seconds * (2 ** min(attempt, 6))) + random.random())
    raise RuntimeError(f"{what} failed after {attempts} attempts: {last}") from last


# ------------------------------------------------------------------ chat side


class PromptCache:
    """Append-only prompt -> completion cache, one JSONL file per sample."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._memory: dict[int, dict[str, str]] = {}

    def path(self, sample: int) -> Path:
        return self.directory / f"sample_{sample:03d}.jsonl"

    def _loaded(self, sample: int) -> dict[str, str]:
        if sample not in self._memory:
            self._memory[sample] = {
                str(row["cache_key"]): str(row["text"])
                for row in read_jsonl(self.path(sample))
                if row.get("cache_key") and row.get("text")
            }
        return self._memory[sample]

    def get(self, sample: int, prompt: str) -> str | None:
        with self._lock:
            return self._loaded(sample).get(sha256_text(prompt))

    def put(self, sample: int, prompt: str, text: str) -> None:
        key = sha256_text(prompt)
        with self._lock:
            self._loaded(sample)[key] = text
            append_jsonl(self.path(sample), {"cache_key": key, "text": text})


@dataclass
class ChatClient:
    """A chat completion endpoint. Deterministic by construction: temperature 0."""

    endpoint: Endpoint
    cache: PromptCache | None = None
    timeout: float = 240.0
    max_tokens: int = 2048
    attempts: int = 12
    retry_base_seconds: float = 3.0

    def __post_init__(self) -> None:
        from openai import OpenAI

        self.endpoint.require("chat")
        self._client = OpenAI(
            api_key=self.endpoint.api_key,
            base_url=self.endpoint.base_url or None,
            timeout=self.timeout,
            max_retries=0,
        )
        self.calls = 0
        self._counter_lock = threading.Lock()

    def complete(self, prompt: str, *, sample: int = 0) -> str:
        if self.cache is not None:
            hit = self.cache.get(sample, prompt)
            if hit is not None:
                return hit

        def call() -> str:
            response = self._client.chat.completions.create(
                model=self.endpoint.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=self.max_tokens,
            )
            text = (response.choices[0].message.content or "").strip()
            if not text:
                raise RuntimeError("empty completion")
            return text

        text = _retry(
            call,
            attempts=self.attempts,
            base_seconds=self.retry_base_seconds,
            what=f"chat completion (sample {sample})",
        )
        with self._counter_lock:
            self.calls += 1
        if self.cache is not None:
            self.cache.put(sample, prompt, text)
        return text

    def complete_json(
        self,
        prompt: str,
        *,
        validate: Callable[[dict[str, Any]], None] | None = None,
        attempts: int = 4,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Ask for a JSON object and keep asking until it is usable.

        Not cached: a cached malformed answer would be returned forever, and
        the step that uses this (grounding) resumes at file granularity anyway.
        Raises :class:`Truncated` when the model ran out of tokens, which the
        caller answers by splitting the request rather than by retrying.
        """
        last: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            text = prompt if attempt == 1 else prompt + RETRY_SUFFIX
            try:
                response = self._client.chat.completions.create(
                    model=self.endpoint.model,
                    messages=[{"role": "user", "content": text}],
                    temperature=0.0,
                    max_tokens=max_tokens or self.max_tokens,
                    response_format={"type": "json_object"},
                )
                choice = response.choices[0]
                if str(choice.finish_reason or "") == "length":
                    raise Truncated("response hit max_tokens")
                value = extract_json(choice.message.content or "")
                if validate is not None:
                    validate(value)
                with self._counter_lock:
                    self.calls += 1
                return value
            except Truncated:
                raise
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt >= max(1, attempts):
                    break
                time.sleep(min(30.0, 2.0 * attempt) + random.random())
        raise RuntimeError(f"structured completion failed after {attempts} attempts: {last}")


# ------------------------------------------------------------- embedding side


class EmbeddingCache:
    """Text -> vector cache, persisted as a pickle so step 6 can resume."""

    def __init__(self, path: Path | None):
        self.path = Path(path) if path else None
        self.entries: dict[str, list[float]] = {}
        if self.path and self.path.exists():
            with self.path.open("rb") as handle:
                loaded = pickle.load(handle)
            if isinstance(loaded, dict):
                self.entries = {str(key): list(value) for key, value in loaded.items()}

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        with temporary.open("wb") as handle:
            pickle.dump(self.entries, handle, protocol=pickle.HIGHEST_PROTOCOL)
        temporary.replace(self.path)


@dataclass
class EmbeddingClient:
    endpoint: Endpoint
    dimensions: int | None = None
    timeout: float = 120.0
    attempts: int = 8
    retry_base_seconds: float = 5.0
    batch: int = EMBEDDING_BATCH

    def __post_init__(self) -> None:
        from openai import OpenAI

        self.endpoint.require("embedding")
        self._client = OpenAI(
            api_key=self.endpoint.api_key,
            base_url=self.endpoint.base_url or None,
            timeout=self.timeout,
            max_retries=0,
        )

    def embed(self, texts: Sequence[str], cache: EmbeddingCache | None = None) -> np.ndarray:
        """Return one row-normalised vector per text, embedding only cache misses."""
        cache = cache if cache is not None else EmbeddingCache(None)
        unique = list(dict.fromkeys(str(text) for text in texts))
        missing = [text for text in unique if text not in cache.entries]
        for start in range(0, len(missing), self.batch):
            chunk = missing[start : start + self.batch]

            def call(chunk: list[str] = chunk) -> None:
                request: dict[str, Any] = {"model": self.endpoint.model, "input": chunk}
                if self.dimensions:
                    request["dimensions"] = int(self.dimensions)
                response = self._client.embeddings.create(**request)
                for text, item in zip(
                    chunk, sorted(response.data, key=lambda item: item.index), strict=True
                ):
                    cache.entries[text] = list(item.embedding)

            _retry(
                call,
                attempts=self.attempts,
                base_seconds=self.retry_base_seconds,
                what="embedding batch",
            )
            cache.save()
        matrix = np.asarray([cache.entries[str(text)] for text in texts], dtype=np.float32)
        return matrix / np.clip(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12, None)
