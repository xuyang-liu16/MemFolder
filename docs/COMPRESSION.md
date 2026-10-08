# Compression methods

[Documentation](README.md) · [简体中文](zh-CN/COMPRESSION.md)

MemFolder reduces two costs of using long-term memory: searching many records and reading long retrieved text. RecordFolder groups related records into fewer units. ContextFolder encodes each group more compactly and checks whether its important facts can be recovered.

## RecordFolder: reduce the number of records

RecordFolder selects representative records, called anchors, and uses semantic similarity, shared entities, and event order to form groups. The configured text writer then consolidates each group.

The implementation follows these steps:

1. Select anchors using local density and diversity.
2. Assign records to their nearest anchor.
3. Find candidate links among earlier records and combine entity and semantic similarity.
4. Keep links that improve on the anchor assignment, then match them into temporal chains.
5. Assign each chain to an anchor group and write the group's output record.

The [RecordFolder experiment template](../examples/experiments/recordfolder-template.json) configures the required features and services. Its grouping stages can also be replaced individually:

| Configuration slot | Default plugin | Role |
| --- | --- | --- |
| `anchors` | `density-peaks` | Select representative records |
| `assignment` | `nearest-anchor-assignment` | Form initial groups |
| `candidates` | `temporal-candidates` | Propose earlier-record links |
| `scorer` | `fused-affinity` | Combine entity and semantic similarity |
| `gate` | `anchor-gate` | Compare links with the anchor assignment |
| `matcher` | `chain-matcher` | Choose compatible links |
| `hosting` | `chain-hosting` | Assign chains to groups |

Defaults include a candidate window of 50 records, top-8 candidate selection, density neighbor count 5, and variance floor `1e-6`. RecordFolder's earlier implementation name is G1S.

## ContextFolder: shorten the text in each group

ContextFolder uses the RecordFolder groups and also rewrites singleton text records. For each group, it extracts facts, decides which facts to preserve, generates a compact encoding, and asks a verifier to answer questions from that encoding. The answers guide revisions.

| Writer slot | Default plugin | Role |
| --- | --- | --- |
| `fact_planner` | `fact-planner` | Extract facts and verification questions |
| `triage` | `fact-triage` | Select required facts by importance and inferability |
| `compiler` | `context-compiler` | Write the compact encoding |
| `verifier` | `blind-verifier` | Test recovery from the encoding |
| `feedback` | `repair-feedback` | Describe missing facts and length issues |
| `selector` | `shortest-clean-round` | Choose among generated encodings |

The default writer targets 80% of the group's source token count, allows three rounds, and uses a budget slack of 1.15. These settings guide text generation. The saved `final_tokens`, `required_lost`, and fallback reason describe the actual outcome. The current execution engine enforces node budgets; enforcing a strict global token cap requires a text-budget executor.

Verification questions are generated from the group's memory. Benchmark questions and reference answers are reserved for the later evaluation stage. The [ContextFolder experiment template](../examples/experiments/contextfolder-template.json) also selects the answer prompt for reading encoded memory. ContextFolder's earlier implementation name is V12.

## Choose a method recipe

A recipe selects a planner, which decides record membership, and an operator, which carries out the selected actions. The [recipes directory](../examples/recipes) contains compression configurations; full experiment configurations live in [examples/experiments](../examples/experiments).

