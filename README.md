# MemFolder

Composable agent-memory compression with RecordFolder, ContextFolder and
baseline planners/operators. Native memory adapters support Mem0, MemOS and M3;
benchmark loaders support LoCoMo, LongMemEval, PersonaMem and M3.

Requires Python 3.11 or newer. Install from the repository root:

```bash
python -m pip install ".[algorithms,contextfolder,evaluation]"
```

Application entry points:

```bash
python -m memfolder --help
python -m memfolder.loading --help
python -m memfolder.benchmarks --help
```

Supply dataset paths, memory mappings, component configuration and model
services through your application. `memfolder.assembly.assemble` composes
compression stages; `memfolder.experiment.assemble_experiment` assembles a
complete experiment. Public contracts are exported by `memfolder.core`.
Plugins can register through the `memfolder.plugins` entry-point group.

Configure model endpoints and model IDs explicitly. The HTTP service reads
credentials from the environment variable selected by `api_key_env`.
Flow observation and case analysis are exposed through the public interfaces
in `memfolder.observation` and `memfolder.analysis`.

Third-party attribution and licensing information: [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES).
