# LoCoMo Sample7 Relay No-Thinking Results

Date: 2026-07-15 CST

Scope:
- Dataset: `dataset/locomo10.json`
- Sample: `sample7`
- QA model: relay `qwen3.6-plus`
- Judge model: relay `qwen3.6-plus`
- Embedding: DashScope `text-embedding-v4`
- Thinking disabled for merge / QA / judge.
- Official comparison scope: category 5 filtered out, `n=191`.
- `evaluation_metrics_official_no_cat5_unique.json` is used because the raw QA file contains duplicate `question_id` values.

## Evaluation

| Method | Budget | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|---:|
| Full Context | - | 191 | 0.7435 | 0.5414 | 0.4453 |
| MemForest | keep70 | 191 | 0.7330 | 0.5165 | 0.4258 |
| MemForest | keep50 | 191 | 0.7435 | 0.5252 | 0.4354 |
| MemForest | keep30 | 191 | 0.7120 | 0.4775 | 0.3887 |
| RecallFlow-NC | keep70 | 191 | 0.7435 | 0.5226 | 0.4283 |
| RecallFlow-NC | keep50 | 191 | 0.7592 | 0.5461 | 0.4458 |
| RecallFlow-NC | keep30 | 191 | 0.7016 | 0.5267 | 0.4310 |

## Source

Extracted from `results/locomo_sample6_8_relay_nothink_side_20260715.md`.
