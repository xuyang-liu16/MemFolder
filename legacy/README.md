# Legacy — the pre-G1S exploration

Everything in this directory belongs to the RecallFlow / MemForest phase of the
project (roughly 2026-07-07 to 2026-07-16). It is **frozen**: nothing here is
imported by, or needed to run, the method in [`../g1s`](../g1s).

It is kept because the result cards are the record of what was actually
measured, and because the method notes explain why the project moved on.

## What is here

| path | what it is |
|---|---|
| `README_recallflow_2026-07.md` | the old repository front page (RecallFlow era) |
| `PROJECT_STATUS.md` | the status board as of 2026-07-09 |
| `docs/` | RecallFlow method notes, the URB protocol and runbook, the experiment plan, research notes, the multi-agent workflow guide |
| `code/` | the RecallFlow v0 skeleton: `compression/` (capsule, coreset, probes, URB, response), `baselines/`, `evaluation/` adapters and scripts, smoke tests |
| `results/` | LoCoMo result cards and metric JSON for the Mem0 / MemForest / RecallFlow-NC / RecallFlow-URB arms, samples 0–9 |
| `coordination/` | the coding agent's working logs for the sample-0 runs |

## How it relates to G1S

RecallFlow compressed on *retrieval response* — probe a node, keep what changes
the response. MemForest was the partition-and-merge baseline it was measured
against. The headline result of that phase
(`results/locomo_sample0_to_9_weighted_mixed_20260716.md`, n=1540 weighted,
category 5 excluded) was that RecallFlow-NC keep50 reached 0.7136 LLM accuracy
against MemForest keep50 at 0.7065, with Full Context at 0.7208 as the upper
bound — an improvement, but a small one, and response fingerprints turned out to
be expensive to compute and not sharp enough per node to use as hard labels.

G1S keeps the partition-and-merge frame and replaces the grouping criterion:
instead of response similarity or embedding similarity, memories are grouped
along entity-grounded temporal chains. That is the method in `../g1s`.

## Caveats

- The code here was a skeleton, not a finished implementation; parts of it were
  never wired up (the URB runner never flowed back into `code/`).
- Paths inside these files refer to the old repository layout, before this
  directory existed. They are not rewritten — treat them as historical text.
- The numbers in the result cards were produced with the endpoints and models of
  that period and are not comparable to the G1S runs without re-measuring.

The state of `main` immediately before the G1S refactor is also available as the
`archive/pre-g1s` branch.
