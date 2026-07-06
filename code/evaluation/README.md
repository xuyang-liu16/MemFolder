# Evaluation

Adapter layer, experiment scripts, and analysis tooling.

## Layout

```
evaluation/
├── README.md                # This file
├── adapters/                # LoCoMo / Mem0 / MemEye data → MemoryNode adapters
├── scripts/                 # Experiment entry points
└── analysis/                # Budget-accuracy plots, bad-case tables, summaries
```

## Adapter Contract

Each adapter converts a raw benchmark dataset into a stream of `MemoryNode` objects that match the schema in `code/src/compression/schema.py`.

## Experiment Script Contract

Each script must accept:

- `--input` — adapter output (jsonl of MemoryNodes)
- `--budget-ratio` — retained memory fraction (e.g. 0.25 / 0.5 / 0.75)
- `--method` — compression method id
- `--output` — result jsonl path
- `--config` — yaml/json config (optional)

And must record for every result row:

`sample_id`, `dataset`, `method`, `budget_ratio`, `num_nodes_before`, `num_capsules_after`, `num_probes`, `compression_latency_sec`, `retrieval_latency_sec`, `qa_score`, `evidence_recall_at_k`, `model`, `date`.

## Status

Not yet implemented.