"""Score LoCoMo QA outputs with resumable per-item writes.

This script mirrors the MemForest LoCoMo metrics used in
`evaluation/evals.py`: token F1, BLEU-1, and LLM judge accuracy. It avoids
the import-time NLTK downloads in the upstream helper and writes results after
each judged item so interrupted runs can resume.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Dict, Iterable, List, Tuple

from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu
from openai import OpenAI


ACCURACY_PROMPT = """
Your task is to label an answer to a question as 'CORRECT' or 'WRONG'. You will be given the following data:
    (1) a question (posed by one user to another user),
    (2) a 'gold' (ground truth) answer,
    (3) a generated answer
which you will score as CORRECT/WRONG.

The point of the question is to ask about something one user should know about the other user based on their prior conversations.
The gold answer will usually be a concise and short answer that includes the referenced topic.
The generated answer might be much longer, but you should be generous with your grading - as long as it touches on the same topic as the gold answer, it should be counted as CORRECT.

For time related questions, be generous with formatting differences. If it refers to the same date or time period as the gold answer, count it as CORRECT.

Question: {question}
Gold answer: {gold_answer}
Generated answer: {generated_answer}

Return JSON only with key "label" and value "CORRECT" or "WRONG".
"""


def load_config(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    for key, value in data.items():
        if key and value is not None and key not in os.environ:
            os.environ[key] = str(value)


def load_qa(path: Path) -> Dict[str, List[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("input QA file must be a JSON object keyed by sample")
    return {str(k): list(v) for k, v in data.items() if isinstance(v, list)}


def load_existing(path: Path) -> Dict[str, List[dict]]:
    if not path.exists():
        return defaultdict(list)
    data = json.loads(path.read_text(encoding="utf-8"))
    out = defaultdict(list)
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list):
                out[str(key)].extend(value)
    return out


def item_key(item: dict) -> Tuple[str, str, str, str]:
    return (
        str(item.get("question", "")),
        str(item.get("answer", "")),
        str(item.get("response", "")),
        str(item.get("category", "")),
    )


def simple_tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9]+", str(text).lower())


def token_f1(prediction: str, reference: str) -> float:
    pred = set(simple_tokenize(prediction))
    ref = set(simple_tokenize(reference))
    if not pred or not ref:
        return 0.0
    overlap = pred & ref
    precision = len(overlap) / len(pred)
    recall = len(overlap) / len(ref)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def bleu1(prediction: str, reference: str) -> float:
    pred = simple_tokenize(prediction)
    ref = [simple_tokenize(reference)]
    if not pred or not ref[0]:
        return 0.0
    return float(sentence_bleu(ref, pred, weights=(1, 0, 0, 0), smoothing_function=SmoothingFunction().method1))


def make_client(timeout: float) -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for LLM judge")
    return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)


def extract_label(text: str) -> int:
    try:
        payload = json.loads(text)
        label = str(payload.get("label", "")).upper()
    except Exception:
        label = text.upper()
    if "CORRECT" in label and "WRONG" not in label:
        return 1
    if "WRONG" in label:
        return 0
    raise ValueError(f"could not parse judge label: {text[:120]}")


def judge_item(client: OpenAI, model: str, item: dict, retries: int, sleep_s: float) -> int:
    prompt = ACCURACY_PROMPT.format(
        question=item["question"],
        gold_answer=item["answer"],
        generated_answer=item["response"],
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            return extract_label(response.choices[0].message.content or "")
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(sleep_s * (attempt + 1))
    raise RuntimeError(f"judge failed after {retries + 1} attempts: {last_error}")


def write_json(path: Path, data: Dict[str, List[dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def iter_items(data: Dict[str, List[dict]]) -> Iterable[Tuple[str, dict]]:
    for key, items in data.items():
        for item in items:
            if str(item.get("category")) == "5":
                continue
            yield key, item


def summarize(results: Dict[str, List[dict]]) -> dict:
    rows = [item for items in results.values() for item in items]
    by_cat: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        by_cat[str(row["category"])].append(row)
    summary = {
        "overall": {
            "count": len(rows),
            "llm_accuracy": mean([r["llm_score"] for r in rows]) if rows else None,
            "bleu1": mean([r["bleu_score"] for r in rows]) if rows else None,
            "f1": mean([r["f1_score"] for r in rows]) if rows else None,
        },
        "categories": {},
    }
    for cat, cat_rows in sorted(by_cat.items()):
        summary["categories"][cat] = {
            "count": len(cat_rows),
            "llm_accuracy": mean([r["llm_score"] for r in cat_rows]),
            "bleu1": mean([r["bleu_score"] for r in cat_rows]),
            "f1": mean([r["f1_score"] for r in cat_rows]),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumable LoCoMo QA scoring.")
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--summary-file", required=True)
    parser.add_argument("--config", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-sleep", type=float, default=2.0)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    load_config(Path(args.config) if args.config else None)
    model = args.model or os.getenv("JUDGE_MODEL") or os.getenv("MODEL") or "qwen3.6-plus"
    client = make_client(args.timeout)

    data = load_qa(Path(args.input_file))
    results = load_existing(Path(args.output_file))
    done = {item_key(row) for rows in results.values() for row in rows}
    total = sum(1 for _, _ in iter_items(data))
    completed_this_run = 0

    for key, item in iter_items(data):
        if args.limit is not None and completed_this_run >= args.limit:
            break
        if item_key(item) in done:
            continue
        row = {
            "question": str(item["question"]),
            "answer": str(item["answer"]),
            "response": str(item["response"]),
            "category": str(item["category"]),
            "bleu_score": bleu1(str(item["response"]), str(item["answer"])),
            "f1_score": token_f1(str(item["response"]), str(item["answer"])),
            "llm_score": judge_item(client, model, item, args.retries, args.retry_sleep),
        }
        results[str(key)].append(row)
        done.add(item_key(item))
        completed_this_run += 1
        write_json(Path(args.output_file), results)
        print(json.dumps({"completed": len(done), "total": total, "last_category": row["category"]}))

    summary = summarize(results)
    Path(args.summary_file).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary_file).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": args.output_file, "summary": args.summary_file, "completed": len(done), "total": total}))


if __name__ == "__main__":
    main()
