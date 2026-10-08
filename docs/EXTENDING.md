# Adding a component

[Documentation](README.md) · [简体中文](zh-CN/EXTENDING.md)

MemFolder loads components from configuration. You can add a dataset, compression stage, text writer, framework adapter, reader, metric, or observer as a Python module or an installed package.

## Choose the interface

| Task | Component role | Main output |
| --- | --- | --- |
| Load a new benchmark | `data_loader` | `DatasetSample` values from `samples()` |
| Read an existing memory store | `memory_loader` | A `LoadedLibrary` from `load()` |
| Select representative records | `anchor_selector` | An `AnchorSelection` |
| Implement a complete grouping method | `planner` | An `ActionPlan` |
| Encode group text | `text_writer` | A `TextWriteResult` |
| Save a framework's native format | `native_writer` | Saved files and their references |
| Generate or score answers | `answerer` or `metric` | Predictions or metric results |
| Analyze recorded events | `observer` | Report files |

Built-in components use these same interfaces. The public types are described in [Data types and interfaces](CONTRACTS.md).

## Try an installed plugin

The repository includes a small benchmark plugin with its own package configuration:

```bash
python -m pip install -e .
python -m pip install -e examples/plugins/new_benchmark
python -m memfolder.benchmarks --config examples/plugins/new_benchmark/config.json --output-dir build/newbench-import-001
```

It loads two synthetic conversations with three history events and two questions. The output directory contains `memory.jsonl`, `evaluation.jsonl`, and `report.json`. This example demonstrates the data-loader interface; real benchmark scoring uses the corresponding evaluator.

## Implement a factory

A factory accepts parameters and a `BuildContext`, then returns a component. Both the factory and component expose a matching `PluginSpec` with the plugin ID, role, and API version. A small selector factory looks like this:

```python
from memfolder.core import ContractError, PluginSpec

SPEC = PluginSpec(plugin_id="lab.selector", role="anchor_selector", api_version=1)

def build(parameters, *, context):
    if set(parameters) - {"newest_first"}:
        raise ContractError("Supported parameter: newest_first")
    return MySelector(newest_first=parameters.get("newest_first", True))

build.spec = SPEC
```

Implement `MySelector.select(request, target, context)` and set `MySelector.spec = SPEC`. The complete [recency selector](../examples/plugins/recency/recency_plugin.py) shows parameter validation, protected-record handling, and the return value.

Use `context.path(value)` for file paths so relative paths resolve from the configuration directory. Keep model and database setup in the selected component's execution lifecycle. Loaders declare `source_paths` or an `input_fingerprint` so experiment verification can identify their inputs.

## Reference the factory

During development, use an importable module and factory name:

```json
{"plugin": "my_selector:build", "parameters": {"newest_first": true}}
```

For an installed package, declare an entry point in its `pyproject.toml`:

```toml
[project.entry-points."memfolder.plugins"]
"lab.selector" = "my_selector:build"
```

After installing that package, use `"plugin": "lab.selector"` in the configuration. For a RecordFolder anchor selector:

```json
{
  "planner": {
    "plugin": "recordfolder",
    "parameters": {"anchors": {"plugin": "lab.selector"}}
  },
  "operator": {"plugin": "recordfolder-operator"}
}
```

The registry checks roles, API versions, and declared capabilities when assembling the components.

## Add a dataset or storage format

A benchmark loader assigns a stable sample identity, loads its history or initial memory, and attaches its evaluation cases. Memory, questions, and reference answers occupy separate fields. Select an existing evaluator or supply a metric for the new task. Files already containing serialized `DatasetSample` objects can use `dataset-jsonl`.

A memory loader reads an existing store. Reuse an existing reader when only the record fields differ and implement `FormatAdapter.decode()`. Add a reader when the file or database transport changes. The [loading guide](LOADING.md) explains owner mappings, vectors, time, and coverage reports.

Match memory and evaluation by dataset, sample, split, and version. Preserve native IDs, source fields, and available model/time information. Close open resources when iteration ends or fails.

## Check a contribution

Add a small fixture and check its expected records, sample identities, source references, and result types. Include empty input, duplicate IDs, invalid parameters, and resource cleanup cases relevant to the component. For memory or evaluation loaders, check that questions and reference labels reach their intended stages.

Examples cover [anchor selection](../examples/plugins/recency), [native output](../examples/plugins/native_writer), and [answering, scoring, and reports](../examples/plugins/experiment_components). `tools/check_plugin_installation.py` checks separately installed plugin packages. `python tools/check_contracts.py` runs the repository's component and data-validation tests.
