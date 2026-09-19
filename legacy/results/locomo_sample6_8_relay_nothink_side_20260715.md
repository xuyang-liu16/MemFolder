# LoCoMo Sample6-8 Relay No-Thinking Results

Date: 2026-07-15 CST

Scope:
- Dataset: `dataset/locomo10.json`
- Samples: `sample6`, `sample7`, `sample8`
- QA model: relay `qwen3.6-plus`
- Judge model: relay `qwen3.6-plus`
- Embedding: DashScope `text-embedding-v4`
- Thinking disabled for merge / QA / judge.
- Official comparison scope: category 5 filtered out.
- Note: sample7 contains duplicate raw `question_id` values. For sample7 judge, `_no_cat5_unique.json` inputs were used so all 191 rows are scored.

## Evaluation

### sample6

| Method | Budget | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|---:|
| Full Context | - | 150 | 0.7933 | 0.6010 | 0.5126 |
| MemForest | keep70 | 150 | 0.7133 | 0.5479 | 0.4657 |
| MemForest | keep50 | 150 | 0.7133 | 0.5489 | 0.4665 |
| MemForest | keep30 | 150 | 0.7267 | 0.5497 | 0.4657 |
| RecallFlow-NC | keep70 | 150 | 0.7267 | 0.5497 | 0.4661 |
| RecallFlow-NC | keep50 | 150 | 0.7267 | 0.5466 | 0.4675 |
| RecallFlow-NC | keep30 | 150 | 0.7200 | 0.5452 | 0.4602 |

### sample7

| Method | Budget | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|---:|
| Full Context | - | 191 | 0.7435 | 0.5414 | 0.4453 |
| MemForest | keep70 | 191 | 0.7330 | 0.5165 | 0.4258 |
| MemForest | keep50 | 191 | 0.7435 | 0.5252 | 0.4354 |
| MemForest | keep30 | 191 | 0.7120 | 0.4775 | 0.3887 |
| RecallFlow-NC | keep70 | 191 | 0.7435 | 0.5226 | 0.4283 |
| RecallFlow-NC | keep50 | 191 | 0.7592 | 0.5461 | 0.4458 |
| RecallFlow-NC | keep30 | 191 | 0.7016 | 0.5267 | 0.4310 |

### sample8

| Method | Budget | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|---:|
| Full Context | - | 156 | 0.7051 | 0.5216 | 0.4447 |
| MemForest | keep70 | 156 | 0.6987 | 0.5137 | 0.4394 |
| MemForest | keep50 | 156 | 0.7692 | 0.5251 | 0.4400 |
| MemForest | keep30 | 156 | 0.7308 | 0.5064 | 0.4313 |
| RecallFlow-NC | keep70 | 156 | 0.7244 | 0.5317 | 0.4552 |
| RecallFlow-NC | keep50 | 156 | 0.7564 | 0.5167 | 0.4363 |
| RecallFlow-NC | keep30 | 156 | 0.6859 | 0.5101 | 0.4340 |

## QA / Judge Coverage

| Sample | Raw QA Rows | No Cat5 Rows | Judge Rows |
|---|---:|---:|---:|
| sample6 | 190 | 150 | 150 |
| sample7 | 239 | 191 | 191 |
| sample8 | 196 | 156 | 156 |
