# Results — RecallFlow v0

This folder stores shareable small-scale outputs produced during v0
development. v0 outputs only dry-run compression diagnostics; QA / evidence
metrics come in v1.

## Files

| File | What it contains |
|---|---|
| `locomo_v0_dryrun.jsonl` | 24 rows = 8 methods × 3 budgets (0.25 / 0.5 / 0.75), LoCoMo fixture. |
| `memforest_sample0_keep70_2026-07-08.md` | LoCoMo sample0 MemForest keep70 result card. |
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
