# RecallFlow Implementation

Implementation of the **RecallFlow** memory compression algorithm. Public shared code.

## Layout

```
code/
├── README.md                       # This file
├── src/
│   ├── compression/                # RecallFlow method modules
│   ├── benchmarks/                 # LoCoMo / MemEye adapters (TBD)
│   └── utils/                      # Shared utilities (TBD)
├── baselines/                      # Sanity baselines (random / recency / embedding k-center / similarity prune/merge)
├── evaluation/                     # Adapters, scripts, analysis
│   ├── adapters/
│   ├── scripts/
│   └── analysis/
└── configs/                        # YAML / JSON experiment configs
```

## Recommended Module Layout (from `docs/recallflow_implementation_guide.md`)

```
code/src/compression/
├── schema.py          # MemoryNode / MemoryCapsule dataclasses
├── probes.py          # Probe query generation
├── response.py        # Response matrix and fingerprint
├── coreset.py         # Response-space coreset selection
├── capsule.py         # Residual routing and capsule builder
└── recallflow.py      # Main entry: fit_compress / update
```

## Status

v0 not yet implemented. See `docs/recallflow_implementation_guide.md` for the minimum closed loop.

## Read First

1. `docs/recallflow_implementation_guide.md`
2. `docs/experiment_plan.md`
3. `docs/research_notes.md`

## Local Process Notes

Local coding process logs go to `coordination/coding/work_log_coding_{cursor,claudecode,codex}.md`. Public-shareable small results go to `results/`.