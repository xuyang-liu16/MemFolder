"""Step 7b — the LoCoMo judge, as its own process.

Scores one sample's QA output on the official LoCoMo terms: category-5
questions are dropped, BLEU-1 and token F1 come from the vendored ``metrics``
module, and an LLM grader supplies the accuracy label using the vendor's own
``ACCURACY_PROMPT``.  Using the vendor's prompt and metric code verbatim is the
point -- it is what makes the numbers comparable to published ones.

This is a separate process rather than a function because the vendored
``metrics`` package imports nltk and bert_score and builds an OpenAI client at
import time; keeping it behind a subprocess boundary keeps the method package
importable without any of that.

    python -m g1s.judge --input-file qa.json --attempts-file attempts.jsonl \\
        --output-file scores.json --sample-idx 3

Results are appended to the attempts file as they finish, so an interrupted run
resumes without re-grading (and without re-paying for) anything already graded.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

#: Question ids of this shape sort back into their original order.
_ID_PATTERN = re.compile(r"^(\d+):(\d+):(.*)$", re.DOTALL)


class JudgeOutputError(RuntimeError):
    """The provider answered, but not with a verdict we can use."""

    def __init__(self, message: str, *, prompt_tokens: int = 0, completion_tokens: int = 0):
        super().__init__(message)
        self.prompt_tokens = int(prompt_tokens)
        self.completion_tokens = int(completion_tokens)


# ------------------------------------------------------------------ QA records


def flatten_items(path: Path) -> list[dict[str, Any]]:
    """Read a QA file, which is either a flat list or grouped by category."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [dict(item) for item in data]
    items: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for group, values in data.items():
            for index, item in enumerate(values):
                row = dict(item)
                row.setdefault("question_id", f"{group}:{index}:{row.get('question', '')}")
                items.append(row)
    return items


def question_id_of(sample: int, index: int, question: str, mode: str) -> str:
    """Identity of a question.

    Sample 7 repeats question text verbatim, so grading keyed on the text alone
    would collapse several distinct questions into one; ``unique`` prefixes the
    position to keep them apart.
    """
    return f"{sample}:{index}:{question}" if mode == "unique" else question


def graded_already(path: Path) -> dict[str, dict[str, Any]]:
    done: dict[str, dict[str, Any]] = {}
    if not Path(path).exists():
        return done
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") == "ok":
                done[str(row["question_id"])] = row
    return done


def write_scores(path: Path, rows: dict[str, dict[str, Any]]) -> None:
    def order(row: dict[str, Any]) -> tuple[int, int, str]:
        match = _ID_PATTERN.match(str(row.get("question_id", "")))
        if match:
            return int(match.group(1)), int(match.group(2)), match.group(3)
        return sys.maxsize, sys.maxsize, str(row.get("question_id", ""))

    fields = (
        "question",
        "answer",
        "response",
        "category",
        "bleu_score",
        "f1_score",
        "llm_score",
        "question_id",
    )
    grouped = {
        "longmemeval": [
            {key: row[key] for key in fields} for row in sorted(rows.values(), key=order)
        ]
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(grouped, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- the LLM judge


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [
            part if isinstance(part, str) else str(part.get("text", ""))
            for part in value
            if isinstance(part, (str, dict))
        ]
        return "".join(parts).strip()
    return ""


def parse_label(message: Any) -> int:
    """Read CORRECT/WRONG out of a completion, however it was dressed up."""
    raw = _as_text(getattr(message, "content", None))
    if not raw:
        raise JudgeOutputError("empty judge completion")
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE).strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            label = str(parsed.get("label", "")).strip().upper()
            if label in {"CORRECT", "WRONG"}:
                return int(label == "CORRECT")
    except json.JSONDecodeError:
        pass
    plain = stripped.strip(". \n\t\"'").upper()
    if plain in {"CORRECT", "WRONG"}:
        return int(plain == "CORRECT")
    match = re.search(
        r"[\"']label[\"']\s*:\s*[\"']?(CORRECT|WRONG)[\"']?", stripped, re.IGNORECASE
    )
    if match:
        return int(match.group(1).upper() == "CORRECT")
    raise JudgeOutputError(f"unusable judge completion ({len(stripped)} chars)")


def judge(client, model: str, template: str, question: str, gold: str, generated: str) -> tuple[int, int, int]:
    """Grade one answer. Returns ``(label, prompt_tokens, completion_tokens)``.

    Tried twice: once asking for a JSON object, once plain.  Some
    OpenAI-compatible providers reject ``response_format`` outright, and some
    reasoning models spend the whole token budget before emitting the verdict.
    """
    request: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": template.format(
                    question=question, gold_answer=gold, generated_answer=generated
                ),
            }
        ],
        "temperature": 0.0,
        "max_tokens": int(os.getenv("JUDGE_MAX_TOKENS", "128")),
    }
    variants = [{**request, "response_format": {"type": "json_object"}}, request]

    errors: list[str] = []
    prompt_tokens = completion_tokens = 0
    for variant in variants:
        try:
            response = client.chat.completions.create(**variant)
            usage = getattr(response, "usage", None)
            prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
            if not response.choices:
                raise JudgeOutputError("completion has no choices")
            return parse_label(response.choices[0].message), prompt_tokens, completion_tokens
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
    raise JudgeOutputError(
        "; ".join(errors), prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
    )


