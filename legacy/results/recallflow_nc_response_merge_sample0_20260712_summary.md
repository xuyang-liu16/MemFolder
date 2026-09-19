# RecallFlow-NC response-merge sample0 comparison

Date: 2026-07-12 12:51 CST

## Config

| Item | Value |
|---|---|
| Dataset | LoCoMo `dataset/locomo10.json` |
| Sample | `sample0` only |
| Source store | `locomo_baseline_qwen36_strictjson_full10_v4_sample0_qa_snapshot` |
| Method | `recallflow_nc_response_merge` |
| keep ratios | `0.7`, `0.5` |
| cluster_ratio | `0.05` |
| tau | `0.1` fixed |
| delta | `1e-12` |
| max_probes_per_node | `3` |
| seed | `0` |
| QA | Mem0 search, `top_k=30`, `filter=False`, `graph=False` |
| Answer/Judge/Merge model | DashScope `qwen3.6-27b` |
| Embedding | DashScope `text-embedding-v4`, dim `1024` |

This run used the response-space merge version described in the runbook, not the older prune-only NC variant.

## Compression

| Method | sample0 before | sample0 after | deleted/merged | probes | clusters | objective | store size |
|---|---:|---:|---:|---:|---:|---:|---:|
| NC response-merge keep70 | 733 | 513 | 220 | 1270 | 36 | 505704.700567 | 13 MB |
| NC response-merge keep50 | 733 | 366 | 367 | 1270 | 36 | 3051730.025198 | 11 MB |

Both compressed stores also contain 43 inherited sample1 residual points from the source snapshot. They were not touched because compression targeted sample0 only.

Leakage audit in both diagnostics:

```json
{
  "compression_reads_qa": false,
  "compression_reads_gold": false,
  "compression_reads_evidence": false,
  "probes_conditioned_on_memory_nodes": true
}
```

## QA Results

Official-style Mem0 search completed `199/199` QA for both runs. Official `evals.py` skipped category 5, leaving `152` judged items.

| Method | n | Acc | BLEU1 | F1 |
|---|---:|---:|---:|---:|
| Full Mem0 | 152 | 75.0% | 42.6% | 52.0% |
| MemForest keep70 | 152 | 75.0% | 41.6% | 48.3% |
| MemForest keep50 | 152 | 71.1% | 41.1% | 47.6% |
| Old NC prune-only keep70 | 152 | 75.0% | 43.4% | 50.1% |
| Old NC prune-only keep50 | 152 | 69.1% | 38.2% | 44.9% |
| New NC response-merge keep70 | 152 | 76.3% | 42.9% | 49.1% |
| New NC response-merge keep50 | 152 | 72.4% | 40.2% | 47.4% |

## Per-Category Results

| Method | Split | n | Acc | BLEU1 | F1 |
|---|---|---:|---:|---:|---:|
| New NC response-merge keep70 | cat 1 | 32 | 59.4% | 38.8% | 41.7% |
| New NC response-merge keep70 | cat 2 | 37 | 91.9% | 52.2% | 63.8% |
| New NC response-merge keep70 | cat 3 | 13 | 76.9% | 25.8% | 26.4% |
| New NC response-merge keep70 | cat 4 | 70 | 75.7% | 43.0% | 48.9% |
| New NC response-merge keep50 | cat 1 | 32 | 43.8% | 33.3% | 35.3% |
| New NC response-merge keep50 | cat 2 | 37 | 86.5% | 49.3% | 61.1% |
| New NC response-merge keep50 | cat 3 | 13 | 76.9% | 22.8% | 25.6% |
| New NC response-merge keep50 | cat 4 | 70 | 77.1% | 41.9% | 49.7% |

## Interpretation

- At keep70, response-merge is the strongest by LLM-judge accuracy: `76.3%`, compared with Full Mem0/MemForest/old NC prune-only at `75.0%`.
- At keep70, response-merge trades off lexical metrics: it is below old NC prune-only on F1 (`49.1%` vs `50.1%`) but above MemForest keep70 on F1 (`49.1%` vs `48.3%`).
- At keep50, response-merge substantially improves over old NC prune-only: `72.4%` vs `69.1%` accuracy and `47.4%` vs `44.9%` F1.
- At keep50, response-merge slightly beats MemForest on accuracy (`72.4%` vs `71.1%`) but trails MemForest on BLEU1/F1 (`40.2/47.4` vs `41.1/47.6`).
- The new method reduces the quality cliff from keep70 to keep50 compared with old NC prune-only, but keep50 still loses clear quality relative to keep70.

## Outputs

| Artifact | Path |
|---|---|
| keep70 diagnostics | `results/recallflow_nc_response_merge_keep70_20260712_codex_respmerge_keep70_diagnostics.jsonl` |
| keep50 diagnostics | `results/recallflow_nc_response_merge_keep50_20260712_codex_respmerge_keep50_diagnostics.jsonl` |
| keep70 compressed store | `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/locomo_sample0_recallflow_nc_response_merge_keep70_20260712_codex_respmerge_keep70_qa` |
| keep50 compressed store | `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/locomo_sample0_recallflow_nc_response_merge_keep50_20260712_codex_respmerge_keep50_qa` |
| keep70 QA | `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample0_recallflow_nc_response_merge_keep70_20260712_codex_respmerge_keep70/locomo_sample0_recallflow_nc_response_merge_keep70_20260712_codex_respmerge_keep70_qa_mem0_results_top_30_filter_False_graph_False.json` |
| keep50 QA | `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample0_recallflow_nc_response_merge_keep50_20260712_codex_respmerge_keep50/locomo_sample0_recallflow_nc_response_merge_keep50_20260712_codex_respmerge_keep50_qa_mem0_results_top_30_filter_False_graph_False.json` |
| keep70 eval | `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample0_recallflow_nc_response_merge_keep70_20260712_codex_respmerge_keep70/evaluation_metrics.json` |
| keep50 eval | `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample0_recallflow_nc_response_merge_keep50_20260712_codex_respmerge_keep50/evaluation_metrics.json` |

## Notes

- `evals.py` printed the same SentenceTransformer/HF cache warning seen in earlier runs. It did not block LLM judge, BLEU1, or token F1 generation.
- The current worktree contains uncommitted implementation files for the response-space method. These results are tied to the local code state at run time.
