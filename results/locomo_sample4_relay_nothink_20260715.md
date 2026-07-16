# LoCoMo Sample4 Relay No-Thinking Results

Date: 2026-07-15 CST

Scope:
- Dataset: `dataset/locomo10.json`
- Sample: `sample4`
- QA model: relay `qwen3.6-plus`
- Judge model: relay `qwen3.6-plus`
- Embedding: DashScope `text-embedding-v4`
- Thinking disabled for merge / QA / judge.
- Official comparison scope: category 5 filtered out, `n=178`.

## Compression Stats

| Method | Budget | Nodes Before | Nodes After | Notes |
|---|---:|---:|---:|---|
| MemForest | keep70 | 925 | 670 | `api_failures=0` |
| MemForest | keep50 | 925 | 477 | `api_failures=0` |
| MemForest | keep30 | 925 | 297 | `api_failures=0` |
| RecallFlow-NC response-merge | keep70 | 925 | 648 | probes=1620 |
| RecallFlow-NC response-merge | keep50 | 925 | 462 | probes=1620 |
| RecallFlow-NC response-merge | keep30 | 925 | 278 | probes=1620 |

## Evaluation

| Method | Budget | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|---:|
| Full Context | - | 178 | 0.6798 | 0.5143 | 0.4215 |
| MemForest | keep70 | 178 | 0.6629 | 0.5101 | 0.4234 |
| MemForest | keep50 | 178 | 0.6910 | 0.5148 | 0.4191 |
| MemForest | keep30 | 178 | 0.6742 | 0.4966 | 0.4128 |
| RecallFlow-NC | keep70 | 178 | 0.6910 | 0.5268 | 0.4387 |
| RecallFlow-NC | keep50 | 178 | 0.6742 | 0.5140 | 0.4236 |
| RecallFlow-NC | keep30 | 178 | 0.6966 | 0.5122 | 0.4245 |

## Artifacts

QA result directories live under:
`external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/`

- `sample4_full_context_relay_nothink_20260715`
- `sample4_memforest_keep70_relay_nothink_20260715`
- `sample4_memforest_keep50_relay_nothink_20260715`
- `sample4_memforest_keep30_relay_nothink_20260715`
- `sample4_recallflow_nc_response_merge_keep70_relay_nothink_20260715`
- `sample4_recallflow_nc_response_merge_keep50_relay_nothink_20260715`
- `sample4_recallflow_nc_response_merge_keep30_relay_nothink_20260715`

Each directory contains:
- raw QA result JSON with `242/242` questions,
- `_no_cat5.json` filtered input with `178` questions,
- `judge_attempts_official_no_cat5.jsonl`,
- `evaluation_metrics_official_no_cat5.json`.
