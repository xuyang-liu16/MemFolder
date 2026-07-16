# LoCoMo Sample6 Relay No-Thinking Results

Date: 2026-07-15 CST

Scope:
- Dataset: `dataset/locomo10.json`
- Sample: `sample6`
- QA model: relay `qwen3.6-plus`
- Judge model: relay `qwen3.6-plus`
- Embedding: DashScope `text-embedding-v4`
- Thinking disabled for merge / QA / judge.
- Official comparison scope: category 5 filtered out, `n=150`.

## Evaluation

| Method | Budget | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|---:|
| Full Context | - | 150 | 0.7933 | 0.6010 | 0.5126 |
| MemForest | keep70 | 150 | 0.7133 | 0.5479 | 0.4657 |
| MemForest | keep50 | 150 | 0.7133 | 0.5489 | 0.4665 |
| MemForest | keep30 | 150 | 0.7267 | 0.5497 | 0.4657 |
| RecallFlow-NC | keep70 | 150 | 0.7267 | 0.5497 | 0.4661 |
| RecallFlow-NC | keep50 | 150 | 0.7267 | 0.5466 | 0.4675 |
| RecallFlow-NC | keep30 | 150 | 0.7200 | 0.5452 | 0.4602 |

## Source

Extracted from `results/locomo_sample6_8_relay_nothink_side_20260715.md`.
