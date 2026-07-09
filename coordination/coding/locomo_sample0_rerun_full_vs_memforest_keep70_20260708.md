# Coding Log: LoCoMo Sample0 Full vs MemForest Keep70 Rerun

Date: 2026-07-08

## Request

The previous full-vs-compressed result showed a large metric gap. The user requested an independent rerun of both the full Mem0 baseline and the official MemForest compressed keep70 result on LoCoMo sample0.

## Actions

1. Used private copied Qdrant stores, excluding `.lock*`, to avoid interfering with other agents and the live stores.
2. Reran QA for the full Mem0 store on sample0 with `run_experiments.py --technique_type mem0 --method search --top_k 30`.
3. Reran QA for the MemForest keep70 store on sample0 with the same retrieval/evaluation settings.
4. Scored both outputs with `code.evaluation.scripts.score_locomo_qa_resumable`.
5. Used DashScope OpenAI-compatible `qwen3.6-27b` for both answer generation and LLM judging.
6. Confirmed both summaries cover 152 non-category-5 LoCoMo questions.

## Result

| split | n | full acc | keep70 acc | delta acc | full B1 | keep70 B1 | delta B1 | full F1 | keep70 F1 | delta F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| overall | 152 | 82.89 | 82.24 | -0.66 | 45.99 | 44.01 | -1.98 | 53.48 | 52.01 | -1.47 |
| 1 | 32 | 78.12 | 78.12 | 0.00 | 45.63 | 40.88 | -4.75 | 51.45 | 46.30 | -5.14 |
| 2 | 37 | 86.49 | 89.19 | 2.70 | 58.27 | 54.09 | -4.18 | 64.63 | 61.45 | -3.18 |
| 3 | 13 | 92.31 | 84.62 | -7.69 | 23.63 | 23.78 | 0.15 | 31.93 | 35.29 | 3.36 |
| 4 | 70 | 81.43 | 80.00 | -1.43 | 43.81 | 43.87 | 0.06 | 52.51 | 52.73 | 0.22 |

Memory points:

| collection | full | keep70 | retention |
|---|---:|---:|---:|
| mem0 | 776 | 572 | 73.7% |
| mem0_entities | 597 | 597 | 100.0% |

## Conclusion

The independent rerun does not confirm the earlier large degradation. The keep70 compressed version is close to full Mem0 overall: accuracy is down only 0.66 percentage points, BLEU1 down 1.98 points, and F1 down 1.47 points.

This suggests the earlier large category-1 drop was probably due to artifact mismatch, a different store state, or a run-specific output/judge variance rather than a stable MemForest keep70 effect. The next useful step is to diff the previous QA output against the rerun output question by question.

Primary result note: `results/locomo_sample0_rerun_full_vs_memforest_keep70_20260708_153731.md`
