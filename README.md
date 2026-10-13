<div align="center">
<h1>MemFolder: Structure-Guided Memory Folding<br>for Efficient Agent Memory Management</h1>

<p>
  <strong>English</strong> | <a href="README.zh-CN.md">中文</a>
</p>

<p>
Xuyang Liu<sup>1,*</sup>,
Chenwen Lu<sup>1,*</sup>,
Junxi Wang<sup>2</sup>,
Siyu Ren<sup>1</sup>,
Xinying Lin<sup>3</sup>,
<br>
Siteng Huang<sup>4</sup>,
Hongli Sun<sup>1</sup>,
Linfeng Zhang<sup>5</sup>,
Honggang Chen<sup>1,&dagger;</sup>
<br><br>
<sup>1</sup> Sichuan University &nbsp;
<sup>2</sup> Fudan University &nbsp;
<sup>3</sup> Sun Yat-sen University
<br>
<sup>4</sup> Zhejiang University &nbsp;
<sup>5</sup> Shanghai Jiao Tong University
<br><br>
<sup>*</sup> Equal contribution. &nbsp; <sup>&dagger;</sup> Corresponding author.
</p>
</div>

<p align="center">
<img src="assets/paper-intro.png" alt="Memory growth increases retrieval and context costs. RecordFolder reduces record count, and ContextFolder shortens each retrieval unit." width="1000">
</p>

> **TLDR:** As agent memory grows, retrieving records and processing the resulting context become increasingly costly.
> To reduce these costs, we propose **MemFolder**, which combines **RecordFolder** for record compression and **ContextFolder** for context compression.

<a id="news"></a>

## 🔥 News

- **`2026.10.08`** 🤗🤗 We release MemFolder, a structure-guided memory folding framework for efficient agent memory management.

<a id="highlights"></a>

## 🎯 Highlights

- **Record compression:** At **30% / 50%** record reduction, RecordFolder retains **100.7% / 99.0%** of Mem0's mean accuracy across three benchmarks.
- **Context compression:** At 50% record reduction, ContextFolder cuts tokens per record by **40.3% / 37.9%** on LoCoMo / LongMemEval, retaining **95.3% / 93.8%** of RecordFolder's accuracy.
- **Retrieval speed:** Reducing record counts by **50% / 70%** yields **1.58× / 3.06×** retrieval speedups, averaged across five evaluation settings.

<a id="overview"></a>

## ✨ Overview

<p align="center">
<img src="assets/paper-overview.png" alt="RecordFolder uses progressive anchor selection, entity-aware affinity and temporal chaining. ContextFolder plans facts, generates encodings and checks blind recovery." width="1000">
</p>

MemFolder has two modules: **RecordFolder** selects complementary anchors and consolidates related records through entity-aware affinity and temporal chains, reducing the number of retrieval units. **ContextFolder** uses a planner to prioritize facts, a compressor to generate compact encodings, and a blind verifier to check recovery and guide revision.

<a id="usage"></a>
<a id="quick-start"></a>

## Usage

As for Coding Agent users, use the following prompt to start an experiment with the bundled [memfolder-exp skill](skills/SKILL.md):

> Follow `skills/SKILL.md` in `https://github.com/xuyang-liu16/MemFolder` to run a LoCoMo pilot comparing RecordFolder and ContextFolder at 50% node retention with my configured model services.

The agent checks the environment, downloads the required data and prepares the configuration. After confirming model services and the run budget, it runs evaluation, verifies the outputs and summarizes the results.

### Experiment workflow

#### 1. Install

Use Python 3.11 or newer. Run the commands below from the repository root in Bash or a compatible shell.

```bash
git clone https://github.com/xuyang-liu16/MemFolder.git
cd MemFolder
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m memfolder --help
```
For RecordFolder and ContextFolder, install:

```bash
python -m pip install -e ".[algorithms,contextfolder,evaluation]"
```
#### 2. Download data

Experiments need **benchmark conversations/questions** and an **input memory store**. For an initial LoCoMo run, download the conversations below and keep the template's `history-initializer`, which creates one record per turn. For Mem0 or MemOS experiments, load a separately generated memory store instead.

