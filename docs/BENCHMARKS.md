# Benchmarks and evaluation

[Documentation](README.md) · [简体中文](zh-CN/BENCHMARKS.md)

The benchmark loader reads histories, questions, and reference answers. The initializer builds or selects memory. After compression, the reader retrieves memory and answers each question; the evaluator scores the answers using the selected protocol.

## Select a dataset and metric

| Dataset | Loader | Input | Evaluation |
| --- | --- | --- | --- |
| LoCoMo | `locomo-dataset` | Conversation sessions, dates, speakers, and QA annotations | `locomo-f1`, optionally `evidence-recall` |
| LongMemEval | `longmemeval-dataset` | Session histories, dates, query times, and answers | `memforest-judge` (shared MemForest protocol) |
| PersonaMem v1 | `personamem-dataset` | Question CSV and context JSONL | `personamem-accuracy` |
| M3 robot | `m3-dataset`, `variant: "robot"` | Annotations and a video-to-memory-loader mapping | `memforest-judge` (shared MemForest protocol) |
| M3 web | `m3-dataset`, `variant: "web"` | Annotations and a video-to-memory-loader mapping | `memforest-judge` (shared MemForest protocol) |

Copy the relevant component from [dataset-components.json](../examples/experiments/dataset-components.json) into your experiment's `dataset` section. Set the file paths and sample selection for your data.

For example:

```json
{
  "dataset": {
    "plugin": "locomo-dataset",
    "parameters": {"path": "data/locomo.json", "utc_offset_minutes": 0}
  },
  "evaluator": {
    "plugin": "metric-evaluator",
    "parameters": {"metrics": [{"plugin": "locomo-f1"}, {"plugin": "evidence-recall"}]}
  }
}
```

Use the source timezone for `utc_offset_minutes`. Add the reader, initializer, compression method, and services as shown in [Experiments](EXPERIMENTS.md).

## Preserve each task's input window

**LoCoMo** keeps session order, speaker identities, dialog IDs, and dates. Evidence annotations refer to source dialog IDs. The default `evidence_policy: "strict"` validates each reference. With `preserve_unknown`, unresolved evidence labels are saved for inspection and answer scoring remains available. Evidence recall returns `not_run` for those cases because the full reference set is unresolved.

**LongMemEval** keeps session IDs aligned with dates and histories. The query time controls the available memory. Question type and answerability labels are used by the evaluator.

**PersonaMem v1** initializes memory from the context prefix ending at `end_index`. Shared context files use a byte-offset index for loading. Public answer options go to the reader; the correct choice goes to the evaluator. PersonaMem v2 requires its own loader and scoring protocol.

**M3 robot** limits memory to nodes available before the annotated `before_clip` cutoff. **M3 web** uses the supplied video's full graph. Configure `memory_loaders` explicitly for each selected video, and provide a graph containing the required cutoff. Both variants use open-ended question answering.

## Configure the shared MemForest judge

All built-in LLM answerers and judges use the shared MemForest protocol,
regardless of benchmark or compression method. Configure the model under
services.chat and services.judge and use:

```json
{
  "plugin": "metric-evaluator",
  "parameters": {
    "metrics": [{"plugin": "memforest-judge", "parameters": {"service": "judge"}}]
  }
}
```

The compatibility name chat-judge selects exactly the same implementation.
It requests JSON and accepts only {"label":"CORRECT"} or {"label":"WRONG"}.
The metric version records the shared template SHA-256. This is the MemForest
automated judge using dataset ground truth; it is not the official LongMemEval
or M3 scoring protocol. Built-in official-judge and benchmark-specific judge
prompt selectors have been removed. A distinct research scoring protocol must
be registered as an explicit external plugin.

See [Shared prompt protocol](PROMPT_PROTOCOL.md) for merge, QA, exceptions,
template provenance, and migration. Deterministic benchmark metrics below
remain available and have their own metric identities.

## Read scores consistently

- `locomo-f1` follows the pinned category, multiple-answer, abstention, and stemming rules. It uses the optional NLTK dependency. `token-f1` is a separate metric with simpler token matching.
- `personamem-accuracy` follows the release's option-set and `final_answer` parsing. `choice-accuracy` uses stricter label/text matching.
- `evidence-recall` scores retrieved source references. Its status identifies cases with unresolved evidence.
- A score's metric version, status, and sample selection are part of the result. Include them when comparing runs.

For an existing memory store, match each sample through `bank-initializer`; see [Loading memories](LOADING.md). For several datasets in one experiment, `composite-dataset` combines loaders and `protocol-evaluator` selects the evaluator by protocol. [Paper results](PAPER_RESULTS.md) contains the manuscript's reported scores.
