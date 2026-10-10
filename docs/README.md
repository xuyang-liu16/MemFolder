# Documentation

[English](README.md) | [简体中文](zh-CN/README.md) · [Project home](../README.md)

MemFolder compresses an agent's stored memories and evaluates how well the agent can answer questions with the compressed memory. Start with the offline example, then configure your data and model services.

## Run an experiment

| What you want to do | Read |
| --- | --- |
| Install the package, run the example, or compare configurations | [Experiments](EXPERIMENTS.md) |
| Use RecordFolder, ContextFolder, or a baseline | [Compression methods](COMPRESSION.md) |
| Configure chronological ToMe and LLMLingua-2 after Record compression | [ToMe contract](TOME_TEMPORAL_CONTRACT.md) · [LLMLingua-2](LLMLINGUA2.md) |
| Import a Mem0, MemOS, or M3 memory store | [Loading memories](LOADING.md) |
| Load a benchmark and choose its scoring method | [Benchmarks and evaluation](BENCHMARKS.md) |
| Save compressed memories in a framework's format | [Framework integration](WRAPPERS.md) |
| Inspect grouping decisions, retrieved memories, and answers | [Inspecting a run](ANALYSIS.md) |

For a first experiment, follow [Experiments](EXPERIMENTS.md). For an existing memory store, continue with [Loading memories](LOADING.md). The [supported configurations](COMPATIBILITY.md) page explains the requirements of each method and framework.

## Develop a component

[Adding a component](EXTENDING.md) walks through plugin installation and configuration. [Data types and interfaces](CONTRACTS.md) describes the objects exchanged by loaders, compression methods, and evaluation components.

## Read the paper results

[Paper results](PAPER_RESULTS.md) contains the complete comparison tables. [Figure sources](assets/README.md) records the origin of each image and chart. Algorithm and source attribution appears in [Third-party notices](THIRD_PARTY_NOTICES.md).
