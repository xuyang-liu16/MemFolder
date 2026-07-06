# Baselines

Sanity baselines for comparison with RecallFlow v0.

## Required Baselines

| Baseline | Role |
|---|---|
| `no_compression` | Upper bound |
| `random` | Sanity check |
| `recency` / `FIFO` | Near-recency bias check |
| `embedding_kcenter` | Probes whether response-fingerprint coreset beats pure embedding similarity |
| `similarity_pruning` | StreamMeCo-like proxy |
| `similarity_merging` | MemForest-like proxy |
| `recallflow_prune_only` | RecallFlow without capsules (representatives only) |
| `recallflow_full` | RecallFlow representatives + capsule + exception |

## Most Critical Comparison

> **RecallFlow full vs embedding kcenter**  
> If we win, response-fingerprint coreset is doing real work beyond semantic similarity.

## Status

Not yet implemented.