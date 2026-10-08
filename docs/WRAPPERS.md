# Framework integration

[Documentation](README.md) · [简体中文](zh-CN/WRAPPERS.md)

A wrapper saves compressed records in a memory framework's format. It updates graph connections, refreshes text embeddings, writes the output, and records how each output node relates to its sources.

## Choose an output format

| Framework | Available outputs | Setup details |
| --- | --- | --- |
| Mem0 | Point JSON or a new local Qdrant collection | The Qdrant writer uses one unnamed dense-vector space |
| MemOS | NaiveTextMemory lists or TreeTextMemory nodes and edges | Loading into a live instance uses a caller-configured empty memory object |
| M3 | VideoGraph JSON, a caller-supplied VideoGraph object, or native pickle | Native search requires matching text-vector dimensions and the graph class |

Mem0 named and sparse vector slots can be retained in unchanged JSON records; editing those slots calls for an appropriate codec and writer. Mem0 history databases, entity graphs, and additional search indexes have separate storage requirements.

MemOS activation and parameter files are preserved as referenced components. A cube with additional cross-component references needs a codec that handles those references. The pinned tree loader accepts the exported graph, while live Neo4j deployment requires its own environment check. Source versions are listed in [WRAPPER_SOURCES.json](WRAPPER_SOURCES.json).

## Try the local example

```bash
python examples/wrapper_demo.py
```

The example uses concatenation and synthetic vectors to demonstrate export, compression, writing, and readback. For a model-backed experiment, choose a wrapper in the [experiment template](EXPERIMENTS.md).

This configuration writes a new Mem0 Qdrant collection. Place it under `compression.wrapper` in an experiment:

```json
{
  "plugin": "mem0-wrapper",
  "parameters": {
    "output_dir": "runs/memory-001",
    "codec": {
      "plugin": "mem0-codec",
      "parameters": {
        "space": {"provider": "your-provider", "model": "your-model", "revision": "your-revision", "dimension": 1536}
      }
    },
    "writer": {"plugin": "qdrant-writer", "parameters": {"collection": "mem0"}},
    "embedding_provider": {
      "plugin": "content-embeddings",
      "parameters": {
        "space": {"provider": "your-provider", "model": "your-model", "revision": "your-revision", "dimension": 1536}
      }
    }
  }
}
```

Install `.[qdrant]` and provide an `embeddings` service with `encode(texts)`. Use the same model, revision, and vector dimension for stored text and retrieval queries. The full experiment runner places each sample's output inside that run's directory; a direct wrapper call uses its configured `output_dir`.

## Understand the write process

1. `export` exposes the input memory as a `Snapshot`.
2. Compression produces a plan and new records.
3. `project` updates graph edges to reflect the retained and merged records.
4. The embedding provider computes vectors for text that needs them.
5. The codec converts the final snapshot into the framework's fields.
6. The writer saves files and a completion manifest.

The default graph projection reconnects merged-node edges to the output node and removes edges incident to dropped nodes. Edges created with the same endpoints and relation are combined using the selected `max`, `sum`, or `mean` rule. Compression-created self-loops are removed, while existing self-loops are retained.

Text embeddings are refreshed according to the declared space. A pooled feature used for grouping has a different purpose from an embedding of the stored text. `preserve_native` with `source_slot` allows reuse when the caller can identify the source vector model.

## Read the saved memory

| Function | Result |
| --- | --- |
| `open_qdrant_view(out)` | Qdrant client and collection name; close the client after use |
| `load_memos_view(out, configured_empty_memory)` | Load files into the supplied MemOS memory instance |
| `load_m3_view(out, VideoGraph)` | Reconstruct an instance of the supplied M3 graph class |

These functions are exported by `memfolder.wrappers`. MemOS tree output should specify `backend: "tree_text"`, including when the final graph has zero edges. For native M3 pickle output, select `m3-pickle-writer` and supply the class through the `m3.graph_type` service.

## Inspect and verify the output

Each write uses a new directory. It contains `source.snapshot.json`, `snapshot.json`, `native.package.json`, the framework's files, ID mappings, source references, and file hashes. A completed write has `manifest.json`; a failed write leaves `failure.json` for diagnosis. Retry a failed write in a new directory.

`verify_materialization(out, artifact=...)` checks the bundle's files, hashes, snapshots, and ID mappings. The experiment-level `python -m memfolder verify RUN_DIRECTORY` also verifies referenced native outputs. Editing output files changes the hashes and requires a new result record.

## Customize integration

| Component | Responsibility |
| --- | --- |
| `graph_projector` | Update graph edges after compression |
| `embedding_provider` | Compute embeddings for stored content |
| `native_codec` | Map records to framework fields |
| `native_writer` | Save those fields in the target format |
| `asset_copier` | Copy and verify referenced files |

Select `framework-wrapper` to assemble custom components, or implement the wrapper interface for a framework-specific lifecycle. The [native writer example](../examples/plugins/native_writer) adds a file that maps output records to their sources. [Extensions](EXTENDING.md) covers installation and registration.