def judge_client():
    from openai import OpenAI

    kwargs: dict[str, Any] = {"max_retries": 0}
    api_key = os.getenv("JUDGE_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("JUDGE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    if os.getenv("JUDGE_TIMEOUT_SECONDS"):
        kwargs["timeout"] = float(os.environ["JUDGE_TIMEOUT_SECONDS"])
    return OpenAI(**kwargs)


# --------------------------------------------------------------------- the CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-file", type=Path, required=True)
    parser.add_argument("--attempts-file", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--sample-idx", type=int, required=True)
    parser.add_argument("--eval-root", type=Path, required=True, help="vendored Mem0 evaluation dir")
    parser.add_argument("--question-id-mode", choices=("unique", "question"), default="question")
    parser.add_argument("--retries", type=int, default=8)
    parser.add_argument("--retry-sleep", type=float, default=8.0)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)

    # The vendored metrics module is the reference implementation of BLEU/F1 and
    # owns the official judge prompt; import it from the evaluation tree.
    sys.path.insert(0, str(args.eval_root))
    from metrics.llm_judge import ACCURACY_PROMPT
    from metrics.utils import calculate_bleu_scores, calculate_metrics

    client = judge_client()
    model = os.getenv("JUDGE_MODEL") or os.getenv("MODEL", "gpt-4o-mini")

    done = graded_already(args.attempts_file)
    pending: list[tuple[str, dict[str, Any]]] = []
    kept = 0
    for item in flatten_items(args.input_file):
        # Category 5 is adversarial/unanswerable and is excluded from the
        # official numbers.
        if str(item.get("category", "")) == "5":
            continue
        question_id = question_id_of(
            args.sample_idx, kept, str(item["question"]), args.question_id_mode
        )
        kept += 1
        if question_id not in done:
            pending.append((question_id, item))

    def evaluate(task: tuple[str, dict[str, Any]]) -> dict[str, Any]:
        question_id, item = task
        question, answer, response = (
            str(item["question"]),
            str(item["answer"]),
            str(item["response"]),
        )
        last: Exception | None = None
        for attempt in range(1, args.retries + 1):
            try:
                metrics = calculate_metrics(response, answer)
                bleu = calculate_bleu_scores(response, answer)
                label, _, _ = judge(client, model, ACCURACY_PROMPT, question, answer, response)
                return {
                    "status": "ok",
                    "question_id": question_id,
                    "question": question,
                    "answer": answer,
                    "response": response,
                    "category": str(item.get("category", "")),
                    "bleu_score": bleu["bleu1"],
                    "f1_score": metrics["f1"],
                    "llm_score": label,
                }
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt < args.retries:
                    time.sleep(
                        min(args.retry_sleep * (2 ** (attempt - 1)), 45.0)
                        + random.uniform(0.0, 0.5)
                    )
        return {
            "status": "error",
            "question_id": question_id,
            "error_type": type(last).__name__ if last else "UnknownError",
            "error": str(last),
        }

    args.attempts_file.parent.mkdir(parents=True, exist_ok=True)
    with args.attempts_file.open("a", encoding="utf-8") as handle:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = [pool.submit(evaluate, task) for task in pending]
            for finished, future in enumerate(as_completed(futures), start=1):
                row = future.result()
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                if row.get("status") == "ok":
                    done[str(row["question_id"])] = row
                if finished % 100 == 0 or finished == len(pending):
                    print(f"scoring {finished}/{len(pending)} ok={len(done)}", flush=True)

    write_scores(args.output_file, done)
    print(f"scored {len(done)}/{kept}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
