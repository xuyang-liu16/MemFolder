# Running experiments

[Documentation](README.md) · [简体中文](zh-CN/EXPERIMENTS.md)

An experiment loads memory, compresses it, retrieves relevant records for each question, generates answers, and scores them. One JSON configuration selects the data, compression method, model services, and output directory.

## Run the offline example

From the repository root, install the package with Python 3.11 or newer:

```bash
python -m pip install -e .
python -m memfolder run examples/experiments/offline-demo.json
python -m memfolder verify build/experiments/offline-demo
```

The example uses four synthetic conversation turns, random grouping, and text concatenation. Its answerer returns the retrieved context. It runs locally with the Python standard library and marks its scores as `test_only`. Use it to check installation and explore the output files.

The `run` command prints the run ID, sample count, compression status, evaluation status, and output directory. A successful `verify` prints `"status": "verified"` after checking the saved files and their hashes.

## Configure RecordFolder or ContextFolder

Install the optional dependencies used by the method templates:

```bash
python -m pip install -e ".[algorithms,contextfolder,evaluation]"
```

Start with [recordfolder-template.json](../examples/experiments/recordfolder-template.json) or [contextfolder-template.json](../examples/experiments/contextfolder-template.json). Each template includes data loading, compression, answering, and evaluation. Update these fields before running:

| Field | What to supply |
| --- | --- |
| `dataset.parameters.path` | Path to your dataset; the supplied value selects the tiny example |
| `services.*.parameters` | Provider URL, model name, and model revision for chat and entity extraction |
| `services.embeddings.parameters.provider.parameters` | Embedding provider URL, model, and revision |
| `compression.features` → `semantic-encoder.parameters.space` | The same embedding model identity and its vector dimension |
| `output_dir` | A new directory for this run |

Replace `REPLACE_*` and `https://api.example.invalid/v1` with your provider settings. Set `MEMFOLDER_PROVIDER_KEY` in the shell that starts the experiment:

```powershell
$env:MEMFOLDER_PROVIDER_KEY = "YOUR_API_KEY"
```

On Bash-compatible shells:

```bash
export MEMFOLDER_PROVIDER_KEY="YOUR_API_KEY"
```

Then run the configured template:

```bash
python -m memfolder run examples/experiments/recordfolder-template.json
python -m memfolder run examples/experiments/contextfolder-template.json
```

Relative paths resolve from the configuration file's directory. For example, `../../build/experiments/recordfolder-001` in `examples/experiments/` points to the repository's `build/experiments/recordfolder-001`.

ContextFolder uses `contextfolder-qa-prompt` when answering from its encoded memory. Keep that prompt selection when adapting the template. For an existing store, configure a `bank-initializer` as described in [Loading memories](LOADING.md).

## Understand the configuration

| Section | Purpose |
| --- | --- |
| `dataset` | Load conversation histories, questions, and scoring labels |
| `initializer` | Build memory from history or select an existing memory store |
| `compression` | Choose the grouping method, text writer, features, and output framework |
| `reader` | Retrieve records, build context, and generate answers |
| `evaluator` | Score answers and retrieved evidence |
| `services` | Configure chat, embedding, and token-counting services |
| `run` | Set the seed, compression budget, execution mode, and original-memory comparison |
| `capture`, `observers`, `redactor` | Select the diagnostic data to save and analyze |
| `output_dir` | Choose where the run is saved |

Configure `reader` and `evaluator` together for question answering. A compression-only experiment can omit both. The compression stages receive the memory; the reader receives questions; the evaluator receives reference answers and evidence labels.

This example retains half of the eligible records within each scope and also evaluates the original memory:

```json
{
  "run": {
    "seed": 7,
    "evaluate_source": true,
    "budgets": [{"unit": "nodes", "ratio": 0.5}]
  }
}
```

`ratio` is the fraction retained. A node budget controls record count. Text length is measured separately with the configured tokenizer. Text ToMe and MST MemForest use `run.mode: "repeat"` to alternate merging and embedding updates; see [Compression methods](COMPRESSION.md).

## Compare methods and seeds

```bash
python -m memfolder matrix examples/experiments/offline-matrix.json
```

The supplied matrix compares RandomMerge and RandomPrune with seeds 7 and 11, producing four runs. In a matrix configuration, `axes` selects configuration fields to vary, `seeds` lists random seeds, and `max_runs` limits the total number of combinations. Each run has its own output directory and manifest.

## Read the output

| File or directory | Contents |
| --- | --- |
| `sources.json` | Input files and fingerprints |
| `run.manifest.json` | Component versions, run status, and references to saved files |
| `result.json` | Per-sample compression statistics and evaluation results |
| `completion.json` | References used to verify a completed run |
| Per-sample directories | Original and final memory, compression rounds, native-format output, predictions, and scores |
| `trace/` | Captured events and their index, when capture is enabled |
| Observer reports | Reports produced by configured analysis components |

Compression statistics include record, character, and edge counts. A tokenizer adds token counts with its measurement identity. Service usage records calls and available billing information. Timings include recording and observer work performed during the run.

With `evaluate_source: true`, the original and compressed memories use the same reader and evaluator. Their results are stored as separate branches. [Inspecting a run](ANALYSIS.md) explains how to follow an individual question or source record.

## Reuse or retry a run

To reuse a completed run with matching inputs and configuration:

```bash
python -m memfolder run examples/experiments/offline-demo.json --resume
```

Resume verifies the recorded input, configuration, component, and runtime identities before reuse. Changes require a new output directory. A failed attempt retains the files written so far for inspection; retry it with a new directory after fixing the cause. `--resume` reuses completed runs, while partial attempts remain available for diagnosis.

The CLI reports the exception type on failure. Calling `assemble_experiment(config, base_path=...).run()` from Python exposes the original exception for debugging. User-supplied services provide a `cache_identity` for resume checks; the caller manages their lifetime.

## Choose what to validate

The offline example checks execution and file integrity. To measure answer quality, supply the target dataset, memory store, model settings, and the benchmark's [evaluation protocol](BENCHMARKS.md). Paper comparisons also depend on the method variant, record budget, prompt, seed, and embedding model. The tables in [Paper results](PAPER_RESULTS.md) report the manuscript experiments.

For development checks:

```bash
python tools/fetch_test_sources.py
python tools/check_contracts.py
```

The source fetcher downloads pinned test inputs into `build/` and checks their hashes. Integration checks use the dependencies and source archives available in the environment. CI runs the test suite and offline examples on Python 3.11 and 3.12.
