# LoCoMo Sample3 Relay No-Thinking Results

Date: 2026-07-15 CST

Scope:
- Dataset: `dataset/locomo10.json`
- Sample: `sample3`
- QA model: relay `qwen3.6-plus`
- Judge model: relay `qwen3.6-plus`
- Embedding: DashScope `text-embedding-v4`
- Thinking disabled for merge / QA / judge.
- Official comparison scope: category 5 filtered out, `n=199`.

## Compression Stats

| Method | Budget | Nodes Before | Nodes After | Notes |
|---|---:|---:|---:|---|
| MemForest | keep70 | 1016 | 731 | `api_failures=0` |
| MemForest | keep50 | 1016 | 520 | `api_failures=0` |
| MemForest | keep30 | 1016 | 330 | `api_failures=0` |
| RecallFlow-NC response-merge | keep70 | 1016 | 711 | probes=1778 |
| RecallFlow-NC response-merge | keep50 | 1016 | 508 | probes=1778 |
| RecallFlow-NC response-merge | keep30 | 1016 | 305 | probes=1778 |

## Evaluation

| Method | Budget | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|---:|
| Full Context | - | 199 | 0.6985 | 0.4273 | 0.3674 |
| MemForest | keep70 | 199 | 0.7186 | 0.4314 | 0.3691 |
| MemForest | keep50 | 199 | 0.7236 | 0.4448 | 0.3778 |
| MemForest | keep30 | 199 | 0.7186 | 0.4327 | 0.3696 |
| RecallFlow-NC | keep70 | 199 | 0.7085 | 0.4332 | 0.3684 |
| RecallFlow-NC | keep50 | 199 | 0.7186 | 0.4353 | 0.3624 |
| RecallFlow-NC | keep30 | 199 | 0.6834 | 0.4192 | 0.3555 |

## Artifacts

QA result directories live under:
`external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/`

- `sample3_full_context_relay_nothink_20260715`
- `sample3_memforest_keep70_relay_nothink_20260714`
- `sample3_memforest_keep50_relay_nothink_20260714`
- `sample3_memforest_keep30_relay_nothink_20260714`
- `sample3_recallflow_nc_response_merge_keep70_relay_nothink_20260714`
- `sample3_recallflow_nc_response_merge_keep50_relay_nothink_r2_20260715`
- `sample3_recallflow_nc_response_merge_keep30_relay_nothink_r2_20260715`

Each directory contains:
- raw QA result JSON with `260/260` questions,
- `_no_cat5.json` filtered input with `199` questions,
- `judge_attempts_official_no_cat5.jsonl`,
- `evaluation_metrics_official_no_cat5.json`.
