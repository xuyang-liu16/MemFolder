---
name: coding
description: Coding Agent for the memory-compression (RecallFlow) project. Implements RecallFlow v0 (probe generator, response matrix, coreset selector, capsule builder) plus LoCoMo / MemEye adapters, baseline wrappers, and smoke tests. Use when implementing or modifying any code under code/, src/, evaluation adapters, or baseline wrappers.
---

# Coding Agent — memory-compression

You are the **Coding Agent** for the `memory-compression` project (method: **RecallFlow**, target ICLR 2027).

## Goal

Implement RecallFlow v0 in `code/src/compression/`:

```
schema → probes → response matrix → response fingerprint → coreset → capsule → evaluator
```

Plus evaluation adapters, baseline wrappers, and at least one smoke test per module.

## Required Reading on Session Start

1. `AGENTS.md`
2. `README.md`
3. `coordination/README.md`
4. This skill (`SKILL.md`)
5. `coordination/coding/work_log_coding_{your-tool}.md`
6. `coordination/coding/work_res_coding_{your-tool}.md`
7. `code/README.md`
8. `docs/recallflow_implementation_guide.md` (formulas + code skeletons)
9. `docs/experiment_plan.md`
10. `docs/recallflow_method.md` (for context on ablations)

## Implementation Order (v0 minimum)

1. `code/src/compression/schema.py` — `MemoryNode`, `ProbeQuery`, `MemoryCapsule` dataclasses.
2. `code/src/compression/probes.py` — entity / temporal / event probe generator (no test leakage).
3. `code/src/compression/response.py` — `compute_response_fingerprints(query_embs, node_embs, tau=0.1)`.
4. `code/src/compression/coreset.py` — farthest-first k-center with mass tiebreak.
5. `code/src/compression/capsule.py` — residual routing + capsule builder.
6. `code/src/compression/recallflow.py` — main `recallflow_compress(nodes, probes, embed_fn, budget)`.
7. `code/evaluation/adapters/` — LoCoMo / MemEye → MemoryNode adapters.
8. `code/baselines/` — random, recency, embedding k-center, similarity prune/merge.
9. Smoke test for each module.

## Hard Rules

- Probe queries must NEVER come from the test-set questions or gold answers (oracle leakage).
- v0 does not require LLM summarization. Use `simple_capsule_summary` first.
- `tau=0.1` is fixed for v0; do not treat as a tunable knob.
- Do not commit `paper/`, `repo/`, `external/`, `src/`, datasets, models, API keys, or full external baseline repos.
- Each script must specify input, output, config, and a minimal run command.
- After every code change, run at least one smoke test or unit test.

## Output Style

- Functions ≤ 50 lines when possible. Use dataclasses for data containers.
- Avoid premature optimization. Get a runnable v0 first.
- Cite the formula section of `recallflow_implementation_guide.md` in the docstring of each function that implements one.

---

## Experience Notes (append-only, dated, signed by tool)

> Append distilled lessons here before context overflow. One bullet = one lesson.

<!-- Experience Notes start -->

<!-- Experience Notes end -->