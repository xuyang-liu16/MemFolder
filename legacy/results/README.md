# Results — RecallFlow v0

This folder stores shareable small-scale outputs produced during v0
development. v0 outputs only dry-run compression diagnostics; QA / evidence
metrics come in v1.

## Latest Result — LoCoMo sample1 five-run comparison

**Date:** 2026-07-12  
**Task:** LoCoMo sample1, Full context vs MemForest vs RecallFlow NC, Mem0 search QA, category 5 skipped by official `evals.py`  
**Result card:** [`locomo_sample1_five_run_comparison_20260712.md`](locomo_sample1_five_run_comparison_20260712.md)

| Method | Nodes after | Eval n | Acc | BLEU1 | F1 |
|---|---:|---:|---:|---:|---:|
| Full context | 561 | 81 | 82.7% | 50.2% | 59.9% |
| MemForest keep70 | 393 | 81 | 79.0% | 49.1% | 57.7% |
| MemForest keep50 | 281 | 81 | 75.3% | 48.3% | 55.8% |
| **RecallFlow NC keep70** | **393** | **81** | **81.5%** | **47.9%** | **56.5%** |
| RecallFlow NC keep50 | 280 | 81 | 74.1% | 42.9% | 52.6% |

Key takeaway: Full context is still the sample1 upper bound. At the same keep70 retained-node budget, RecallFlow NC improves LLM-judge accuracy over MemForest (`81.5%` vs `79.0%`) but trails MemForest on BLEU1/F1. At keep50, RecallFlow NC is below MemForest across headline metrics.

Earlier sample0 response-merge comparison:

| Method | sample0 nodes | Acc | BLEU1 | F1 |
|---|---:|---:|---:|---:|
| Full Mem0 | 733 | 75.0% | 42.6% | 52.0% |
| MemForest keep70 | 529 | 75.0% | 41.6% | 48.3% |
| MemForest keep50 | 374 | 71.1% | 41.1% | 47.6% |
| Old NC prune-only keep70 | 513 | 75.0% | 43.4% | 50.1% |
| Old NC prune-only keep50 | 366 | 69.1% | 38.2% | 44.9% |
| **New NC response-merge keep70** | **513** | **76.3%** | **42.9%** | **49.1%** |
| **New NC response-merge keep50** | **366** | **72.4%** | **40.2%** | **47.4%** |

Key takeaway: response-merge improves the previous NC prune-only method, especially at keep50, and has the best sample0 LLM-judge accuracy at keep70. At keep50 it beats MemForest on accuracy but is slightly lower on BLEU1/F1.

## Files

| File | What it contains |
|---|---|
| `locomo_v0_dryrun.jsonl` | 24 rows = 8 methods × 3 budgets (0.25 / 0.5 / 0.75), LoCoMo fixture. |
| `memforest_sample0_keep70_2026-07-08.md` | LoCoMo sample0 MemForest keep70 result card. |
| `recallflow_nc_response_merge_sample0_20260712_summary.md` | LoCoMo sample0 response-merge keep70/keep50 compression and QA result card. |
| `locomo_sample1_five_run_comparison_20260712.md` | LoCoMo sample1 five-run comparison: Full context, MemForest keep70/keep50, RecallFlow NC keep70/keep50. |
| `recallflow_nc_response_merge_*_diagnostics.jsonl` | Small sample0 compression diagnostics for response-merge runs; raw stores and QA dumps stay under `external/` and are not committed. |
| `recallflow_urb_random_node_probe_response_2026-07-09.md` | Random 15-node inspection of RecallFlow-URB 10-dimensional response distributions and metadata. |

## Latest Insight (2026-07-09)

The random node probe-response inspection suggests that URB dimensions are useful as soft signals but too diffuse to serve as hard node-level labels. Most random nodes have top-1 response values around 13%-17%, while a few nodes show sharper alignment, such as the transition-year node with `time=30.2%`.

Implication for the next method iteration:

```text
Use URB responses at the cell/cluster level.
Allocate compression budget by estimated response-preservation loss.
Avoid hand-written node-level role routing rules.
```

See `recallflow_urb_random_node_probe_response_2026-07-09.md`.

## How to regenerate

```bash
rm -f results/locomo_v0_dryrun.jsonl
for ratio in 0.25 0.5 0.75; do
  for method in no_compression random recency embedding_kcenter \
                similarity_pruning similarity_merging \
                recallflow_prune_only recallflow_full; do
    python3 -m code.evaluation.scripts.run_recallflow_locomo \
      --input code/evaluation/adapters/fixtures/locomo_fixture.jsonl \
      --method $method --budget-ratio $ratio --seed 0 \
      --output results/locomo_v0_dryrun.jsonl
  done
done
python3 -m code.evaluation.analysis.summarize_run \
  --input results/locomo_v0_dryrun.jsonl --format markdown
```

## Latest Snapshot (seed=0, LoCoMo fixture)

| method | budget | avg_caps | avg_retained | avg_archived |
|---|---|---:|---:|---:|
| no_compression | 0.25–0.75 | 0.0 | 12.0 | 0.0 |
| random | 0.25 / 0.50 / 0.75 | 0.0 | 3.0 / 6.0 / 9.0 | 9.0 / 6.0 / 3.0 |
| recency | 0.25 / 0.50 / 0.75 | 0.0 | 3.0 / 6.0 / 9.0 | 9.0 / 6.0 / 3.0 |
| embedding_kcenter | 0.25 / 0.50 / 0.75 | 0.0 | 3.0 / 6.0 / 9.0 | 9.0 / 6.0 / 3.0 |
| similarity_pruning | 0.25 / 0.50 / 0.75 | 0.0 | 3.0 / 6.0 / 9.0 | 9.0 / 6.0 / 3.0 |
| similarity_merging | 0.25 / 0.50 / 0.75 | 0.0 | 3.0 / 6.0 / 9.0 | 9.0 / 6.0 / 3.0 |
| recallflow_prune_only | 0.25 / 0.50 / 0.75 | 0.0 | 3.0 / 6.0 / 9.0 | 9.0 / 6.0 / 3.0 |
| **recallflow_full** | **0.25 / 0.50 / 0.75** | **3.0 / 6.0 / 9.0** | **6.0 / 7.0 / 11.0** | **6.0 / 5.0 / 1.0** |

## Interpretation Notes

- All methods respect the budget, except `no_compression` (upper bound).
- `recallflow_full` deviates from the others in that its `retained`
  counts include both representatives and exceptions, so they can exceed
  budget. This is by design: §5.3 of the implementation guide routes
  "rare evidence" into the exception set; we do *not* hard-cap exceptions
  in v0 (the ablation is reported as a diagnostic field, see §11 of the
  implementation guide).
- `qa_score` and `evidence_recall_at_k` are reported as 0.0 in v0; the
  retrieval round-trip proxy lands in v1.
- Dry-run seeds: `seed=0` only. Multi-seed sweeps are tracked in
  `experiments/` once we move off the fixture.
