# LoCoMo Sample0 Rerun: Full Mem0 vs MemForest Keep70

Date: 2026-07-08

## Purpose

Independently rerun LoCoMo sample0 QA and judging for:

- Full uncompressed Mem0 store
- Official MemForest compressed keep70 store

This rerun was requested because the previous comparison showed a large gap, especially on category 1. The rerun used private copied stores to avoid local Qdrant concurrent access conflicts.

## Conditions

- Dataset: `dataset/locomo10.json`
- Sample range: `--start_idx 0 --end_idx 1`
- QA retrieval: Mem0 `search`
- `top_k`: 30
- Filters: `False`
- Graph: `False`
- Answer model: DashScope OpenAI-compatible `qwen3.6-27b`
- Judge model: DashScope OpenAI-compatible `qwen3.6-27b`
- Scoring: `code.evaluation.scripts.score_locomo_qa_resumable`
- Scored questions: 152 non-category-5 questions

## Stores

- Full source snapshot: `locomo_baseline_qwen36_strictjson_full10_v4_sample0_qa_snapshot`
- Keep70 source snapshot: `locomo_baseline_qwen36_strictjson_full10_v4_sample0_memforest_keep70`
- Full private rerun store: `/mnt/disk1/memory-compression-v2/external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/locomo_sample0_rerun_full_20260708_153731`
- Keep70 private rerun store: `/mnt/disk1/memory-compression-v2/external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/locomo_sample0_rerun_memforest_keep70_20260708_153731`

## Memory Size

| collection | full | keep70 | retention |
|---|---:|---:|---:|
| mem0 points | 776 | 572 | 73.7% |
| mem0_entities points | 597 | 597 | 100.0% |

## Metrics

Values are percentages. Delta is `keep70 - full`.

| split | n | full acc | keep70 acc | delta acc | full B1 | keep70 B1 | delta B1 | full F1 | keep70 F1 | delta F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| overall | 152 | 82.89 | 82.24 | -0.66 | 45.99 | 44.01 | -1.98 | 53.48 | 52.01 | -1.47 |
| 1 | 32 | 78.12 | 78.12 | 0.00 | 45.63 | 40.88 | -4.75 | 51.45 | 46.30 | -5.14 |
| 2 | 37 | 86.49 | 89.19 | 2.70 | 58.27 | 54.09 | -4.18 | 64.63 | 61.45 | -3.18 |
| 3 | 13 | 92.31 | 84.62 | -7.69 | 23.63 | 23.78 | 0.15 | 31.93 | 35.29 | 3.36 |
| 4 | 70 | 81.43 | 80.00 | -1.43 | 43.81 | 43.87 | 0.06 | 52.51 | 52.73 | 0.22 |

## Output Files

- Full QA: `/mnt/disk1/memory-compression-v2/external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample0_rerun_20260708_153731_full/locomo_sample0_rerun_full_20260708_153731_mem0_results_top_30_filter_False_graph_False.json`
- Keep70 QA: `/mnt/disk1/memory-compression-v2/external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample0_rerun_20260708_153731_memforest_keep70/locomo_sample0_rerun_memforest_keep70_20260708_153731_mem0_results_top_30_filter_False_graph_False.json`
- Full metrics: `results/locomo_sample0_rerun_full_20260708_153731_metrics.json`
- Full summary: `results/locomo_sample0_rerun_full_20260708_153731_summary.json`
- Keep70 metrics: `results/locomo_sample0_rerun_memforest_keep70_20260708_153731_metrics.json`
- Keep70 summary: `results/locomo_sample0_rerun_memforest_keep70_20260708_153731_summary.json`

## Interpretation

This independent rerun does not reproduce the earlier large degradation. The keep70 compressed store is very close to the full store on overall LLM-judge accuracy, with a small drop in BLEU1 and token F1. Category 1 accuracy is unchanged in this rerun, although lexical metrics drop by about 5 points.

The earlier large gap is therefore likely caused by run-specific conditions or artifact mismatch rather than a stable keep70 compression effect. The next debugging target should be comparing the exact earlier QA outputs against this rerun, especially category 1, and checking whether the previous full and compressed stores came from identical add/extraction states.
