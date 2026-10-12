---
name: memfolder-exp
description: Configure, run, compare, and inspect MemFolder memory-compression experiments using its loaders, plugins and CLI. Use for offline checks, existing memory banks, benchmark evaluation and method comparisons.
---

# MemFolder experiments

Locate the checkout containing `pyproject.toml`, `src/memfolder/__main__.py` and
`examples/experiments/`. Read its [README](../../README.md) and inspect the actual
configuration before running. Paths below are relative to that checkout; an
installed skill may live elsewhere. If the user requests this repository and no
checkout is available, clone `https://github.com/xuyang-liu16/MemFolder.git` into
a fresh directory.

Preserve the user's dataset, bank, method, services, output location and existing
authorization. Reuse available inputs. Prepare a pilot when no run size was
specified; the README example uses LoCoMo `conv-26` and node retention `0.5`.
That conversation has 199 questions, so estimate calls from the loaded questions
and compression stages. Resolve missing choices before dependent model calls.
An authorized experiment does not need another confirmation for its routine
steps; setup or inspection alone does not authorize paid inference.

## Prepare the run

- Establish whether this is an offline wiring check, a new comparison, or
  reproduction of a particular paper result.
- Record benchmark version, sample IDs, bank-to-sample/owner mapping and hashes.
  `history-initializer` creates one node per turn; framework-generated memory
  banks require an explicit loader and `bank-initializer` mapping.
- Resolve model/revision, embedding space, tokenizer, retrieval budget, retained
  node ratio, seed, and fresh output directory. Credentials stay in environment
  variables. Paths resolve from the configuration's directory.
- Read [experiment-config.md](references/experiment-config.md) for bank import,
  dense retrieval, benchmark time semantics and model-backed scoring.
- Use [tome.md](references/tome.md) for temporal ToMe, and
  [llmlingua2.md](references/llmlingua2.md) for its two context-compression variants.

Recipes under `examples/recipes/` configure compression components. Full run
configs are under `examples/experiments/`; a recipe alone is not a run config.
Replace each required component and configure each feature name once.

## Check installation and execute

Use Python 3.11+ and install the extras needed by the selected components.
`algorithms`, `contextfolder`, `qdrant`, `evaluation`, and `llmlingua2` are separate
extras. Classifier weights are loaded lazily; a model-backed run may need them.

```bash
python -m pip install -e .
python -m memfolder --help
python -m memfolder run examples/experiments/offline-demo.json
python -m memfolder verify build/experiments/offline-demo
```

The offline example uses synthetic history and test-only answers/metrics.
For a prepared model-backed config:

```bash
python -m memfolder run /path/to/experiment.json
python -m memfolder verify /path/to/output
python -m memfolder run /path/to/experiment.json --resume
```

`--resume` validates and reuses a completed run; it does not continue partial
samples. Preserve failed runs and retry in a fresh directory. There are no
`--dry-run`, `--limit` or `--max-requests` options; select sample IDs in the config.
For sweeps, use the structure in `examples/experiments/offline-matrix.json`.

## Preserve the comparison protocol

All built-in ordinary summaries, final QA and final judges use
[`memforest.shared.v1`](../../docs/PROMPT_PROTOCOL.md). Keep
`memforest-qa-prompt` and `memforest-judge` across every arm, including the
uncompressed control, LLMLingua-2 and BabelTele. The judge accepts JSON
`CORRECT`/`WRONG`. `qa-prompt` and `contextfolder-qa-prompt` are identical aliases;
`chat-judge` is an alias of the same judge. Do not append a decoder legend or
enable AGPR in benchmark QA. A distinct explicit research protocol needs its
own identity and must not be mixed into this comparison.

ContextFolder's fact extraction, encoding, blind recovery and repair are
compression-internal stages. They use source memory, not benchmark QA or gold.
LLMLingua-2 and BabelTele retain their own compression mechanisms.
Keep the same source, retrieval, models and scoring coverage across arms.
F1 and deterministic choice accuracy remain separately identified metrics;
the shared MemForest judge differs from native benchmark scoring protocols.

## Match method and input contracts

- `run.budgets[].ratio` is the fraction of eligible nodes retained. A 70% node
  reduction is `0.3`; report realized counts after scope rounding.
- The main RecordFolder template needs semantic and entity features plus parsed
  event times. PersonaMem turn order and M3 clip visibility require explicit
  order/time adapters; replacing only `dataset` is insufficient.
- Temporal ToMe needs `repeat` mode and initial vectors bound to current text in
  one declared cosine space. `semantic-encoder` supplies planning features,
  not initial node embeddings. Read the ToMe reference before substituting it.
- MemForest scope-capacity and per-cluster ceilings have different budgets.
  The latter uses the Python API's `resolve_memforest_budget`; the full run
  schema has no dynamic budget-resolver field.
- ContextFolder's default text target is `0.8`, with three writer rounds and
  slack `1.15`. These differ from driver round limits. Its empty/invalid fact
  fallback currently lacks a length bound and blind verification. Inspect
  fallback reasons, required-fact losses and measured saved lengths.
- For a context pass after Record compression, use the current-record rewrite
  recipes and `examples/record_then_context.py`. Reset stage state/features
  and node budget; do not regroup original source members.
- Preserve LongMemEval query-time visibility, PersonaMem history prefixes and
  M3 clip cutoffs/protected nodes. Text-chat answering does not implement the
  full M3 multimodal controller or StreamMeCo's temporal reader.

## Inspect and report

Inspect `result.json`, `run.manifest.json`, `sources.json` and per-sample
snapshots, predictions, evaluation and baseline evaluation. Export a case with:

```bash
python -m memfolder case /path/to/output \
  --dataset-id DATASET --sample-id SAMPLE --question-id QUESTION \
  --output /path/to/new-case
```

Report completed/expected samples and questions, metric identity/coverage,
original/final nodes and tokens, tokenizer, fallbacks, service failures and
artifact paths. The CLI reports an exception type; inspect the failed stage or
use the Python API for detail before retrying. Stop expansion on unresolved
authentication, quota, schema or input-contract failures. Call counts are not
a billing total, and trace redaction does not redact all private run files.

`tools/check_contracts.py` reports failures and skips separately. Eight historical
parity tests and the standalone method/wrapper source checkers still need author
archives outside the checkout. `tools/fetch_test_sources.py` verifies pinned
public references but does not supply those private archives. Report this scope
accurately; a successful wiring check does not establish paper-score reproduction.
