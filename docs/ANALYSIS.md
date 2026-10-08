# Inspecting a run

[Documentation](README.md) · [简体中文](zh-CN/ANALYSIS.md)

Use captured events to follow a source record through grouping, text compression, retrieval, and answering. `FileRunReader` supports queries by original record, compression action, or question, and can export the related events and files.

## Enable capture

Add this to an experiment configuration:

```json
{
  "capture": {"profile": "cases", "text_policy": "omit", "vector_policy": "omit"},
  "observers": [{"plugin": "event-report-observer", "required": false}]
}
```

`summary` saves events; `cases` and `full` also save public data views for inspection. Filters can select samples, scopes, stages, and diagnostic schemas. Choose a text/vector policy according to the data needed for the analysis. `text_policy: "redacted"` requires a configured redactor.

Capture policies apply to the public analysis files. The run's private source snapshots, predictions, and evaluation files still contain the data needed to execute and verify the experiment. Review those files separately before sharing a run directory.

## Inspect the offline example

After running the [offline example](EXPERIMENTS.md), export its first question:

```bash
python -m memfolder case build/experiments/offline-demo --dataset-id locomo --sample-id demo --question-id demo:0 --output build/cases/demo-question
```

The command prints the capture status and counts of related events and files. It writes `case.json` and the referenced files into a new export directory. Use `--action-id` to inspect a compression action or `--source-id` to inspect an original record.

The Python API exposes the same queries:

```python
from memfolder import FileRunReader

reader = FileRunReader("build/experiments/offline-demo")
sample = reader.sample("locomo", "demo")
case = reader.by_question(sample, "demo:0", branch="compressed")
print(case.status, len(case.events), len(case.artifacts))
```

## Follow a record through the pipeline

| Stage | Useful saved data |
| --- | --- |
| Loading and initialization | Source identities, memory records, and sample membership |
| Grouping | Anchors, assignments, candidate links, scores, and selected groups |
| Text writing | Action members, output text according to capture policy, and fallback reasons |
| ContextFolder verification | Required facts, round token counts, recovery checks, and selected round |
| Framework output | Original/final snapshots and output-node ID mapping |
| Retrieval | Hit rank, score, output ID, and original sources |
| Answering and evaluation | Question ID, context reference, prediction, and score status |

Availability depends on the capture policy and the component's diagnostic output. `complete_for_capture` means all data selected by that policy was recorded. `partial` identifies missing files or failed recording. `not_recorded` identifies a case outside the captured data.

## Compare two runs

Use original source identities to align records between runs:

```python
from memfolder import FileRunReader

left = FileRunReader("runs/experiment-a")
right = FileRunReader("runs/experiment-b")
origins = left.origins(sample_id="demo", source_id="d1")
comparison = left.compare(right, origins=origins)
```

An original identity includes its dataset, sample, scope, source ID, and revision. Generated output IDs identify records within a run. The comparison records differences in data versions, reader settings, services, prompts, and scoring protocols so you can interpret the result.

## Add an analysis report

An observer implements `open`, `on_event`, and `close`. It receives immutable events, a reader for the public analysis files, and a writer for its reports. Reports can summarize group sizes, fact recovery, or question-level outcomes. Components that change grouping or text implement the planner or operator interface instead.

An optional observer's failure is recorded while the run continues. Setting `required: true` makes successful reporting a requirement for a completed experiment. The [experiment component example](../examples/plugins/experiment_components) includes an observer, answerer, and metric.

For compression-only Python calls, `DiagnosticCollector` collects component diagnostics and can write JSONL. The complete experiment adds sample, round, question, and original/compressed branch information. See [Extensions](EXTENDING.md) for component registration.
