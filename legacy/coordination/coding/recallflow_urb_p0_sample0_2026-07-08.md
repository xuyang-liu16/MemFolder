# RecallFlow-URB P0 sample0 run log

Date: 2026-07-08

Scope:
- Ran the RecallFlow-URB P0 diagnostics on LoCoMo sample0 Mem0 memories.
- Used the sample0 QA snapshot store, not the original Qdrant store being modified by other agents.
- Did not read LoCoMo QA, gold answer, or evidence fields.

Inputs:
- Qdrant snapshot: `/mnt/disk1/memory-compression-v2/external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/locomo_baseline_qwen36_strictjson_full10_v4_sample0_qa_snapshot`
- Exported nodes: `external/rf_inputs/locomo_sample0_mem0_nodes.jsonl`
- Exported node count: 733
- Node embedding dimension: 1024
- LoCoMo sample users found: `Caroline_0`, `Melanie_0`

Run:
- Embedding backend: DashScope OpenAI-compatible embeddings
- Embedding model: `text-embedding-v4`
- Embedding dim: 1024
- URB basis version: `urb_v0`
- URB basis hash: `71d9d97df3ba0fd32b191f730f79e9e73e4a49547fe083a9405582d9c9534ea0`
- Budget ratio: 0.5
- Budget: 366
- Tau: 0.1
- Seed: 0

Outputs:
- Summary JSONL: `results/recallflow_urb_p0_locomo_sample0.jsonl`
- Diagnostics dir: `external/rf_outputs/diagnostics/locomo_0`
- URB centroid cache: `external/cache/urb/urb_v0_text-embedding-v4_1024.npy`
- URB centroid cache metadata: `external/cache/urb/urb_v0_text-embedding-v4_1024.meta.json`

Results:

| Method | Nodes before | Budget | Nodes after | Representatives | Exceptions |
| --- | ---: | ---: | ---: | ---: | ---: |
| `embedding_kcenter` | 733 | 366 | 366 | 366 | 0 |
| `recallflow_urb_prune_only` | 733 | 366 | 366 | 366 | 0 |
| `recallflow_urb_full` | 733 | 366 | 497 | 366 | 131 |

Validation:
- `code/tests_run/test_urb_smoke.py`: 4 passed.
- `code/tests_run/test_compression_smoke.py`: 18 passed.
- Export sanity check: 733 rows, 1024-d embeddings, no forbidden QA/gold/evidence fields.
- Detailed diagnostics leakage audit:
  - `compression_reads_qa=false`
  - `compression_reads_gold=false`
  - `compression_reads_evidence=false`
  - `basis_is_fixed=true`
  - `basis_conditioned_on_sample=false`

Notes:
- `recallflow_urb_full` retains the representative budget plus exception nodes. The final retained count of 497 is expected under the current P0 semantics because 131 nodes exceeded the fixed `tau=0.1` residual threshold.
- Detailed diagnostics currently record raw response, mass, residual, assignment, and exception information. They do not yet include summarized coverage metrics such as `coverage_min` or `coverage_mean`.
