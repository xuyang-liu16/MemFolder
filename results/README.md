# results/

Public-shareable small-scale experiment results and analyses.

## Layout

```
results/
├── README.md                       # This file
├── recallflow_v0_locomo.jsonl      # RecallFlow v0 LoCoMo results
├── recallflow_v0_memeye.jsonl      # RecallFlow v0 MemEye results (later)
├── budget_accuracy/                # Plots and tables
└── bad_cases/                      # bad case tables and analyses
```

## Conventions

- Every result row must record: `sample_id`, `dataset`, `method`, `budget_ratio`, `metric`, `model`, `date`
- Every experiment config (seed, model id, probe setup, budget) must be reproducible from `code/configs/` or the script arguments
- Bad case tables must include: `sample_id`, `method`, `compression_policy`, `error_type`, `missing_evidence`, `notes`
- Large raw outputs (full LoCoMo QA dumps, M3-Agent inference logs, large memory graphs) stay local — not committed

## Status

No public results yet. v0 first run is the next P0 task after implementation.