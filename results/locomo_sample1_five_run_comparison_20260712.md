# LoCoMo Sample1 Official Five-Run Comparison

Date: 2026-07-12

## Setup

- Dataset slice: LoCoMo `dataset/locomo10.json`, sample1 only (`start_idx=1`, `end_idx=2`)
- Compared runs:
  - Full context / Full Mem0
  - MemForest keep70
  - MemForest keep50
  - RecallFlow NC keep70
  - RecallFlow NC keep50
- Model stack:
  - Chat / merge / judge: DashScope compatible OpenAI API, `qwen3.6-27b`
  - Embedding: DashScope compatible OpenAI API, `text-embedding-v4`, dim=1024
- Retrieval/eval:
  - `top_k=30`
  - Official eval aggregated 81 questions
  - Category 5 skipped by the official evaluator

## Main Results

| Method | Nodes after | Eval n | Accuracy | BLEU1 | F1 |
|---|---:|---:|---:|---:|---:|
| Full context | 561 | 81 | 82.7% | 50.2% | 59.9% |
| MemForest keep70 | 393 | 81 | 79.0% | 49.1% | 57.7% |
| MemForest keep50 | 281 | 81 | 75.3% | 48.3% | 55.8% |
| RecallFlow NC keep70 | 393 | 81 | 81.5% | 47.9% | 56.5% |
| RecallFlow NC keep50 | 280 | 81 | 74.1% | 42.9% | 52.6% |

Category breakdown:

| Method | Category | n | Accuracy | BLEU1 | F1 |
|---|---:|---:|---:|---:|---:|
| Full context | 1 | 11 | 72.7% | 33.4% | 45.3% |
| Full context | 2 | 26 | 100.0% | 74.7% | 89.2% |
| Full context | 4 | 44 | 75.0% | 39.9% | 46.3% |
| MemForest keep70 | 1 | 11 | 63.6% | 34.2% | 45.2% |
| MemForest keep70 | 2 | 26 | 100.0% | 74.6% | 88.5% |
| MemForest keep70 | 4 | 44 | 70.5% | 37.7% | 42.6% |
| MemForest keep50 | 1 | 11 | 63.6% | 34.5% | 43.7% |
| MemForest keep50 | 2 | 26 | 92.3% | 74.7% | 86.0% |
| MemForest keep50 | 4 | 44 | 68.2% | 36.1% | 40.9% |
| RecallFlow NC keep70 | 1 | 11 | 72.7% | 33.8% | 47.3% |
| RecallFlow NC keep70 | 2 | 26 | 100.0% | 75.1% | 87.6% |
| RecallFlow NC keep70 | 4 | 44 | 72.7% | 35.4% | 40.5% |
| RecallFlow NC keep50 | 1 | 11 | 63.6% | 15.9% | 29.5% |
| RecallFlow NC keep50 | 2 | 26 | 96.2% | 75.3% | 88.2% |
| RecallFlow NC keep50 | 4 | 44 | 63.6% | 30.4% | 37.3% |

QA/eval output files:

- `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample1_full_mem0_20260712_codex/evaluation_metrics.json`
- `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample1_memforest_keep70_20260712_codex/evaluation_metrics.json`
- `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample1_memforest_keep50_20260712_codex/evaluation_metrics.json`
- `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample1_recallflow_nc_response_merge_keep70_20260712_codex/evaluation_metrics.json`
- `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample1_recallflow_nc_response_merge_keep50_20260712_codex/evaluation_metrics.json`

## Notes

- Full context is the upper bound on this sample and remains strongest overall.
- RecallFlow NC keep70 has higher LLM-judge accuracy than MemForest keep70 (`81.5%` vs `79.0%`) at the same retained-node budget, but lower BLEU1/F1.
- RecallFlow NC keep50 is slightly below MemForest keep50 across headline metrics on sample1.
- Raw QA outputs and compressed stores remain under `external/` and are not committed.
