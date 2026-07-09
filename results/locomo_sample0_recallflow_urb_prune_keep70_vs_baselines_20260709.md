# LoCoMo Sample0: RecallFlow-URB Prune Keep70 vs Baselines

Date: 2026-07-09

## Purpose

Run QA and scoring for RecallFlow-compressed LoCoMo sample0 memory so it can be compared with the existing full Mem0 and MemForest keep70 baselines.

## Compared Runs

| method | store | compression |
|---|---|---|
| Full Mem0 | `locomo_sample0_rerun_full_20260708_153731` | no compression |
| MemForest keep70 | `locomo_sample0_rerun_memforest_keep70_20260708_153731` | official MemForest compressed store |
| RecallFlow-URB prune keep70 | `locomo_sample0_recallflow_urb_prune_keep70_20260709_qa` | fixed URB response fingerprint + farthest-first k-center, representative-only |

## RecallFlow Compression Details

- Script: `/mnt/disk1/memory-compression-v2/external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/RecallFlow_URB.py`
- Method: `recallflow_urb_prune_only`
- `keep-ratio`: `0.7`
- `tau`: `0.1`
- Seed: `0`
- Compression reads QA/gold/evidence: `false`
- URB basis: fixed, dataset-agnostic
- Sample0 compressed memory nodes: `733 -> 513` retained, `220` deleted
- Total `mem0` collection points in private store: `556`
- Total `mem0_entities` collection points in private store: `597`

Note: I also tried `recallflow_urb_full --keep-ratio 0.7`, but it retained `630/733` sample0 nodes because of exception keeps. That retention is about 86%, so I did not use it as the primary keep70 comparison.

## QA / Scoring Conditions

- Dataset: `dataset/locomo10.json`
- Sample range: `--start_idx 0 --end_idx 1`
- QA method: Mem0 `search`
- `top_k`: 30
- Filters: `False`
- Graph: `False`
- Answer model: DashScope OpenAI-compatible `qwen3.6-27b`
- Judge model: DashScope OpenAI-compatible `qwen3.6-27b`
- Scorer: `code.evaluation.scripts.score_locomo_qa_resumable`
- Scored questions: 152 non-category-5 questions

Important caveat: the first 122 QA answers were generated without an explicit max-token cap. One category-4 question then repeatedly timed out, so the resumed QA run set `CHAT_ANSWER_MAX_TOKENS=256` and `CHAT_ANSWER_ENABLE_THINKING=false` for the remaining 77 raw QA questions. Retrieval, store, prompt, `top_k`, answer model, and judge model were unchanged.

## Accuracy / F1

Values are percentages. `RF-MF` is `RecallFlow - MemForest`.

| split | n | full acc | MemForest acc | RecallFlow acc | RF-MF acc | full F1 | MemForest F1 | RecallFlow F1 | RF-MF F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| overall | 152 | 82.89 | 82.24 | 79.61 | -2.63 | 53.48 | 52.01 | 51.71 | -0.31 |
| 1 | 32 | 78.12 | 78.12 | 81.25 | +3.12 | 51.45 | 46.30 | 47.30 | +1.00 |
| 2 | 37 | 86.49 | 89.19 | 86.49 | -2.70 | 64.63 | 61.45 | 66.13 | +4.68 |
| 3 | 13 | 92.31 | 84.62 | 76.92 | -7.69 | 31.93 | 35.29 | 29.72 | -5.57 |
| 4 | 70 | 81.43 | 80.00 | 75.71 | -4.29 | 52.51 | 52.73 | 50.18 | -2.56 |

## BLEU1

| split | full B1 | MemForest B1 | RecallFlow B1 | RF-MF B1 |
|---|---:|---:|---:|---:|
| overall | 45.99 | 44.01 | 43.34 | -0.67 |
| 1 | 45.63 | 40.88 | 37.80 | -3.08 |
| 2 | 58.27 | 54.09 | 58.94 | +4.85 |
| 3 | 23.63 | 23.78 | 18.03 | -5.75 |
| 4 | 43.81 | 43.87 | 42.32 | -1.55 |

## Output Files

- QA output: `/mnt/disk1/memory-compression-v2/external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample0_recallflow_urb_prune_keep70_20260709/locomo_sample0_recallflow_urb_prune_keep70_20260709_qa_mem0_results_top_30_filter_False_graph_False.json`
- Metrics: `results/locomo_sample0_recallflow_urb_prune_keep70_20260709_metrics.json`
- Summary: `results/locomo_sample0_recallflow_urb_prune_keep70_20260709_summary.json`
- Compression diagnostics: `results/locomo_sample0_recallflow_urb_prune_keep70_20260709_diagnostics.jsonl`

## Interpretation

On this sample0 run, RecallFlow-URB prune keep70 is close to MemForest keep70 on lexical F1 and BLEU1, but lower on LLM-judge accuracy. The drop is concentrated in categories 3 and 4. Category 1 accuracy is better than MemForest, and category 2 lexical metrics are better, so the method is not uniformly worse.

The current result should be treated as an early engineering baseline for RecallFlow-URB prune-only, not the final RecallFlow full-capsule method. The full variant retained too many nodes under `keep-ratio=0.7`; a fair full-capsule comparison should either set a lower representative ratio to match final retention or change the exception policy.
