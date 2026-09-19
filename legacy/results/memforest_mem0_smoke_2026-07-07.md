# MemForest / Mem0 Smoke — 2026-07-07

## Config

| Field | Value |
|---|---|
| Chat / judge model | `qwen3.6-plus` via relay |
| Embedding model | `text-embedding-v4` via DashScope Bailian |
| Embedding dim | `1024` |
| Environment | `/root/miniconda/envs/memforest` |
| Raw output | `external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/mem0_direct_smoke.jsonl` |

## Results

| Dataset | Smoke type | Add | Search | Answer |
|---|---|---:|---:|---|
| LoCoMo | direct Mem0 add/search/answer | ok | ok | `May 7, 2023.` |
| LongMemEval | direct Mem0 add/search/answer | ok | ok | `You graduated with a degree in Business Administration.` |
| PersonaMem | direct Mem0 add/search/answer | ok | ok | Pacific Islander music + modern digital melodies |

## MemForest Compression Check

`MemForest.py --dry-run` on a 4-node local smoke store succeeded:

| Sample | Nodes before | Clusters | Expected after | Actual after |
|---:|---:|---:|---:|---:|
| 0 | 4 | 1 | 2 | 2 |

## Notes

- The official MemForest `run_experiments.py` LoCoMo path was not completed end-to-end because even a one-session run was too slow for a quick smoke. A direct Mem0 driver was used to validate API, embedding, Qdrant, retrieval, and answer generation.
- LongMemEval and PersonaMem raw datasets are not in the native MemForest `conversation` / `qa` schema. Tiny converted files were generated only for adapter smoke preparation; the recorded successful results here use direct synthetic memory snippets derived from each dataset's first example.
- `spaCy` and `fastembed` are missing in the env, so Mem0 runs without entity/BM25 extras. This should be fixed before reporting formal Mem0 baseline numbers.
