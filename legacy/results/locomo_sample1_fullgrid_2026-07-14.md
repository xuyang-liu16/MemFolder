# LoCoMo Sample1 Full-Grid Results

Date: 2026-07-14

Evaluation stack:
- Dataset: `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/dataset/locomo10.json`
- Sample: `sample1`
- Chat / judge model: DashScope compatible `qwen3.6-27b`
- Embedding model: DashScope compatible `text-embedding-v4`
- Retrieval: Mem0 search, `top_k=30`
- Official `evals.py` skips category 5, so judged `n=81`.

| Method | Compression | Judged n | Acc/LLM | BLEU-1 | F1 |
|---|---:|---:|---:|---:|---:|
| Full Context | 561 | 81 | 80.25% | 48.58% | 59.89% |
| MemForest Keep70 | 561 -> 403 | 81 | 79.01% | 49.48% | 58.50% |
| MemForest Keep50 | 561 -> 286 | 81 | 74.07% | 46.78% | 54.32% |
| MemForest Keep30 | 561 -> 184 | 81 | 71.60% | 46.23% | 54.43% |
| RecallFlow-NC Keep70 | 561 -> 393 | 81 | 81.48% | 48.97% | 58.16% |
| RecallFlow-NC Keep50 | 561 -> 280 | 81 | 76.54% | 45.23% | 53.45% |
| RecallFlow-NC Keep30 | 561 -> 168 | 81 | 75.31% | 44.77% | 54.19% |

Notes:
- MemForest compression completed with `api_failures=0` for Keep70/50/30.
- RecallFlow-NC compression completed with 842 probes for Keep70/50/30.
- MemForest QA initially failed because output folders were missing; after creating folders, rerun completed successfully.
