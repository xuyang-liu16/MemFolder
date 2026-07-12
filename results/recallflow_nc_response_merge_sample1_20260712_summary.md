# RecallFlow-NC Response-Merge on LoCoMo Sample1

Date: 2026-07-12

## Setup

- Source store: `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/locomo_baseline_qwen36_strictjson_full10_v4`
- Source node counts from Qdrant `mem0`: sample0=733, sample1=561, sample2=872
- Sample1 add checkpoint: 19 sessions, 259 completed add batches
- Dataset slice: LoCoMo `dataset/locomo10.json`, `start_idx=1`, `end_idx=2`
- Method: `recallflow_nc_response_merge`
- Model stack:
  - Chat / merge / judge: DashScope compatible OpenAI API, `qwen3.6-27b`
  - Embedding: DashScope compatible OpenAI API, `text-embedding-v4`, dim=1024
- Retrieval/eval:
  - `top_k=30`
  - QA generated for 105 questions
  - Official eval aggregated 81 questions; category 5 skipped by the evaluator

## Compression

| Run | Before | After | Deleted / Merged | Probes | Clusters | Objective |
|---|---:|---:|---:|---:|---:|---:|
| keep70 | 561 | 393 | 168 | 842 | 28 | 722003.771728 |
| keep50 | 561 | 280 | 281 | 842 | 28 | 3021830.540562 |

Diagnostics:

- `results/recallflow_nc_response_merge_sample1_keep70_20260712_codex_diagnostics.jsonl`
- `results/recallflow_nc_response_merge_sample1_keep50_20260712_codex_diagnostics.jsonl`

Compressed stores:

- `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/locomo_sample1_recallflow_nc_response_merge_keep70_20260712_codex_qa`
- `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/locomo_sample1_recallflow_nc_response_merge_keep50_20260712_codex_qa`

## Evaluation

| Method | Budget | Eval n | Accuracy | BLEU1 | F1 |
|---|---:|---:|---:|---:|---:|
| RecallFlow-NC response-merge | keep70 | 81 | 81.5% | 47.9% | 56.5% |
| RecallFlow-NC response-merge | keep50 | 81 | 74.1% | 42.9% | 52.6% |

Category breakdown:

| Budget | Category | n | Accuracy | BLEU1 | F1 |
|---|---:|---:|---:|---:|---:|
| keep70 | 1 | 11 | 72.7% | 33.8% | 47.3% |
| keep70 | 2 | 26 | 100.0% | 75.1% | 87.6% |
| keep70 | 4 | 44 | 72.7% | 35.4% | 40.5% |
| keep50 | 1 | 11 | 63.6% | 15.9% | 29.5% |
| keep50 | 2 | 26 | 96.2% | 75.3% | 88.2% |
| keep50 | 4 | 44 | 63.6% | 30.4% | 37.3% |

QA/eval output files:

- `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample1_recallflow_nc_response_merge_keep70_20260712_codex/locomo_sample1_recallflow_nc_response_merge_keep70_20260712_codex_qa_mem0_results_top_30_filter_False_graph_False.json`
- `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample1_recallflow_nc_response_merge_keep70_20260712_codex/evaluation_metrics.json`
- `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample1_recallflow_nc_response_merge_keep50_20260712_codex/locomo_sample1_recallflow_nc_response_merge_keep50_20260712_codex_qa_mem0_results_top_30_filter_False_graph_False.json`
- `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample1_recallflow_nc_response_merge_keep50_20260712_codex/evaluation_metrics.json`

## Notes

- Compression did not read QA questions, gold answers, or evidence; probes are node-conditioned from memory text only.
- `tau=0.1` was fixed.
- The evaluator warned that SentenceTransformer could not be loaded from `hf-mirror.com`; the run still completed and reported LLM accuracy, BLEU1, and F1.
- Compared with sample0, sample1 keep70 is strong on all three headline metrics. keep50 has a clear drop from keep70, especially category 1 and 4.
