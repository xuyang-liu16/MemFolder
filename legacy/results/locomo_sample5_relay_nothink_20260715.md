# LoCoMo Sample5 Relay No-Thinking Results

Date: 2026-07-15 CST

Scope:
- Dataset: `dataset/locomo10.json`
- Sample: `sample5`
- QA model: relay `qwen3.6-plus`
- Judge model: relay `qwen3.6-plus`
- Embedding: DashScope `text-embedding-v4`
- Thinking disabled for merge / QA / judge.
- Official comparison scope: category 5 filtered out, `n=123`.

## Compression Stats

| Method | Budget | Nodes Before | Nodes After | Notes |
|---|---:|---:|---:|---|
| MemForest | keep70 | 333 | 240 | relay/no-thinking side run |
| MemForest | keep50 | 333 | 169 | relay/no-thinking side run |
| MemForest | keep30 | 333 | 107 | relay/no-thinking side run |
| RecallFlow-NC response-merge | keep70 | 333 | 233 | probes=537 |
| RecallFlow-NC response-merge | keep50 | 333 | 166 | probes=537 |
| RecallFlow-NC response-merge | keep30 | 333 | 100 | probes=537 |

## Evaluation

| Method | Budget | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|---:|
| Full Context | - | 123 | 0.3496 | 0.2825 | 0.2263 |
| MemForest | keep70 | 123 | 0.3415 | 0.2684 | 0.2151 |
| MemForest | keep50 | 123 | 0.3171 | 0.2590 | 0.2082 |
| MemForest | keep30 | 123 | 0.3252 | 0.2516 | 0.1977 |
| RecallFlow-NC | keep70 | 123 | 0.3333 | 0.2664 | 0.2137 |
| RecallFlow-NC | keep50 | 123 | 0.3496 | 0.2834 | 0.2371 |
| RecallFlow-NC | keep30 | 123 | 0.3496 | 0.2691 | 0.2182 |

## Artifacts

QA result directories live under:
`external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/`

- `sample5_full_context_relay_nothink_side_20260715`
- `sample5_memforest_keep70_relay_nothink_side_20260715`
- `sample5_memforest_keep50_relay_nothink_side_20260715`
- `sample5_memforest_keep30_relay_nothink_side_20260715`
- `sample5_recallflow_nc_response_merge_keep70_relay_nothink_side_20260715`
- `sample5_recallflow_nc_response_merge_keep50_relay_nothink_side_20260715`
- `sample5_recallflow_nc_response_merge_keep30_relay_nothink_side_20260715`

Each directory contains:
- raw QA result JSON with `158/158` questions,
- `_no_cat5.json` filtered input with `123` questions,
- `judge_attempts_official_no_cat5_relay_approved.jsonl`,
- `evaluation_metrics_official_no_cat5_relay_approved.json`.
