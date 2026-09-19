# LoCoMo Sample2 Full-Grid Results

Date: 2026-07-14

Evaluation stack:
- Dataset: `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/dataset/locomo10.json`
- Sample: `sample2`
- Chat / judge model: DashScope compatible `qwen3.6-27b`
- Embedding model: DashScope compatible `text-embedding-v4`
- Retrieval: Mem0 search, `top_k=30`
- Official `evals.py` skips category 5, so judged `n=152`.

| Method | Compression | Judged n | Acc/LLM | BLEU-1 | F1 |
|---|---:|---:|---:|---:|---:|
| Full Context | 928 | 152 | 84.21% | 54.16% | 64.72% |
| MemForest Keep70 | 928 -> 672 | 152 | 82.89% | 54.25% | 63.41% |
| MemForest Keep50 | 928 -> 477 | 152 | 81.58% | 52.14% | 60.59% |
| MemForest Keep30 | 928 -> 298 | 152 | 78.95% | 47.20% | 55.88% |
| RecallFlow-NC Keep70 | 928 -> 650 | 152 | 80.92% | 50.61% | 59.69% |
| RecallFlow-NC Keep50 | 928 -> 464 | 152 | 80.26% | 50.14% | 59.36% |
| RecallFlow-NC Keep30 | 928 -> 278 | 152 | 80.26% | 49.28% | 57.73% |

Notes:
- Full Context QA was initially partial; reran the resumable QA to `193/193` and then reran eval.
- MemForest compression API failures observed under high parallelism:
  - Keep70: 3 cluster-level merge failures.
  - Keep50: 6 cluster-level merge failures.
  - Keep30: 0 cluster-level merge failures.
- RecallFlow-NC compression used 1564 probes for Keep70/50/30.
- During several evals, SentenceTransformer emitted a CUDA OOM warning. The reported table uses LLM judge, BLEU-1, and token F1, and the eval jobs completed successfully.
