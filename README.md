# MemFolder

**A modular experiment framework for agent memory compression.**

MemFolder lets researchers load an existing memory library, choose how to plan
and execute compression, adapt the output to a memory framework, and evaluate it
under an explicit retrieval and QA protocol. New methods can be added as plugins
and assembled through configuration.

This is the first development release of the refactored framework. **RecordFolder**
is the formal name of G1S; **ContextFolder** is the formal name of V12.

## Design

```text
Benchmark / existing memory library
                 |
        Loader + Initializer
                 |
         MemoryWrapper.export
                 |
       Features -> Planner -> Operator
                 |
   Graph projection + content embeddings
                 |
       MemoryWrapper.materialize
                 |
        Retriever -> QA -> Evaluator

     Trace / observers / case analysis
              observe each stage
```

- **Separate decisions from execution.** A Planner selects nodes and produces an
  action plan; an Operator executes Keep, Drop, Merge or Rewrite actions.
- **Replace small components.** Candidate generation, scoring, gating, matching,
  grouping and context writing have independent interfaces.
- **Keep experiments explicit.** Budgets, seeds, model identities, retrieval,
  prompts and scoring belong to configuration and recorded run artifacts.
- **Inspect the data flow.** Traces connect source memories, groups, actions,
  output nodes, retrieval hits and predictions for case analysis.
- **Preserve evaluation boundaries.** Benchmark answers and evidence labels are
  supplied to the Evaluator, rather than the compression pipeline or Reader.

## Implemented components

| Layer | Available implementations |
| --- | --- |
| Main methods | RecordFolder and ContextFolder |
| Baseline stages | ToMe, MemForest, DART memory adaptations, StreamMeCo graph compression, RandomMerge, RandomPrune, KMeansMerge, KMeansPrune |
| Benchmarks | LoCoMo, PersonaMem, LongMemEval, M3 robot/web |
| Memory frameworks | Mem0, MemOS, M3 |
| Experiment tools | Configuration assembly, batch matrices, source controls, artifact verification, completed-run resume and case inspection |

Method variants are explicit recipes. DART here refers to memory adaptations;
StreamMeCo includes its graph compression stage. Graph, modality, embedding and
backend requirements still determine which combinations are valid. Implemented
interfaces and tests do not establish reproduced paper scores for every combination.
See [compatibility boundaries](docs/COMPATIBILITY.md).

## Quick start

Requires **Python 3.11 or newer**. The core package has no mandatory third-party
dependencies and does not load models or open databases at import time.

```bash
git clone https://github.com/xuyang-liu16/MemFolder.git
cd MemFolder
python -m pip install -e .

python -m memfolder run examples/experiments/offline-demo.json
python -m memfolder verify build/experiments/offline-demo
python -m memfolder matrix examples/experiments/offline-matrix.json
```

The offline demo uses synthetic data, a concatenation operator and a context echo
answerer. Its scores are marked `test_only`; it requires no API key or model call.
If the output already exists, use `--resume` with the same configuration or select
a new output directory.

For vector algorithms, ContextFolder tokenization, local Qdrant and evaluation:

```bash
python -m pip install -e ".[algorithms,contextfolder,qdrant,evaluation]"
```

For real model experiments, start from the
[RecordFolder template](examples/experiments/recordfolder-template.json) or
[ContextFolder template](examples/experiments/contextfolder-template.json).
Configure data paths, output paths, provider URLs, models and embedding spaces.
Supply provider credentials through environment variables; the templates contain
placeholders. Details are in the [experiment guide](docs/EXPERIMENTS.md).

## Add a module

Implement a plugin factory with a `PluginSpec` and the appropriate interface,
then reference it directly in configuration:

```json
{
  "plugin": "my_module:build",
  "parameters": {"my_parameter": 0.5}
}
```

An independently installed package can instead register a `memfolder.plugins`
entry point. The registry checks roles, API versions and capabilities before
assembly; a new plugin does not require a method-name branch in the core Runner.

Examples:

- [New benchmark](examples/plugins/new_benchmark): a separate loader package.
- [Recency component](examples/plugins/recency): replace an anchor selector.
- [Native writer](examples/plugins/native_writer): extend framework output.
- [Experiment components](examples/plugins/experiment_components): replace an
  answerer, metric and observer.
- [ToMe + ContextFolder](examples/recipes/tome-with-contextfolder.json): compose
  record grouping with a different context writer.

See [the extension guide](docs/EXTENDING.md) for contracts and configuration.

## Repository layout

```text
src/memfolder/
  core/          Public data contracts and invariants
  loading/       Native memory library readers and adapters
  benchmarks/    Benchmark parsers and evaluation separation
  planning/      Planners and interchangeable decision components
  operators/     Pruning, merging and context writing
  wrappers/      Framework projection, encoding and materialization
  evaluation/    Retrieval, answering, prompts and metrics
  analysis/      Traces, observers and case queries
  assembly.py    Compression pipeline assembly
  experiment.py  Complete offline experiment execution
  matrix.py      Experiment matrices
examples/        Recipes, experiment configurations and external plugins
schemas/         JSON Schemas for public contracts
tests/           Contracts, methods, loading, wrappers and experiments
tools/           Validation and source verification utilities
docs/            Module guides, compatibility and provenance
```

## Development and verification

```bash
python tools/check_contracts.py
```

To exercise optional upstream-source integration checks, install the optional
dependencies, download the exact source revisions with checksum verification,
then run the same suite:

```bash
python tools/fetch_test_sources.py
python tools/check_contracts.py
```

Downloaded files and test outputs stay in ignored `build/` directories. Historical
archive characterization tests require those separate archives and explicitly
skip when they are unavailable. Model QA, full SDK lifecycle integration, live
Neo4j and multimodal inference need additional environment-specific validation.

## Documentation

Start with [experiments](docs/EXPERIMENTS.md), [compression](docs/COMPRESSION.md),
[memory loading](docs/LOADING.md), [wrappers](docs/WRAPPERS.md),
[benchmark protocols](docs/BENCHMARKS.md), [analysis](docs/ANALYSIS.md) and
[public contracts](docs/CONTRACTS.md).

## Attribution and licensing

Source revisions and adaptations are recorded in
[method provenance](docs/METHOD_PROVENANCE.json) and
[third-party notices](docs/THIRD_PARTY_NOTICES.md). The StreamMeCo MIT notice is
included in the package. A uniform distribution license for the historical source
contributions has not been finalized; this release does not relicense them.