```bash
mkdir -p data/locomo
curl -fL https://raw.githubusercontent.com/snap-research/locomo/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376/data/locomo10.json \
  -o data/locomo/locomo10.json
```
| Benchmark | Download | Dataset plugin and inputs |
| --- | --- | --- |
| LoCoMo | [Official release](https://github.com/snap-research/locomo) | `locomo-dataset`: `locomo10.json` |
| LongMemEval | [Official data](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) | `longmemeval-dataset`: e.g. `longmemeval_s_cleaned.json` |
| PersonaMem v1, 32K | [Official data](https://huggingface.co/datasets/bowen-upenn/PersonaMem) | `personamem-dataset`: `questions_32k.csv` and `shared_contexts_32k.jsonl` |
| M3-Bench robot/web | [Annotations](https://github.com/ByteDance-Seed/m3-agent/tree/master/data/annotations), [memory graphs](https://huggingface.co/datasets/ByteDance-Seed/M3-Bench/tree/main/memory_graphs) | `m3-dataset`: `robot.json` or `web.json`, plus a memory loader for each video |

<details>
<summary><b>Download commands for LongMemEval, PersonaMem and M3 annotations</b></summary>

Download only the benchmark you need:

```bash
mkdir -p data/longmemeval
curl -fL https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json \
  -o data/longmemeval/longmemeval_s_cleaned.json

mkdir -p data/personamem
curl -fL https://huggingface.co/datasets/bowen-upenn/PersonaMem/resolve/main/questions_32k.csv \
  -o data/personamem/questions_32k.csv
curl -fL https://huggingface.co/datasets/bowen-upenn/PersonaMem/resolve/main/shared_contexts_32k.jsonl \
  -o data/personamem/shared_contexts_32k.jsonl

mkdir -p data/m3
curl -fL https://raw.githubusercontent.com/ByteDance-Seed/m3-agent/0e3e41939bd8a0b66d756e7b7eb8d5fe9992da5c/data/annotations/robot.json \
  -o data/m3/robot.json
curl -fL https://raw.githubusercontent.com/ByteDance-Seed/m3-agent/0e3e41939bd8a0b66d756e7b7eb8d5fe9992da5c/data/annotations/web.json \
  -o data/m3/web.json
```
Use the corresponding entry in [dataset-components.json](examples/experiments/dataset-components.json) as the experiment's `dataset` section. PersonaMem provides turn order, and M3 clip indices express visibility; the LoCoMo templates' default `event-time-features` requires explicit parsed event times. Configure a declared order/time adapter for those inputs before compression; replacing only the dataset section is insufficient. See [benchmark configuration](skills/references/experiment-config.md#benchmark-time-and-reader-scope). Set `contexts_path` for PersonaMem, and `memory_loaders` plus `variant` for M3. Download both M3 annotations and memory graphs, preserving media paths and clip cutoffs. Full multimodal evaluation also requires the [M3-Agent controller setup](https://github.com/ByteDance-Seed/m3-agent#control).

Use the original benchmark formats with these loaders. MemForest's `dataset/longmemeval.json` and `dataset/personamem_32k.json` use a converted LoCoMo-style schema and require a matching adapter. Keep the dataset version, memory snapshot and scoring protocol matched.

</details>

<details>
<summary><b>Use a prebuilt Mem0 store</b></summary>

[MemForest_data](https://huggingface.co/datasets/Celina-love-sweet/MemForest_data) provides original Mem0 stores in `LoCoMo/locomo.tar.gz`, `LongMemEval/longmemeval.tar.gz` and `PersonaMem/personamem.tar.gz`. Use these originals as inputs for compression comparisons. The `keep30/50/70` archives contain compressed baseline outputs. For LoCoMo:

```bash
mkdir -p data/memforest
curl -fL https://huggingface.co/datasets/Celina-love-sweet/MemForest_data/resolve/37452b97d0b317a69bace34951caaf25a9949fec/LoCoMo/locomo.tar.gz \
  -o data/memforest/locomo.tar.gz
tar -xzf data/memforest/locomo.tar.gz -C data/memforest
```
The archive is about 46 MB. Keep the original store unchanged. In a configuration under `build/configs/`, replace `initializer` with the following for the first LoCoMo sample, `conv-26`:

```json
{
  "plugin": "bank-initializer",
  "parameters": {
    "loaders": {
      "conv-26": {
        "plugin": "mem0-sqlite",
        "parameters": {
          "path": "../../data/memforest/locomo/qdrant/collection/mem0/storage.sqlite",
          "options": {
            "dataset_id": "locomo",
            "sample_id": "conv-26",
            "naive_timezone": "UTC",
            "selectors": {"user_id": ["Caroline_0", "Melanie_0"]}
          }
        }
      }
    }
  }
}
```
The owner names follow MemForest's `<speaker>_<sample index>` convention. Check them against the selected store. To expand beyond this pilot, add one mapping per sample and update `dataset.parameters.sample_ids`. Use `selectors` to select each sample's owners, and import the collection's `storage.sqlite` from an offline snapshot.

Use answer scoring for imported memories. Enable `evidence-recall` when the imported nodes map to the original dialogue evidence IDs, and remove it otherwise. Other supported bank plugins are `mem0`, `mem0-qdrant`, `memos`, `memos-cube` and `m3`. The `history-initializer` creates one node per conversation turn. For framework-specific memory extraction and updates, use the upstream [Mem0](https://github.com/mem0ai/mem0), [MemOS](https://github.com/MemTensor/MemOS) or [M3-Agent](https://github.com/ByteDance-Seed/m3-agent) pipeline.

</details>

#### 3. Configure a LoCoMo experiment

Copy the templates to local configuration files:

```bash
mkdir -p build/configs
cp examples/experiments/recordfolder-template.json build/configs/locomo-recordfolder.json
cp examples/experiments/contextfolder-template.json build/configs/locomo-contextfolder.json
export MEMFOLDER_PROVIDER_KEY="YOUR_API_KEY"
```
In **both files**, replace the `dataset` section with:

```json
{
  "plugin": "locomo-dataset",
  "parameters": {
    "path": "../../data/locomo/locomo10.json",
    "utc_offset_minutes": 0,
    "evidence_policy": "preserve_unknown",
    "sample_ids": ["conv-26"]
  }
}
```
This selects one conversation. Set `sample_ids` to `[]` for all ten. `preserve_unknown` retains questions with unresolved evidence IDs and marks their evidence recall as unscored. The explicit UTC offset is used to interpret timezone-free dates consistently.

| Setting | What to change |
| --- | --- |
| `services.chat.parameters`, `services.grounding.parameters`, `services.judge.parameters` | Replace the example URL and all `REPLACE_*` model/revision values with your provider settings. |
| `services.embeddings.parameters.provider.parameters` | Configure the embedding endpoint, model and revision. |
| `compression.features[0].parameters.space` | Match the embedding model, revision and actual vector dimension. |
| `run.budgets[0].ratio` | Fraction of nodes **retained**: `0.5` for 50% reduction, `0.3` for 70% reduction. |
| `output_dir` | Use a fresh directory for each experiment. Template defaults are `../../build/experiments/recordfolder-001` and `../../build/experiments/contextfolder-001`. |

All paths resolve from the configuration file's directory. The two templates use the same source and evaluate both original and compressed memory. Keep model, sample, retrieval and scoring settings identical across the comparison. ContextFolder's writer defaults to a **0.8 token-retention target**, up to **3 rounds** and **1.15 budget slack**. An empty/invalid fact plan currently enters an unverified summary fallback without a length bound; inspect fallback counts and actual saved lengths before expanding a run. The target guides revision. Report the measured token retention of the final output.

<details>
<summary><b>Dense retrieval and paper settings</b></summary>

The starter templates use lexical top-10 retrieval, the shared MemForest LLM judge and MemOS-format output. Configure dense retrieval separately from the semantic features used for compression. Add the following under `reader.parameters`, keeping the existing answerer:

```json
{
  "retriever": {
    "plugin": "dense-retriever",
    "parameters": {
      "top_k": 10,
      "space": {
        "provider": "caller-declared",
        "model": "YOUR_EMBEDDING_MODEL",
        "revision": "YOUR_MODEL_REVISION",
        "dimension": 1536
      }
    }
  }
}
```
Also add `embedding_provider` under `compression.wrapper.parameters`, so rewritten records receive new embeddings:

```json
{
  "embedding_provider": {
    "plugin": "content-embeddings",
    "parameters": {
      "space": {
        "provider": "caller-declared",
        "model": "YOUR_EMBEDDING_MODEL",
        "revision": "YOUR_MODEL_REVISION",
        "dimension": 1536
      }
    }
  }
}
```
Use the same `space` in both blocks and in the semantic feature provider, with your model's actual dimension. Both readers select `memforest-qa-prompt`; `contextfolder-qa-prompt` remains an identical compatibility alias.

All built-in record summaries use the same MemForest merge template. Final QA and judge are shared across methods and benchmarks: `memforest-qa-prompt` and `memforest-judge`, with JSON `CORRECT`/`WRONG` labels. LLMLingua-2 and BabelTele retain their compression logic; ContextFolder's internal fact/encoding checks remain separate from final evaluation. The [prompt protocol](src/prompt_protocol.py) records the exact templates, hashes and cache identities.

To reproduce a paper table, also match its memory snapshot, model versions, retrieval settings and scoring coverage. LoCoMo F1 is an optional distinct metric; the MemForest judge is distinct from the benchmarks' original scoring protocols. For Mem0-native evaluation, configure its retriever explicitly alongside the imported memory store.

</details>

#### 4. Run and inspect results

```bash
python -m memfolder run build/configs/locomo-recordfolder.json
python -m memfolder verify build/experiments/recordfolder-001
python -m memfolder run build/configs/locomo-contextfolder.json
python -m memfolder verify build/experiments/contextfolder-001
python -m memfolder case build/experiments/recordfolder-001 \
  --dataset-id locomo --sample-id conv-26 --question-id conv-26:0 \
  --output build/cases/locomo-recordfolder-q0
```
These runs call the configured model APIs. Each output directory contains `result.json` with original/compressed scores and per-sample statistics, `run.manifest.json` with execution status, and per-sample memory snapshots and predictions. `verify` checks artifact integrity. `case` exports one question for inspection.

For budget/seed sweeps, configure [matrix-template.json](examples/experiments/matrix-template.json) with the same data and services as your experiment, then run `python -m memfolder matrix CONFIG.json`. `--resume` reuses a validated **completed** run. After a failed run, preserve its files and retry in a fresh output directory.

The [PersonaMem Mem0](examples/experiments/personamem-mem0-template.json), [PersonaMem MemOS](examples/experiments/personamem-memos-template.json) and [M3](examples/experiments/m3-recordfolder-template.json) templates use framework-specific ordering rules: Mem0 `created_at`, MemOS `(ts, id)`, and numeric node IDs within each M3 clip. Supply your dataset paths, question/video IDs, memory mappings and model services. Prefix banks require explicit source history positions; M3 budgets remain per clip. See the [time and prefix configuration](skills/references/experiment-config.md#framework-time-and-order-profiles) for field mapping, ContextFolder composition and reader scope.

<details>
<summary><b>Baseline recipes</b></summary>

[examples/recipes/](examples/recipes/) provides compression configurations for each method. Copy your configured RecordFolder experiment, then replace its `compression.planner` and `compression.operator` with the selected recipe's components. Configure each required feature once, keep the wrapper and services, and retain the shared QA/judge. A compression recipe is a component fragment, not a complete experiment config.

- For [MemForest scope-capacity](examples/recipes/memforest-mst-capacity.json), set `run.mode` to `"repeat"` and use `event-time-features` with `aggregation: "latest"`, alongside the semantic encoder. Run the [per-cluster ceiling](examples/recipes/memforest-mst-cluster-ceil.json) variant through the Python API with `resolve_memforest_budget`. The M3 average-linkage proxy is a separately named adaptation.
- [Text ToMe](skills/references/tome.md) uses a chronological-halves planner with the common `text-operator` and `semantic-encoder`, in `run.mode: "repeat"`. The shared feature provider encodes current text before each match, so raw history needs no precomputed node vectors. Start from [tome-template.json](examples/experiments/tome-template.json), declare the embedding space and configure each feature name once. The cached embedding service reuses unchanged text. Native vector output and dense retrieval still need the wrapper's content-embedding provider. The alternating-partition variant is `tome-bsm`.
- [LLMLingua-2](skills/references/llmlingua2.md) compresses final record text with a default retention rate of `0.55`. The token-budget compression service, all-text embedding refresh and explicit Mem0 owner mapping remain separately configurable.
- [record_and_context_compression.py](examples/record_and_context_compression.py) applies ContextFolder to another compressor's final records, preserving their count while rewriting the text.

</details>

JSON files under `examples/` configure experiments, compression components and
data loaders. The Python contracts in [src/core/](src/core/)
define the data interface. Export JSON Schema when an integration needs it:

```bash
python tools/export_schemas.py --output-dir build/schemas
```

<a id="main-results"></a>
<a id="full-results"></a>

## Full results

The tables and figures below report the paper's results with their original
method and evaluation identities. New repository runs record their own scores
and protocol manifests; updated prompts or methods do not relabel these numbers.

### RecordFolder: record compression

**All** denotes overall accuracy, **Avg.** the mean across benchmarks, and **%** the average accuracy retained relative to the uncompressed framework.

#### Record compression on Mem0

<table>
<thead>
<tr><th rowspan="2">Method</th><th colspan="5">LoCoMo</th><th colspan="7">LongMemEval</th><th rowspan="2">Persona<br>-Mem</th><th rowspan="2">Avg.</th><th rowspan="2">%</th></tr>
<tr><th>SH</th><th>MH</th><th>TR</th><th>OD</th><th>All</th><th>SU</th><th>SA</th><th>SP</th><th>MS</th><th>KU</th><th>TR</th><th>All</th></tr>
</thead>
<tbody>
<tr><td>Mem0</td><td align="center">66.0</td><td align="center">56.0</td><td align="center">53.9</td><td align="center">42.7</td><td align="center">60.2</td><td align="center">90.0</td><td align="center">21.4</td><td align="center">23.3</td><td align="center">54.9</td><td align="center">79.5</td><td align="center">44.4</td><td align="center">55.2</td><td align="center">67.9</td><td align="center">61.1</td><td align="center">100.0</td></tr>
<tr><td colspan="16"><em>Record compression ratio &darr; 30%</em></td></tr>
<tr><td>+&nbsp;Random&nbsp;Pruning</td><td align="center">55.3</td><td align="center">49.7</td><td align="center">43.3</td><td align="center">39.6</td><td align="center">50.8</td><td align="center">82.9</td><td align="center">17.9</td><td align="center"><ins>26.7</ins></td><td align="center"><ins>51.9</ins></td><td align="center">73.1</td><td align="center">39.1</td><td align="center">50.8</td><td align="center">64.5</td><td align="center">55.4</td><td align="center">90.7</td></tr>
<tr><td>+&nbsp;KMeans</td><td align="center">61.1</td><td align="center">54.3</td><td align="center"><ins>52.7</ins></td><td align="center">40.6</td><td align="center">56.8</td><td align="center">84.3</td><td align="center">17.9</td><td align="center">20.0</td><td align="center"><ins>51.9</ins></td><td align="center"><ins>75.6</ins></td><td align="center">41.4</td><td align="center">52.0</td><td align="center">65.7</td><td align="center">58.2</td><td align="center">95.3</td></tr>
<tr><td>+&nbsp;DART</td><td align="center"><ins>64.1</ins></td><td align="center">53.9</td><td align="center">48.0</td><td align="center">40.6</td><td align="center">57.4</td><td align="center">82.9</td><td align="center">19.0</td><td align="center">20.0</td><td align="center">48.9</td><td align="center">74.4</td><td align="center">34.6</td><td align="center">48.8</td><td align="center"><ins>66.6</ins></td><td align="center">57.6</td><td align="center">94.3</td></tr>
<tr><td>+&nbsp;Random&nbsp;Merging</td><td align="center">60.9</td><td align="center">52.1</td><td align="center">51.1</td><td align="center">43.8</td><td align="center">56.2</td><td align="center"><strong>91.4</strong></td><td align="center"><strong>21.4</strong></td><td align="center">20.2</td><td align="center">46.6</td><td align="center">74.4</td><td align="center">41.4</td><td align="center">50.8</td><td align="center">65.2</td><td align="center">57.4</td><td align="center">93.9</td></tr>
<tr><td>+&nbsp;ToMe</td><td align="center">63.1</td><td align="center">51.1</td><td align="center">50.8</td><td align="center"><ins>44.8</ins></td><td align="center">57.2</td><td align="center">85.7</td><td align="center"><strong>21.4</strong></td><td align="center">23.3</td><td align="center">48.1</td><td align="center">71.8</td><td align="center">42.9</td><td align="center">51.2</td><td align="center">66.4</td><td align="center">58.3</td><td align="center">95.4</td></tr>
<tr><td>+&nbsp;MemForest</td><td align="center">63.7</td><td align="center"><ins>54.6</ins></td><td align="center">52.0</td><td align="center"><strong>45.8</strong></td><td align="center"><ins>58.5</ins></td><td align="center"><ins>90.0</ins></td><td align="center"><ins>19.6</ins></td><td align="center">20.0</td><td align="center">49.8</td><td align="center"><strong>76.9</strong></td><td align="center"><strong>49.6</strong></td><td align="center"><ins>54.2</ins></td><td align="center"><ins>66.6</ins></td><td align="center"><ins>59.7</ins></td><td align="center"><ins>97.7</ins></td></tr>
<tr><td>+&nbsp;<strong>MemFolder&nbsp;(Ours)</strong></td><td align="center"><strong>67.5</strong></td><td align="center"><strong>56.0</strong></td><td align="center"><strong>56.1</strong></td><td align="center">41.7</td><td align="center"><strong>61.7</strong></td><td align="center">88.6</td><td align="center"><strong>21.4</strong></td><td align="center"><strong>36.7</strong></td><td align="center"><strong>52.6</strong></td><td align="center"><ins>75.6</ins></td><td align="center"><ins>46.6</ins></td><td align="center"><strong>55.2</strong></td><td align="center"><strong>67.7</strong></td><td align="center"><strong>61.5</strong></td><td align="center"><strong>100.7</strong></td></tr>
<tr><td colspan="16"><em>Record compression ratio &darr; 50%</em></td></tr>
<tr><td>+&nbsp;Random&nbsp;Pruning</td><td align="center">44.4</td><td align="center">45.4</td><td align="center">37.1</td><td align="center"><strong>44.8</strong></td><td align="center">43.1</td><td align="center">75.7</td><td align="center">17.9</td><td align="center"><ins>26.7</ins></td><td align="center">32.3</td><td align="center">65.4</td><td align="center">39.8</td><td align="center">43.6</td><td align="center">64.3</td><td align="center">50.3</td><td align="center">82.3</td></tr>
<tr><td>+&nbsp;KMeans</td><td align="center">51.6</td><td align="center">43.6</td><td align="center">39.6</td><td align="center">37.5</td><td align="center">46.8</td><td align="center">77.1</td><td align="center">19.6</td><td align="center">23.3</td><td align="center">39.1</td><td align="center"><ins>74.4</ins></td><td align="center">39.8</td><td align="center">47.0</td><td align="center">65.2</td><td align="center">53.0</td><td align="center">86.7</td></tr>
<tr><td>+&nbsp;DART</td><td align="center">57.4</td><td align="center">49.6</td><td align="center">41.7</td><td align="center"><ins>43.8</ins></td><td align="center">51.9</td><td align="center">67.1</td><td align="center">12.5</td><td align="center">23.3</td><td align="center">42.9</td><td align="center">60.3</td><td align="center">31.6</td><td align="center">41.4</td><td align="center">64.3</td><td align="center">52.5</td><td align="center">85.9</td></tr>
<tr><td>+&nbsp;Random&nbsp;Merging</td><td align="center">56.0</td><td align="center">48.2</td><td align="center">46.4</td><td align="center">37.5</td><td align="center">51.4</td><td align="center">85.7</td><td align="center"><strong>23.2</strong></td><td align="center">20.0</td><td align="center">42.9</td><td align="center">70.5</td><td align="center">39.1</td><td align="center">48.6</td><td align="center">64.5</td><td align="center">54.8</td><td align="center">89.7</td></tr>
<tr><td>+&nbsp;ToMe</td><td align="center">60.2</td><td align="center">50.4</td><td align="center">47.4</td><td align="center"><ins>43.8</ins></td><td align="center">54.7</td><td align="center">85.7</td><td align="center"><ins>21.4</ins></td><td align="center">23.3</td><td align="center"><ins>48.1</ins></td><td align="center">71.8</td><td align="center">41.4</td><td align="center">50.8</td><td align="center">65.9</td><td align="center">57.1</td><td align="center">93.5</td></tr>
<tr><td>+&nbsp;MemForest</td><td align="center"><ins>62.1</ins></td><td align="center"><strong>56.7</strong></td><td align="center"><strong>54.8</strong></td><td align="center"><ins>43.8</ins></td><td align="center"><ins>58.4</ins></td><td align="center"><strong>90.0</strong></td><td align="center">19.6</td><td align="center">20.0</td><td align="center"><ins>48.1</ins></td><td align="center"><ins>74.4</ins></td><td align="center"><ins>42.9</ins></td><td align="center"><ins>51.8</ins></td><td align="center"><strong>67.7</strong></td><td align="center"><ins>59.3</ins></td><td align="center"><ins>97.1</ins></td></tr>
<tr><td>+&nbsp;<strong>MemFolder&nbsp;(Ours)</strong></td><td align="center"><strong>65.5</strong></td><td align="center"><ins>55.7</ins></td><td align="center"><ins>50.5</ins></td><td align="center">39.6</td><td align="center"><strong>59.3</strong></td><td align="center"><ins>88.6</ins></td><td align="center"><ins>21.4</ins></td><td align="center"><strong>30.0</strong></td><td align="center"><strong>53.4</strong></td><td align="center"><strong>76.9</strong></td><td align="center"><strong>45.9</strong></td><td align="center"><strong>55.0</strong></td><td align="center"><ins>67.2</ins></td><td align="center"><strong>60.5</strong></td><td align="center"><strong>99.0</strong></td></tr>
<tr><td colspan="16"><em>Record compression ratio &darr; 70%</em></td></tr>
<tr><td>+&nbsp;Random&nbsp;Pruning</td><td align="center">35.0</td><td align="center">36.5</td><td align="center">25.9</td><td align="center">31.3</td><td align="center">33.1</td><td align="center">47.1</td><td align="center">7.1</td><td align="center"><ins>30.0</ins></td><td align="center">16.5</td><td align="center">42.3</td><td align="center">31.6</td><td align="center">28.6</td><td align="center">63.7</td><td align="center">41.8</td><td align="center">68.4</td></tr>
<tr><td>+&nbsp;KMeans</td><td align="center">37.9</td><td align="center">42.6</td><td align="center">27.4</td><td align="center">39.6</td><td align="center">36.7</td><td align="center">61.4</td><td align="center">8.9</td><td align="center"><ins>30.0</ins></td><td align="center">21.8</td><td align="center">59.0</td><td align="center">31.6</td><td align="center">34.8</td><td align="center">63.8</td><td align="center">45.1</td><td align="center">73.8</td></tr>
<tr><td>+&nbsp;DART</td><td align="center">46.4</td><td align="center">44.3</td><td align="center">36.1</td><td align="center">41.7</td><td align="center">43.6</td><td align="center">44.3</td><td align="center">10.7</td><td align="center">16.7</td><td align="center">21.0</td><td align="center">43.6</td><td align="center">27.8</td><td align="center">30.6</td><td align="center">61.8</td><td align="center">45.3</td><td align="center">74.1</td></tr>
<tr><td>+&nbsp;Random&nbsp;Merging</td><td align="center">54.0</td><td align="center">47.2</td><td align="center">47.0</td><td align="center"><ins>43.8</ins></td><td align="center">50.7</td><td align="center">80.0</td><td align="center">21.4</td><td align="center"><ins>30.0</ins></td><td align="center">41.4</td><td align="center">67.9</td><td align="center">34.6</td><td align="center">46.2</td><td align="center">64.0</td><td align="center">53.6</td><td align="center">87.7</td></tr>
<tr><td>+&nbsp;ToMe</td><td align="center">56.6</td><td align="center">51.8</td><td align="center"><ins>47.7</ins></td><td align="center">38.5</td><td align="center">52.7</td><td align="center"><ins>84.3</ins></td><td align="center">21.4</td><td align="center">20.0</td><td align="center">45.1</td><td align="center">70.5</td><td align="center"><ins>42.1</ins></td><td align="center">49.6</td><td align="center"><strong>65.7</strong></td><td align="center">56.0</td><td align="center">91.7</td></tr>
<tr><td>+&nbsp;MemForest</td><td align="center"><ins>58.1</ins></td><td align="center"><ins>56.4</ins></td><td align="center">45.2</td><td align="center"><strong>45.8</strong></td><td align="center"><ins>54.4</ins></td><td align="center"><ins>84.3</ins></td><td align="center"><strong>25.0</strong></td><td align="center">23.3</td><td align="center"><strong>52.6</strong></td><td align="center"><ins>74.4</ins></td><td align="center">39.8</td><td align="center"><ins>52.2</ins></td><td align="center">64.4</td><td align="center"><ins>57.0</ins></td><td align="center"><ins>93.3</ins></td></tr>
<tr><td>+&nbsp;<strong>MemFolder&nbsp;(Ours)</strong></td><td align="center"><strong>61.2</strong></td><td align="center"><strong>57.0</strong></td><td align="center"><strong>50.7</strong></td><td align="center">43.4</td><td align="center"><strong>57.1</strong></td><td align="center"><strong>85.7</strong></td><td align="center"><ins>23.2</ins></td><td align="center"><strong>53.3</strong></td><td align="center"><ins>50.4</ins></td><td align="center"><strong>75.6</strong></td><td align="center"><strong>45.1</strong></td><td align="center"><strong>55.0</strong></td><td align="center"><ins>64.9</ins></td><td align="center"><strong>59.0</strong></td><td align="center"><strong>96.6</strong></td></tr>
</tbody>
</table>

#### Record compression on MemOS

<table>
<thead>
<tr><th rowspan="2">Method</th><th colspan="5">LoCoMo</th><th colspan="7">LongMemEval</th><th rowspan="2">Persona<br>-Mem</th><th rowspan="2">Avg.</th><th rowspan="2">%</th></tr>
<tr><th>SH</th><th>MH</th><th>TR</th><th>OD</th><th>All</th><th>SU</th><th>SA</th><th>SP</th><th>MS</th><th>KU</th><th>TR</th><th>All</th></tr>
</thead>
<tbody>
<tr><td>MemOS</td><td align="center">84.5</td><td align="center">70.2</td><td align="center">78.8</td><td align="center">56.2</td><td align="center">79.0</td><td align="center">91.4</td><td align="center">100.0</td><td align="center">66.7</td><td align="center">55.6</td><td align="center">78.2</td><td align="center">71.4</td><td align="center">74.0</td><td align="center">60.3</td><td align="center">71.1</td><td align="center">100.0</td></tr>
<tr><td colspan="16"><em>Record compression ratio &darr; 50%</em></td></tr>
<tr><td>+&nbsp;Random&nbsp;Pruning</td><td align="center">70.5</td><td align="center">65.2</td><td align="center">57.3</td><td align="center">46.9</td><td align="center">65.3</td><td align="center">67.1</td><td align="center">64.3</td><td align="center">63.3</td><td align="center">28.6</td><td align="center">52.6</td><td align="center">43.6</td><td align="center">47.8</td><td align="center">55.9</td><td align="center">56.3</td><td align="center">79.2</td></tr>
<tr><td>+&nbsp;KMeans</td><td align="center">75.7</td><td align="center">59.2</td><td align="center">57.6</td><td align="center"><ins>57.3</ins></td><td align="center">67.8</td><td align="center">72.9</td><td align="center">69.6</td><td align="center">66.7</td><td align="center">20.3</td><td align="center">51.3</td><td align="center">45.9</td><td align="center">47.6</td><td align="center">54.7</td><td align="center">56.7</td><td align="center">79.7</td></tr>
<tr><td>+&nbsp;DART</td><td align="center">76.5</td><td align="center">68.1</td><td align="center">58.9</td><td align="center"><strong>58.3</strong></td><td align="center">70.1</td><td align="center">62.9</td><td align="center"><strong>82.1</strong></td><td align="center">50.0</td><td align="center">20.3</td><td align="center">35.9</td><td align="center">33.1</td><td align="center">40.8</td><td align="center">53.7</td><td align="center">54.9</td><td align="center">77.2</td></tr>
<tr><td>+&nbsp;Random&nbsp;Merging</td><td align="center">79.4</td><td align="center"><ins>69.9</ins></td><td align="center">66.0</td><td align="center">54.2</td><td align="center">73.3</td><td align="center">80.0</td><td align="center">62.5</td><td align="center"><strong>83.3</strong></td><td align="center"><strong>46.6</strong></td><td align="center">60.3</td><td align="center">54.9</td><td align="center">59.6</td><td align="center"><ins>56.2</ins></td><td align="center">63.0</td><td align="center">88.7</td></tr>
<tr><td>+&nbsp;ToMe</td><td align="center">76.7</td><td align="center">68.8</td><td align="center">63.9</td><td align="center">52.1</td><td align="center">71.0</td><td align="center">78.6</td><td align="center">67.9</td><td align="center"><ins>76.7</ins></td><td align="center">40.6</td><td align="center"><ins>70.5</ins></td><td align="center"><strong>63.2</strong></td><td align="center"><ins>61.8</ins></td><td align="center"><strong>57.9</strong></td><td align="center">63.6</td><td align="center">89.4</td></tr>
<tr><td>+&nbsp;MemForest</td><td align="center"><strong>82.6</strong></td><td align="center">68.8</td><td align="center"><strong>70.1</strong></td><td align="center"><strong>58.3</strong></td><td align="center"><strong>76.0</strong></td><td align="center"><ins>81.4</ins></td><td align="center">76.8</td><td align="center">66.7</td><td align="center">40.6</td><td align="center">65.4</td><td align="center"><ins>56.4</ins></td><td align="center">60.0</td><td align="center">54.8</td><td align="center"><ins>63.6</ins></td><td align="center"><ins>89.5</ins></td></tr>
<tr><td>+&nbsp;<strong>MemFolder&nbsp;(Ours)</strong></td><td align="center"><ins>81.2</ins></td><td align="center"><strong>70.6</strong></td><td align="center"><ins>69.5</ins></td><td align="center">56.2</td><td align="center"><ins>75.3</ins></td><td align="center"><strong>85.7</strong></td><td align="center"><ins>78.6</ins></td><td align="center"><strong>83.3</strong></td><td align="center"><ins>45.1</ins></td><td align="center"><strong>75.6</strong></td><td align="center">54.9</td><td align="center"><strong>64.2</strong></td><td align="center">54.7</td><td align="center"><strong>64.7</strong></td><td align="center"><strong>91.0</strong></td></tr>
<tr><td colspan="16"><em>Record compression ratio &darr; 70%</em></td></tr>
<tr><td>+&nbsp;Random&nbsp;Pruning</td><td align="center">58.5</td><td align="center">59.9</td><td align="center">43.0</td><td align="center">49.0</td><td align="center">54.9</td><td align="center">32.9</td><td align="center">48.2</td><td align="center">73.3</td><td align="center">13.5</td><td align="center">29.5</td><td align="center">28.6</td><td align="center">30.2</td><td align="center">52.8</td><td align="center">46.0</td><td align="center">64.7</td></tr>
<tr><td>+&nbsp;KMeans</td><td align="center">62.5</td><td align="center">57.8</td><td align="center">43.9</td><td align="center">55.2</td><td align="center">57.3</td><td align="center">40.0</td><td align="center">53.6</td><td align="center">50.0</td><td align="center">15.8</td><td align="center">30.8</td><td align="center">30.1</td><td align="center">31.6</td><td align="center">52.6</td><td align="center">47.2</td><td align="center">66.4</td></tr>
<tr><td>+&nbsp;DART</td><td align="center">65.6</td><td align="center">59.9</td><td align="center">46.1</td><td align="center">54.2</td><td align="center">59.8</td><td align="center">30.0</td><td align="center">60.7</td><td align="center">50.0</td><td align="center">15.0</td><td align="center">25.6</td><td align="center">18.0</td><td align="center">26.8</td><td align="center">48.9</td><td align="center">45.2</td><td align="center">63.5</td></tr>
<tr><td>+&nbsp;Random&nbsp;Merging</td><td align="center">73.0</td><td align="center">64.2</td><td align="center"><ins>61.7</ins></td><td align="center"><ins>57.3</ins></td><td align="center">68.1</td><td align="center"><strong>75.7</strong></td><td align="center">39.3</td><td align="center"><ins>83.3</ins></td><td align="center"><strong>39.1</strong></td><td align="center">60.3</td><td align="center"><strong>52.6</strong></td><td align="center"><ins>53.8</ins></td><td align="center">54.0</td><td align="center">58.6</td><td align="center">82.5</td></tr>
<tr><td>+&nbsp;ToMe</td><td align="center">71.7</td><td align="center"><ins>68.8</ins></td><td align="center">60.7</td><td align="center">47.9</td><td align="center">67.4</td><td align="center">67.1</td><td align="center"><strong>67.9</strong></td><td align="center">70.0</td><td align="center">32.3</td><td align="center"><ins>62.8</ins></td><td align="center"><ins>51.9</ins></td><td align="center">53.4</td><td align="center"><ins>55.4</ins></td><td align="center">58.7</td><td align="center">82.6</td></tr>
<tr><td>+&nbsp;MemForest</td><td align="center"><ins>77.4</ins></td><td align="center">64.9</td><td align="center"><strong>62.6</strong></td><td align="center">56.2</td><td align="center"><ins>70.7</ins></td><td align="center">62.9</td><td align="center"><ins>66.1</ins></td><td align="center">73.3</td><td align="center">30.8</td><td align="center">50.0</td><td align="center">50.4</td><td align="center">50.0</td><td align="center"><strong>55.5</strong></td><td align="center"><ins>58.7</ins></td><td align="center"><ins>82.6</ins></td></tr>
<tr><td>+&nbsp;<strong>MemFolder&nbsp;(Ours)</strong></td><td align="center"><strong>77.5</strong></td><td align="center"><strong>69.1</strong></td><td align="center">60.1</td><td align="center"><strong>60.4</strong></td><td align="center"><strong>71.3</strong></td><td align="center"><ins>74.3</ins></td><td align="center">62.5</td><td align="center"><strong>93.3</strong></td><td align="center"><ins>33.8</ins></td><td align="center"><strong>65.4</strong></td><td align="center">45.9</td><td align="center"><strong>54.4</strong></td><td align="center">55.2</td><td align="center"><strong>60.3</strong></td><td align="center"><strong>84.8</strong></td></tr>
</tbody>
</table>

#### Record compression on M3-Bench

<table>
<thead>
<tr><th rowspan="2">Method</th><th colspan="6">M3-Bench-robot</th><th colspan="6">M3-Bench-web</th><th rowspan="2">Avg.</th><th rowspan="2">%</th></tr>
<tr><th>ME</th><th>MH</th><th>CM</th><th>PU</th><th>GK</th><th>All</th><th>ME</th><th>MH</th><th>CM</th><th>PU</th><th>GK</th><th>All</th></tr>
</thead>
<tbody>
<tr><td>M3-Agent</td><td align="center">30.9</td><td align="center">29.4</td><td align="center">29.6</td><td align="center">41.1</td><td align="center">22.6</td><td align="center">30.3</td><td align="center">44.9</td><td align="center">25.6</td><td align="center">44.8</td><td align="center">58.6</td><td align="center">53.7</td><td align="center">47.9</td><td align="center">39.1</td><td align="center">100.0</td></tr>
<tr><td colspan="15"><em>Record compression ratio &darr; 50%</em></td></tr>
<tr><td>+&nbsp;Random&nbsp;Pruning</td><td align="center">28.4</td><td align="center">25.9</td><td align="center">27.3</td><td align="center">38.7</td><td align="center">19.6</td><td align="center">28.1</td><td align="center">35.6</td><td align="center">23.0</td><td align="center">34.9</td><td align="center">52.3</td><td align="center">44.2</td><td align="center">41.2</td><td align="center">34.7</td><td align="center">88.7</td></tr>
<tr><td>+&nbsp;KMeans</td><td align="center">29.1</td><td align="center">30.6</td><td align="center">28.4</td><td align="center">41.4</td><td align="center">20.8</td><td align="center">29.2</td><td align="center">41.1</td><td align="center">21.7</td><td align="center">42.5</td><td align="center">55.0</td><td align="center">47.4</td><td align="center">43.9</td><td align="center">36.6</td><td align="center">93.6</td></tr>
<tr><td>+&nbsp;DART</td><td align="center">28.9</td><td align="center">25.9</td><td align="center">29.4</td><td align="center">39.1</td><td align="center">22.0</td><td align="center">29.1</td><td align="center">39.9</td><td align="center">23.6</td><td align="center">39.4</td><td align="center">52.9</td><td align="center">47.2</td><td align="center">43.1</td><td align="center">36.1</td><td align="center">92.3</td></tr>
<tr><td>+&nbsp;StreamMeCo</td><td align="center">32.3</td><td align="center">28.2</td><td align="center">29.8</td><td align="center">41.4</td><td align="center">21.1</td><td align="center">30.6</td><td align="center">39.7</td><td align="center">25.2</td><td align="center">38.9</td><td align="center">58.4</td><td align="center">47.3</td><td align="center">44.7</td><td align="center">37.7</td><td align="center">96.2</td></tr>
<tr><td>+&nbsp;Random&nbsp;Merging</td><td align="center">33.0</td><td align="center">32.9</td><td align="center">31.9</td><td align="center">44.3</td><td align="center">19.6</td><td align="center">30.8</td><td align="center">41.8</td><td align="center">21.0</td><td align="center">40.1</td><td align="center">58.0</td><td align="center">46.3</td><td align="center">44.6</td><td align="center">37.7</td><td align="center">96.4</td></tr>
<tr><td>+&nbsp;ToMe</td><td align="center">30.5</td><td align="center">32.9</td><td align="center">29.6</td><td align="center">42.3</td><td align="center">19.9</td><td align="center">30.9</td><td align="center">42.7</td><td align="center">24.7</td><td align="center">41.7</td><td align="center">54.3</td><td align="center">53.1</td><td align="center">46.1</td><td align="center">38.5</td><td align="center">98.5</td></tr>
<tr><td>+&nbsp;MemForest</td><td align="center">31.6</td><td align="center">31.8</td><td align="center">31.1</td><td align="center">45.1</td><td align="center">21.4</td><td align="center"><strong>31.6</strong></td><td align="center">42.6</td><td align="center">23.9</td><td align="center">43.4</td><td align="center">57.1</td><td align="center">51.5</td><td align="center"><ins>46.5</ins></td><td align="center"><ins>39.0</ins></td><td align="center"><ins>99.7</ins></td></tr>
<tr><td>+&nbsp;<strong>MemFolder&nbsp;(Ours)</strong></td><td align="center">31.7</td><td align="center">34.1</td><td align="center">30.0</td><td align="center">45.3</td><td align="center">19.9</td><td align="center"><ins>31.0</ins></td><td align="center">44.6</td><td align="center">27.8</td><td align="center">44.6</td><td align="center">59.6</td><td align="center">52.4</td><td align="center"><strong>48.2</strong></td><td align="center"><strong>39.6</strong></td><td align="center"><strong>101.3</strong></td></tr>
<tr><td colspan="15"><em>Record compression ratio &darr; 70%</em></td></tr>
<tr><td>+&nbsp;Random&nbsp;Pruning</td><td align="center">27.3</td><td align="center">25.9</td><td align="center">26.7</td><td align="center">39.2</td><td align="center">20.8</td><td align="center">27.7</td><td align="center">35.0</td><td align="center">19.9</td><td align="center">34.9</td><td align="center">48.7</td><td align="center">39.5</td><td align="center">37.3</td><td align="center">32.5</td><td align="center">83.1</td></tr>
<tr><td>+&nbsp;KMeans</td><td align="center">28.7</td><td align="center">28.2</td><td align="center">27.3</td><td align="center">42.7</td><td align="center">19.3</td><td align="center">28.9</td><td align="center">35.5</td><td align="center">20.1</td><td align="center">34.9</td><td align="center">39.7</td><td align="center">42.5</td><td align="center">39.1</td><td align="center">34.0</td><td align="center">87.0</td></tr>
<tr><td>+&nbsp;DART</td><td align="center">27.8</td><td align="center">25.9</td><td align="center">25.4</td><td align="center">40.0</td><td align="center">16.2</td><td align="center">27.2</td><td align="center">35.4</td><td align="center">19.5</td><td align="center">36.6</td><td align="center">48.2</td><td align="center">45.0</td><td align="center">39.2</td><td align="center">33.2</td><td align="center">84.9</td></tr>
<tr><td>+&nbsp;StreamMeCo</td><td align="center">29.1</td><td align="center">30.6</td><td align="center">26.9</td><td align="center">40.3</td><td align="center">19.9</td><td align="center">28.4</td><td align="center">37.0</td><td align="center">21.7</td><td align="center">36.1</td><td align="center">53.0</td><td align="center">46.3</td><td align="center">41.9</td><td align="center">35.1</td><td align="center">89.8</td></tr>
<tr><td>+&nbsp;Random&nbsp;Merging</td><td align="center">30.6</td><td align="center">31.8</td><td align="center">28.8</td><td align="center">45.1</td><td align="center">19.0</td><td align="center">30.4</td><td align="center">41.1</td><td align="center">21.9</td><td align="center">39.6</td><td align="center">58.6</td><td align="center">41.5</td><td align="center">43.2</td><td align="center">36.8</td><td align="center">94.1</td></tr>
<tr><td>+&nbsp;ToMe</td><td align="center">31.7</td><td align="center">27.1</td><td align="center">28.6</td><td align="center">43.1</td><td align="center">20.2</td><td align="center">30.6</td><td align="center">42.9</td><td align="center">23.6</td><td align="center">43.6</td><td align="center">56.5</td><td align="center">49.8</td><td align="center">45.7</td><td align="center">38.2</td><td align="center">97.7</td></tr>
<tr><td>+&nbsp;MemForest</td><td align="center">31.2</td><td align="center">32.9</td><td align="center">32.4</td><td align="center">43.6</td><td align="center">17.4</td><td align="center">30.7</td><td align="center">44.8</td><td align="center">23.9</td><td align="center">38.9</td><td align="center">57.3</td><td align="center">50.4</td><td align="center">46.3</td><td align="center">38.5</td><td align="center">98.5</td></tr>
<tr><td>+&nbsp;<strong>MemFolder&nbsp;(Ours)</strong></td><td align="center">32.3</td><td align="center">29.4</td><td align="center">30.9</td><td align="center">45.4</td><td align="center">19.9</td><td align="center"><strong>31.4</strong></td><td align="center">44.5</td><td align="center">28.9</td><td align="center">44.1</td><td align="center">60.3</td><td align="center">51.6</td><td align="center"><strong>48.7</strong></td><td align="center"><strong>40.1</strong></td><td align="center"><strong>102.6</strong></td></tr>
</tbody>
</table>

### ContextFolder: context compression

<p align="center">
<img src="assets/paper-context-results.png" alt="Accuracy versus tokens per record at 50% record reduction on LoCoMo, LongMemEval and M3-Bench-robot." width="1000">
</p>

At 50% record reduction, ContextFolder further reduces tokens per record by **40.3% on LoCoMo** and **37.9% on LongMemEval** relative to RecordFolder alone, with final accuracy of **56.6%** and **51.8%**, respectively. Upper left is better. Colors identify record compressors, and markers identify context compressors.

### Retrieval efficiency

<p align="center">
<img src="assets/paper-retrieval-efficiency.png" alt="Mean and P95 retrieval latency across five settings at 100%, 50% and 30% of records retained." width="1000">
</p>

Keeping 30% of records yields **1.88–5.34×** mean retrieval speedups across five settings. Solid lines show mean latency, and dashed lines show P95 latency. The horizontal axis shows records **retained**, while the tables above show records **removed**.
