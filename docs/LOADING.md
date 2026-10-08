# Loading memories

[Documentation](README.md) · [简体中文](zh-CN/LOADING.md)

Use `memfolder.loading` to import an existing Mem0, MemOS, or M3 memory store. It returns a `LoadedLibrary` containing per-sample memory and an import report. Each sample has a `Snapshot`: the records, edges, and assets available for compression.

For conversation datasets that still need memory construction, start with [Benchmarks](BENCHMARKS.md) and select an initializer in the [experiment configuration](EXPERIMENTS.md).

## Select the input format

| Input | Python function | Dependency |
| --- | --- | --- |
| Mem0 record export or Qdrant point JSON/JSONL | `load_mem0(path)` | Standard library |
| Archived MemoryNode JSONL | `load_mem0_legacy_nodes(path)` | Standard library |
| Local Qdrant directory | `load_mem0_qdrant(path, collection=...)` | `qdrant-client` |
| Offline Qdrant `storage.sqlite` | `load_mem0_sqlite(path)` | Standard library |
| Existing Qdrant client | `load_mem0_client(client, collection=...)` | Caller-provided client |
| MemOS text or tree JSON | `load_memos(path)` | Standard library |
| MemOS cube directory | `load_memos_cube(path)` | Standard library |
| M3 VideoGraph JSON or pickle | `load_m3(path)` | NumPy for pickles containing NumPy arrays |
| Previously saved MemFolder library | `load_library(path)` | Standard library |

The local Qdrant reader opens a temporary copy of the source store. Mem0's `history.db` contains operation history; use the collection's `storage.sqlite` for current records. PostgreSQL, Neo4j, and server-side snapshots require an export in a supported format or a custom reader.

## Import from the command line

For a local Qdrant store, install the optional dependency:

```bash
python -m pip install -e ".[qdrant]"
python -m memfolder.loading mem0-qdrant "path/to/store" --collection mem0 --options my-options.json --output-dir imported-memory-001
```

`my-options.json` describes the selected sample. For example, the following selects two participants from one conversation:

```json
{
  "dataset_id": "locomo",
  "split": "test",
  "sample_id": "conversation-1",
  "selectors": {"user_id": ["Alice_1", "Bob_1"]},
  "naive_timezone": "UTC"
}
```

Use the actual owner IDs and source timezone. `sample_id` groups the selected owners into one benchmark sample; their original partitions remain available to the compression method.

Other formats use the same output convention:

```bash
python -m memfolder.loading memos-cube "path/to/cube" --output-dir imported-cube-001
python -m memfolder.loading m3 "path/to/video.pkl" --output-dir imported-video-001
```

Each import creates a new directory with `library.json` and `report.json`. The report contains source hashes, record and edge counts, filtering counts, and parsing issues. A local format example is available through `python examples/loading_demo.py`.

## Import from Python

```python
from memfolder.loading import LoadOptions, load_mem0, save_library

library = load_mem0(
    "export.json",
    options=LoadOptions(
        dataset_id="my-dataset",
        sample_id="sample-1",
        namespace="store-1",
    ),
)

for memory in library.inputs:
    snapshot = memory.initial_snapshot
    print(memory.sample.sample_id, len(snapshot.records))

save_library(library, "imported-library.json")
```

Declare `sample_id` only after selecting the records that belong to that sample. To import a file containing several samples, supply `sample_map` with exact owner-to-sample mappings. Mem0 defaults to owner identities, MemOS to cubes, and M3 to videos. M3 text records are further partitioned by clip; media and identity nodes are protected.

## Use an imported store in an experiment

A `bank-initializer` maps each benchmark sample ID to a memory loader. For a dataset with sample ID `demo`, the initializer can be configured as follows:

```json
{
  "initializer": {
    "plugin": "bank-initializer",
    "parameters": {
      "loaders": {
        "demo": {
          "plugin": "mem0-sqlite",
          "parameters": {
            "path": "data/collection/mem0/storage.sqlite",
            "options": {"dataset_id": "locomo", "sample_id": "demo"}
          }
        }
      }
    }
  }
}
```

The loader must return one selected memory sample with the matching dataset and sample IDs. Add `selectors` when the source store contains other conversations. The experiment then pairs that memory with the dataset's questions and scoring labels.

## Declare vectors and time correctly

Original fields and vectors are preserved in `record.native`. To use a native vector as a declared embedding, supply its slot in `LoadOptions.embedding_spaces` with the actual provider, model, revision, and dimension. Vectors with an unknown model remain available as native data. `native_vector_sets(record)` exposes all preserved vector slots, including multiple and sparse vectors.

An imported model declaration records the caller's knowledge of the source. A freshly computed content embedding provides the current text-to-vector association needed after rewriting. [Framework integration](WRAPPERS.md) explains embedding refresh before retrieval.

| Time field or option | Meaning |
| --- | --- |
| `naive_timezone` | Timezone for source dates that omit one |
| `numeric_timestamp_clock` | Unit and clock of numeric timestamps |
| `visibility_field` | Source field used for availability time |
| Record event ranges | When the described events occurred |
| M3 clip clock | Clip order within the named video |

Unparsed timestamps remain in the native fields and produce a report issue. Set `order_by` to `source`, `native_id`, or `time_id`; the time-based option requires comparable parsed times.

## Check import completeness

Inspect `report.sources` before running compression. `declared_complete` means the source declared complete coverage, `partial` marks an accepted partial export, and `unknown` means the supplied file's coverage could not be established. `records_filtered` and `edges_filtered` account for explicit selection.

For SQLite, use an offline store with an empty WAL/journal. The reader checks a temporary copy and preserves persisted vector values. The Qdrant SDK path can normalize vectors or convert precision, so comparisons should use the same import path. Split backups can supply `metadata_path` explicitly to the Qdrant loader.

The loader validates IDs, vector dimensions, graph references, and sample ownership. The default limits are one million records and 2 GiB per file, configurable through `LoadOptions`. The selected records occupy memory while the `Snapshot` is built.

Keep MemOS component files alongside their cube when they are referenced as assets. M3 media paths retain their source values and are resolved by the component that consumes the media. The M3 pickle reader supports recognized graph and value types; other formats can be exported to JSON or handled by a format adapter.

## Add a format

A reader obtains a `SourceDocument` from a file or database. A `FormatAdapter` decodes it into records and edges. The importer converts those values into MemFolder memory objects. See [Extensions](EXTENDING.md) for plugin configuration and [LOADING_SOURCES.json](LOADING_SOURCES.json) for the source versions used to implement the built-in formats.
