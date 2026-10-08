# Data types and interfaces

[Documentation](README.md) · [简体中文](zh-CN/CONTRACTS.md)

The types in [`src/memfolder/core`](../src/memfolder/core) describe the data exchanged between loading, compression, retrieval, and evaluation. They use immutable Python values and a versioned JSON representation. This page explains the types most useful when implementing a component.

## Memory and samples

| Type | Meaning |
| --- | --- |
| `MemoryRecord` | One memory unit, with content, source references, time, and optional embeddings |
| `ContentPart` | Text or a reference to an image, audio, video, or other asset |
| `ScopeRef` | Dataset, sample, and partition identifying a record's grouping boundary |
| `OriginRef` | Original source ID and revision within a scope |
| `Snapshot` | Records, graph edges, and assets at one stage of compression |
| `MemoryInput` | A sample's history or an existing snapshot |
| `DatasetSample` | Memory together with its evaluation cases |
| `QuestionSet` | Questions and public options supplied to the reader |
| `EvaluationSet` | Reference answers, evidence, and scoring metadata supplied to the evaluator |

A partition can represent a conversation, memory cube, video clip, or another region defined by the loader. Plans normally operate within a scope. Sample-wide merging requires an explicit plan boundary and runtime authorization; dataset and sample identity remain fixed.

`eligible` selects records for compression. `RetentionPolicy` separately controls dropping, merging, and rewriting. Outputs inherit the relevant protection from their members. Source references let an output record be traced back to the records that contributed to it.

## Plans and results

The planner receives a `PlanningRequest` containing the current snapshot, features, budgets, execution mode, and optional method state. It returns an `ActionPlan`:

| Action | Input records | Output records | Purpose |
| --- | --- | --- | --- |
| Keep | 1 | 1 | Retain the record as stored |
| Drop | 1 | 0 | Remove a record |
| Merge | At least 2 | 1 | Consolidate several records |
| Rewrite | 1 | 1 | Change a record's text |

Each target record appears in exactly one action. Records outside the target set remain in the snapshot. The plan records the input snapshot fingerprint so the executor can validate the version it applies to.

The operator produces an `ActionOutcome` for each action and an `OperatorResult` for the plan. Outcomes identify success, a fallback with a reason, or failure. A fallback still follows the action's output count and source requirements. A change in membership or output count requires a revised plan.

`input_view` selects original or current-round members. This supports ContextFolder's use of original group content and iterative methods that work from the current merged text. After validation, the wrapper updates the graph and refreshes embeddings before the next round or final write.

## Embeddings, features, and time

An `Embedding` belongs to actual stored content and declares its provider, model, revision, dimension, and metric. Rewritten content needs a refreshed embedding. A `FeatureBatch` belongs to a snapshot and can carry grouping vectors, pooled mass, entities, or cluster labels.

`TimePoint.clock` identifies the time scale. Event ranges describe when events occurred; `available_at` and `expires_at` describe visibility. Merging uses the compatible intersection of member visibility intervals. Separate output units are needed when those intervals have no overlap.

## Budgets

`BudgetRequest` describes the target amount retained. It accepts either an absolute `limit` or a `ratio`, along with an allocation and rounding rule.

| Field | Options and meaning |
| --- | --- |
| `unit` | `nodes`, `characters`, `tokens`, `words`, `bytes`, `edges`, or a namespaced unit |
| `allocation` | Per `scope`, `global`, or caller-supplied `group` |
| `rounding` | `half_even`, `half_up`, `floor`, or `ceil` |
| `minimum` | Lower bound for each allocated target |
| `enforcement` | `exact`, `at_most`, or `advisory` |
| `reference` | Resolve from the `initial` or `current` snapshot |
| `measurement_id` | Identity of the tokenizer or other measurement procedure |

Node counts use eligible records. Character counts use Python Unicode code points. Other units require explicit per-record measurements. The compression driver currently enforces node budgets and accepts other units as advisory; strict text limits require an executor that measures and enforces them.

Group allocations form a complete, disjoint partition of eligible records. Rounding occurs within each group, which matters for methods such as MemForest's cluster-level ceilings.

## Serialization and validation

Core objects are immutable dataclasses. `FrozenMap` stores recursively immutable JSON values. `dumps()` and `loads()` use a schema envelope containing `schema_id`, `schema_version`, and `data`.

```python
from memfolder.core import ScopeRef, dumps, loads

scope = ScopeRef(dataset_id="demo", sample_id="sample-1", partition_id="history")
encoded = dumps(scope)
restored = loads(encoded, expected=ScopeRef)
assert restored == scope
```

Constructors and validators check types, IDs, dimensions, graph references, time, source coverage, and protections. `json_schema(Type)` exports structural schemas; use `loads` or `from_data` when importing external values to apply the semantic checks as well.

Component-specific fields belong in namespaced `extensions`. New serialized types register a schema with `@record("lab.type")`. `MemoryDelta` describes versioned updates to records and edges; `AlgorithmState` stores a method's JSON state and asset references. Runtime services such as clients and models are supplied separately.

## Source reference

| Module | Types and helpers |
| --- | --- |
| `memory.py`, `data.py` | Memory, samples, questions, and reference labels |
| `features.py`, `candidates.py` | Features and optional grouping stages |
| `plans.py`, `budgets.py` | Actions, outcomes, and retained-amount targets |
| `evaluation.py`, `observation.py` | Predictions, scores, events, and case views |
| `plugins.py`, `values.py` | Component interfaces and serialization |

Run `python tools/check_contracts.py` to check the implementation. See [Extensions](EXTENDING.md) for a complete plugin example.
