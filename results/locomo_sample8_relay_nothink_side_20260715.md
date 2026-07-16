# LoCoMo Sample8 Relay No-Thinking Results

Date: 2026-07-15 CST

Scope:
- Dataset: `dataset/locomo10.json`
- Sample: `sample8`
- QA model: relay `qwen3.6-plus`
- Judge model: relay `qwen3.6-plus`
- Embedding: DashScope `text-embedding-v4`
- Thinking disabled for merge / QA / judge.
- Official comparison scope: category 5 filtered out, `n=156`.

## Evaluation

| Method | Budget | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|---:|
| Full Context | - | 156 | 0.7051 | 0.5216 | 0.4447 |
| MemForest | keep70 | 156 | 0.6987 | 0.5137 | 0.4394 |
| MemForest | keep50 | 156 | 0.7692 | 0.5251 | 0.4400 |
| MemForest | keep30 | 156 | 0.7308 | 0.5064 | 0.4313 |
| RecallFlow-NC | keep70 | 156 | 0.7244 | 0.5317 | 0.4552 |
| RecallFlow-NC | keep50 | 156 | 0.7564 | 0.5167 | 0.4363 |
| RecallFlow-NC | keep30 | 156 | 0.6859 | 0.5101 | 0.4340 |

## Source

Extracted from `results/locomo_sample6_8_relay_nothink_side_20260715.md`.
