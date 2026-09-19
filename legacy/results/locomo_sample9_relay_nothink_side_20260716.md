# LoCoMo Sample9 Relay No-Thinking Results

Date: 2026-07-16 JST

Scope:
- Dataset: `dataset/locomo10.json`
- Sample: `sample9`
- QA model: relay `qwen3.6-plus`
- Judge model: relay `qwen3.6-plus`
- Embedding: DashScope `text-embedding-v4`
- Thinking disabled for merge / QA / judge.
- Official comparison scope: category 5 filtered out, `n=158`.

## Compression Stats

| Method | Budget | Nodes Before | Nodes After | Notes |
|---|---:|---:|---:|---|
| MemForest | keep70 | 889 | 642 | `api_failures=0` |
| MemForest | keep50 | 889 | 454 | `api_failures=0` |
| MemForest | keep30 | 889 | 287 | `api_failures=0` |
| RecallFlow-NC response-merge | keep70 | 889 | 622 | probes=1490 |
| RecallFlow-NC response-merge | keep50 | 889 | 444 | probes=1490 |
| RecallFlow-NC response-merge | keep30 | 889 | 267 | probes=1490 |

## Evaluation

| Method | Budget | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|---:|
| Full Context | - | 158 | 0.7975 | 0.5282 | 0.4481 |
| MemForest | keep70 | 158 | 0.7722 | 0.5138 | 0.4364 |
| MemForest | keep50 | 158 | 0.7532 | 0.4919 | 0.4215 |
| MemForest | keep30 | 158 | 0.7595 | 0.4735 | 0.4054 |
| RecallFlow-NC | keep70 | 158 | 0.7785 | 0.5207 | 0.4540 |
| RecallFlow-NC | keep50 | 158 | 0.7658 | 0.4893 | 0.4204 |
| RecallFlow-NC | keep30 | 158 | 0.7215 | 0.4880 | 0.4180 |

## Artifact Directories

Under `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/`:

- `sample9_full_context_relay_nothink_side_20260716`
- `sample9_memforest_keep70_relay_nothink_side_20260716`
- `sample9_memforest_keep50_relay_nothink_side_20260716`
- `sample9_memforest_keep30_relay_nothink_side_20260716`
- `sample9_recallflow_nc_response_merge_keep70_relay_nothink_side_20260716`
- `sample9_recallflow_nc_response_merge_keep50_relay_nothink_side_20260716`
- `sample9_recallflow_nc_response_merge_keep30_relay_nothink_side_20260716`

Each directory contains raw QA JSON (`204/204`), `_no_cat5.json` (`158`), `judge_attempts_official_no_cat5.jsonl`, and `evaluation_metrics_official_no_cat5.json`.
