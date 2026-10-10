# Supported configurations

[Documentation](README.md) · [简体中文](zh-CN/COMPATIBILITY.md)

An experiment combines a dataset, a memory framework, a compression method, and a reader/evaluator. Choose each according to its data and service requirements. This page summarizes the implemented components and the additional setup needed for a particular experiment.

## Compression requirements

| Method | Required input | Execution |
| --- | --- | --- |
| RecordFolder | Text, semantic vectors, entity features, and event times | Group records and consolidate text |
| ContextFolder | RecordFolder inputs, chat service, and tokenizer | Group records and verify compact encodings |
| RandomPrune / RandomMerge | Records, stable IDs, and a seed | Select records or form random groups |
| KmeansPrune / KmeansMerge | Vectors in one declared space | Select representatives or merge clusters |
| DART memory variants | Vectors, pivot settings, and a seed | Select records |
| Text ToMe | Current content-bound vectors, comparable event times (or all-ordinal order), chat and embeddings | Sequential chronological-half pair merges, repeated destinations, immediate embedding refresh |
| LLMLingua-2 context | Final current Record snapshot and an LLMLingua-2 service | One rewrite per record, default retention rate 0.55; optional official package |
| M3 pooled ToMe | Vectors and accumulated mass | Pool features according to the recipe |
| Text MemForest | Semantic features and event times | Repeated cluster/tree-based merging |
| M3 MemForest proxy | Vectors | Archived average-linkage grouping |
| StreamMeCo graph compression | M3 graph structure, vector features, and class information | Apply clip-level and sample-level selection rules |

Keep the recipe's variant name when reporting results. The [compression guide](COMPRESSION.md) explains MemForest budget variants, StreamMeCo quotas, and DART's archived memory adaptations.

## Dataset requirements

| Dataset | Information to preserve | Evaluation setup |
| --- | --- | --- |
| LoCoMo | Sessions, speakers, dialog IDs, dates | Category-aware F1 and optional evidence recall |
| LongMemEval | Sessions, dates, query time | Pinned judge prompt and configured judge model |
| PersonaMem v1 | Per-question history prefix and public choices | Option-set answer scoring |
| M3 robot/web | Video identity, graph, media references, clip visibility | Open-ended answers and pinned judge prompt |

M3's dataset loader defines the task and questions; its memory wrapper defines graph storage and retrieval. Other dataset/framework combinations can be assembled when their sample, time, graph, and modality requirements match. See [Benchmarks](BENCHMARKS.md) for scoring details.

## Framework output and retrieval

| Framework | Implemented integration | Configuration needed |
| --- | --- | --- |
| Mem0 | Point JSON, local Qdrant output, and Qdrant retrieval | One declared dense-vector space for the built-in Qdrant writer |
| MemOS | Text/tree output and loading into a configured memory instance | Cube boundaries, component assets, and backend settings |
| M3 | VideoGraph JSON/object/pickle and native graph search | Video mapping, graph class, and compatible text vectors |

The generic reader also supports lexical retrieval, dense retrieval, graph expansion, time decay, and a caller-supplied SDK search service. The answerer supplied with the templates uses text chat. Multimodal answering can be added through an answerer that consumes the available content parts.

The current runner executes offline experiments with one or repeated compression rounds. Live database transactions, continuous ingestion, and the upstream M3 multi-step controller need integrations appropriate to the target system. StreamMeCo's upstream temporal reader likewise requires a dedicated implementation. [Framework integration](WRAPPERS.md) documents the supported output formats.

## Validate the combination you use

Use the offline example to check package setup, a small real-memory sample to check loading and framework output, and the target benchmark/model configuration to measure answer quality. Compare records, source references, graph edges, vector identities, and score protocols at those stages.

The repository includes component tests, source-comparison tests, plugin installation checks, and optional storage integration checks. Their scope depends on the supplied dependencies and source archives. The [paper tables](PAPER_RESULTS.md) report the manuscript's experiments; they are the reference for those particular settings.
