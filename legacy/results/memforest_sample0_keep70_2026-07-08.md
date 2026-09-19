# MemForest Sample0 Keep70 Result

Date: 2026-07-08

This is a shared result card for the MemForest compression run on LoCoMo sample0.

## Setting

| Item | Value |
| --- | --- |
| Dataset | LoCoMo `dataset/locomo10.json` |
| Sample | sample0 only |
| Input store | `locomo_baseline_qwen36_strictjson_full10_v4_sample0_qa_snapshot` |
| Compressed store | `locomo_baseline_qwen36_strictjson_full10_v4_sample0_memforest_keep70` |
| Algorithm | `MemForest.py` |
| keep-ratio | 0.7 |
| cluster-ratio | 0.05 |
| semantic-time-alpha | 0.8 |
| time-window-size | 5 |
| Merge model | DashScope `qwen3.6-27b` |
| Embedding | DashScope `text-embedding-v4`, dim 1024 |
| QA/Judge model | DashScope `qwen3.6-27b` |
| Search top-k | 30 |

## Compression Stats

| Metric | Before | After |
| --- | ---: | ---: |
| sample0 mem0 nodes | 733 | 529 |
| total mem0 collection points | 776 | 572 |
| mem0_entities points | 597 | 597 |
| Qdrant SQLite size | 8.09 MB | 5.86 MB |

Cluster count: 36.
Merge count: 204.
API failures: 0.

The copied snapshot contained 43 sample1 `mem0` points. They were not compressed because the run used `--start-idx 0 --end-idx 0`.

## Evaluation

Official-style Mem0 search completed 199/199 QA. Official `evals.py` skipped category 5, leaving 152 judged items.

| Category | Count | Accuracy | B1 | F1 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 32 | 53.1% | 40.5% | 42.9% |
| 2 | 37 | 89.2% | 47.5% | 59.6% |
| 3 | 13 | 69.2% | 23.3% | 21.9% |
| 4 | 70 | 78.6% | 42.4% | 49.8% |
| Overall | 152 | 75.0% | 41.6% | 48.3% |

LLM judge correct: 114/152.

## Baseline Comparison

| Metric | Uncompressed sample0 | MemForest keep70 | Delta |
| --- | ---: | ---: | ---: |
| Accuracy | 75.0% | 75.0% | +0.0 pp |
| B1 | 42.6% | 41.6% | -1.0 pp |
| F1 | 52.0% | 48.3% | -3.7 pp |

Interpretation: in this sample0 Qwen/DashScope setup, MemForest keep70 preserved LLM-judge accuracy while reducing lexical overlap metrics.