| Method | Recipe | Behavior |
| --- | --- | --- |
| RecordFolder | [recordfolder.json](../examples/recipes/recordfolder.json) | Group records using anchors, entities, semantics, and time |
| ContextFolder | [contextfolder.json](../examples/recipes/contextfolder.json) | Use those groups with verified text encoding |
| RandomPrune | [random-prune.json](../examples/recipes/random-prune.json) | Retain a seeded sample of records |
| RandomMerge | [random-merge.json](../examples/recipes/random-merge.json) | Form random groups and merge their text |
| KmeansPrune | [kmeans-prune.json](../examples/recipes/kmeans-prune.json) | Keep a real record near each cluster center |
| KmeansMerge | [kmeans-merge.json](../examples/recipes/kmeans-merge.json) | Merge each cluster with the chosen writer |
| DART | [random-anchor](../examples/recipes/dart-random_anchor_farthest.json), [medoid](../examples/recipes/dart-medoid_pivot.json) | Select memories using archived DART adaptations |
| Text ToMe | [tome-text.json](../examples/recipes/tome-text.json) | Repeated bipartite matching, text merging, and re-embedding |
| M3 ToMe | [tome-m3-pooled.json](../examples/recipes/tome-m3-pooled.json) | Pool features with their accumulated mass |
| Text MemForest | [scope budget](../examples/recipes/memforest-mst-capacity.json), [cluster budgets](../examples/recipes/memforest-mst-cluster-ceil.json) | Cluster by semantics and time, then merge along tree edges |
| M3 MemForest proxy | [memforest-m3-proxy.json](../examples/recipes/memforest-m3-proxy.json) | Use the archived average-linkage approximation |
| StreamMeCo | [streammeco-official.json](../examples/recipes/streammeco-official.json) | Prune a memory graph with the pinned classification and selection rules |

Method variants have different execution settings:

- **Text ToMe and text MemForest:** set `mode` to `repeat` and provide an embedding service for rewritten text. MemForest uses the latest member event time after a merge.
- **MemForest cluster budgets:** the historical variant rounds each initial cluster's retained count upward. Use `resolve_memforest_budget()` with the matching clusterer and ratio. The scope-budget variant allocates a specified total count instead.
- **StreamMeCo:** selection uses separate class quotas for clip-level and sample-level records. Its recipe works with those quotas or a compatible external budget. This port implements graph compression; the upstream method's temporal retrieval stage requires a separate reader implementation.
- **DART and the M3 MemForest proxy:** these names identify the memory adaptations in the archived experiments. Use the exact recipe name when reporting a comparison.

## Combine grouping and text encoding

For example, this configuration uses ToMe grouping with ContextFolder encoding:

```json
{
  "planner": {"plugin": "tome"},
  "operator": {"plugin": "contextfolder-operator"}
}
```

Place it in the experiment's `compression` section along with its feature providers and wrapper. Set `run.mode` to `repeat` and configure chat, embeddings, and a tokenizer. A complete compression recipe appears in [tome-with-contextfolder.json](../examples/recipes/tome-with-contextfolder.json).

## Supply features and services

| Component | What it provides |
| --- | --- |
| `semantic-encoder` | Embeddings of the current record text |
| `chat-grounding` | Entity and relation features extracted from memory |
| `event-time-features` | Event times used by temporal grouping |
| Stored embedding or grounding providers | Previously computed features with declared identities and record mappings |
| `chat` service | Text generation and ContextFolder fact checks |
| `embeddings` service | `encode(texts)` for current memory text |
| `tokenizer` service | `count(text)` and a `measurement_id` |

Declare the embedding provider, model, revision, and dimension together. After text changes, refresh its content embedding. ToMe's pooled vectors remain method features, while retrieval uses embeddings associated with the stored text.

Event time describes when the recorded event occurred. Availability time describes when a reader may access it. Temporal methods use event times with a declared clock; the explicit `order` variants use record order where that is the intended experiment setting.

## Follow execution

```text
Memory → features → grouping plan → text writing → updated memory
                         ↑                              |
                         └──── next round, if needed ───┘

Final memory → framework output → retrieval → answering → evaluation
```

`assemble(config)` builds the compression components. `CompressionEngine.step()` executes one plan; `run()` repeats planning when required and checks the final node budget. Plans use four actions: keep, drop, merge, and rewrite. Protected records, sample boundaries, and source references are checked as actions are applied.

For a small local example:

```bash
python examples/compression_demo.py
```

It groups nine synthetic records into four records by concatenating their text. For model-backed runs, use the full [experiment templates](EXPERIMENTS.md). [Analysis](ANALYSIS.md) explains grouping diagnostics and fact-check records; [Extensions](EXTENDING.md) shows how to replace a component. Source revisions are recorded in [METHOD_PROVENANCE.json](METHOD_PROVENANCE.json).
