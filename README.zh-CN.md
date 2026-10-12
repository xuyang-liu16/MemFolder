<div align="center">
<h1>MemFolder: Structure-Guided Memory Folding<br>for Efficient Agent Memory Management</h1>

<p>
  <a href="README.md">English</a> | <strong>中文</strong>
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
<sup>1</sup> 四川大学 &nbsp;
<sup>2</sup> 复旦大学 &nbsp;
<sup>3</sup> 中山大学
<br>
<sup>4</sup> 浙江大学 &nbsp;
<sup>5</sup> 上海交通大学
<br><br>
<sup>*</sup> 共同第一作者。 &nbsp; <sup>&dagger;</sup> 通讯作者。
</p>
</div>

<p align="center">
<a href="docs/assets/paper-intro.pdf"><img src="docs/assets/paper-intro.png" alt="记忆增长带来检索和上下文开销，RecordFolder 减少节点数量，ContextFolder 缩短每个检索单元的文本。" width="1000"></a>
</p>

> **TLDR:** 随着智能体记忆不断积累，节点检索和上下文处理的开销持续增加。
> 为降低这些开销，我们提出 **MemFolder**，包含用于节点压缩的 **RecordFolder** 和用于上下文压缩的 **ContextFolder**。

<a id="news"></a>

## 🔥 最新动态

- **`2026.10.08`** 🤗🤗 我们发布 MemFolder，一个用于高效智能体记忆管理的结构引导记忆折叠框架。

<a id="highlights"></a>

## 🎯 核心亮点

- **节点压缩：** 压缩 **30% / 50%** 节点后，RecordFolder 在三个基准上保留 Mem0 原始平均准确率的 **100.7% / 99.0%**。
- **上下文压缩：** 压缩 50% 节点后，ContextFolder 在 LoCoMo / LongMemEval 上将每节点 token 数再降 **40.3% / 37.9%**，同时保留 RecordFolder 准确率的 **95.3% / 93.8%**。
- **检索加速：** 压缩 **50% / 70%** 节点后，五个评测设置的平均检索加速分别为 **1.58× / 3.06×**。

<a id="overview"></a>

## ✨ 方法概览

<p align="center">
<a href="docs/assets/paper-overview.pdf"><img src="docs/assets/paper-overview.png" alt="RecordFolder 通过渐进式锚点选择、实体感知亲和度和时间链完成分组。ContextFolder 规划事实、生成编码并验证盲恢复结果。" width="1000"></a>
</p>

MemFolder 包含两个模块：**RecordFolder** 选择互补锚点，结合实体感知亲和度与时间链整合相关节点，减少检索单元。**ContextFolder** 使用规划器确定事实优先级、压缩器生成紧凑编码，再通过盲验证器检查事实恢复并指导迭代修订。

<a id="usage"></a>
<a id="quick-start"></a>

## 使用说明

对于 Coding Agent 用户，可以发送以下指令，按仓库内的 [memfolder-exp skill](skills/memfolder-exp/SKILL.md) 开始实验：

> 请按 `https://github.com/xuyang-liu16/MemFolder` 中的 `skills/memfolder-exp/SKILL.md`，使用我配置的模型服务运行 LoCoMo 小规模实验，对比保留 50% 节点的 RecordFolder 和 ContextFolder。

Agent 会检查环境、下载所需数据并生成配置，确认模型服务与运行预算后启动评测，最后校验并汇总结果。

### 实验流程

#### 1. 安装

使用 Python 3.11 或更新版本。以下命令在仓库根目录、Bash 或兼容终端中执行。

```bash
git clone https://github.com/xuyang-liu16/MemFolder.git
cd MemFolder
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m memfolder --help
python -m memfolder run examples/experiments/offline-demo.json
python -m memfolder verify build/experiments/offline-demo
```
离线示例使用合成对话在本地检查流程，指标标记为 `test_only`。运行 RecordFolder 和 ContextFolder 还需安装：

```bash
python -m pip install -e ".[algorithms,contextfolder,evaluation]"
```
#### 2. 下载数据

实验需要**基准的对话与问答数据**以及**待压缩的记忆库**。首次运行 LoCoMo 时，可下载下面的对话数据，并保留模板中的 `history-initializer`，按每个对话轮次构建一个节点。开展 Mem0 或 MemOS 实验时，应换成单独生成的记忆库。

```bash
mkdir -p data/locomo
curl -fL https://raw.githubusercontent.com/snap-research/locomo/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376/data/locomo10.json \
  -o data/locomo/locomo10.json
```
| 基准 | 下载地址 | 数据插件与输入文件 |
| --- | --- | --- |
| LoCoMo | [官方发布](https://github.com/snap-research/locomo) | `locomo-dataset`：`locomo10.json` |
| LongMemEval | [官方数据](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) | `longmemeval-dataset`：如 `longmemeval_s_cleaned.json` |
| PersonaMem v1，32K | [官方数据](https://huggingface.co/datasets/bowen-upenn/PersonaMem) | `personamem-dataset`：`questions_32k.csv` 和 `shared_contexts_32k.jsonl` |
| M3-Bench robot/web | [问答标注](https://github.com/ByteDance-Seed/m3-agent/tree/master/data/annotations)、[记忆图](https://huggingface.co/datasets/ByteDance-Seed/M3-Bench/tree/main/memory_graphs) | `m3-dataset`：`robot.json` 或 `web.json`，以及逐视频配置的记忆加载器 |

<details>
<summary><b>LongMemEval、PersonaMem 和 M3 标注的下载命令</b></summary>

只下载准备使用的基准：

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
将 [dataset-components.json](examples/experiments/dataset-components.json) 中对应条目作为实验的 `dataset` 配置。PersonaMem 提供对话顺序，M3 的 clip 序号表示可见性；LoCoMo 模板默认的 `event-time-features` 需要已解析的事件时间。这两类输入须先配置语义明确的顺序／时间适配器，仅替换数据集配置还不够，见[基准配置](skills/memfolder-exp/references/experiment-config.md#benchmark-time-and-reader-scope)。PersonaMem 还需填写 `contexts_path`，M3 还需填写 `memory_loaders` 和 `variant`。下载 M3 问答标注及对应记忆图，并保留媒体路径与 clip 截止范围。完整多模态评测还需配置 [M3-Agent 控制器](https://github.com/ByteDance-Seed/m3-agent#control)。

这些加载器使用基准原始格式。MemForest 的 `dataset/longmemeval.json` 和 `dataset/personamem_32k.json` 使用转换后的 LoCoMo 风格格式，需要匹配的适配器。数据版本、记忆快照和评分协议需配套使用。

</details>

<details>
<summary><b>使用预构建的 Mem0 记忆库</b></summary>

[MemForest_data](https://huggingface.co/datasets/Celina-love-sweet/MemForest_data) 提供原始 Mem0 记忆库：`LoCoMo/locomo.tar.gz`、`LongMemEval/longmemeval.tar.gz` 和 `PersonaMem/personamem.tar.gz`。压缩对比实验使用这些原始库作为输入，带 `keep30/50/70` 的压缩包保存已压缩的基线结果。以 LoCoMo 为例：

```bash
mkdir -p data/memforest
curl -fL https://huggingface.co/datasets/Celina-love-sweet/MemForest_data/resolve/37452b97d0b317a69bace34951caaf25a9949fec/LoCoMo/locomo.tar.gz \
  -o data/memforest/locomo.tar.gz
tar -xzf data/memforest/locomo.tar.gz -C data/memforest
```
压缩包约 46 MB。保留原始记忆库不变。在 `build/configs/` 下的实验配置中，将 `initializer` 替换为以下内容，对应 LoCoMo 的第一个样本 `conv-26`：

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
用户标识遵循 MemForest 的 `<speaker>_<sample index>` 命名方式，使用前需核对所选库中的实际值。扩展到更多样本时，为每个样本添加映射，并同步修改 `dataset.parameters.sample_ids`。通过 `selectors` 筛选每个样本对应的用户，并从离线快照导入 collection 中的 `storage.sqlite`。

导入记忆后使用答案评分。节点具有原始对话的证据 ID 映射时，可启用 `evidence-recall`，其余情况从 evaluator 中移除该项。其他记忆库可使用 `mem0`、`mem0-qdrant`、`memos`、`memos-cube` 和 `m3` 插件。`history-initializer` 按对话轮次构建节点。需要框架自身的记忆提取与更新时，使用上游 [Mem0](https://github.com/mem0ai/mem0)、[MemOS](https://github.com/MemTensor/MemOS) 或 [M3-Agent](https://github.com/ByteDance-Seed/m3-agent) 流程。

</details>

#### 3. 配置 LoCoMo 实验

将两个模板复制为本地配置：

```bash
mkdir -p build/configs
cp examples/experiments/recordfolder-template.json build/configs/locomo-recordfolder.json
cp examples/experiments/contextfolder-template.json build/configs/locomo-contextfolder.json
export MEMFOLDER_PROVIDER_KEY="YOUR_API_KEY"
```
将**两个文件**的 `dataset` 部分替换为：

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
这里先选一个对话。将 `sample_ids` 设为 `[]` 可运行全部十个对话。`preserve_unknown` 保留证据编号无法解析的问题，并将其证据召回标为未评分。显式 UTC 偏移用于统一解释没有时区的日期。

| 配置项 | 需要填写的内容 |
| --- | --- |
| `services.chat.parameters`、`services.grounding.parameters`、`services.judge.parameters` | 将示例地址及所有 `REPLACE_*` 模型名、版本替换成实际服务配置。 |
| `services.embeddings.parameters.provider.parameters` | 填写向量服务地址、模型名和版本。 |
| `compression.features[0].parameters.space` | 与向量服务保持相同模型和版本，并填写实际向量维度。 |
| `run.budgets[0].ratio` | 节点**保留比例**：`0.5` 表示缩减 50%，`0.3` 表示缩减 70%。 |
| `output_dir` | 每次实验使用新目录。模板默认为 `../../build/experiments/recordfolder-001` 和 `../../build/experiments/contextfolder-001`。 |

所有路径以配置文件所在目录为基准。两个模板使用同一输入，并评测原始与压缩后的记忆。对比时保持模型、样本、检索和评分设置一致。ContextFolder 的 writer 默认使用 **0.8 token 保留目标**、最多 **3 轮**和 **1.15 预算容差**。当前空／非法事实规划会进入未经盲验证、缺少长度保护的摘要回退；扩大实验前应检查 fallback 数量和实际保存长度。目标用于指导修订，结果报告最终输出的实际 token 保留比例。

<details>
<summary><b>向量检索与论文设置</b></summary>

入门模板默认使用词项匹配 top-10 检索、公共 MemForest LLM judge 和 MemOS 格式输出。向量检索与压缩阶段的语义特征分别配置。需要向量检索时，在 `reader.parameters` 下加入以下内容，并保留原有 answerer：

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
同时在 `compression.wrapper.parameters` 下加入 `embedding_provider`，为改写后的节点重新生成向量：

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
两处 `space` 与语义特征提供器保持一致，并填写模型实际维度。两个 reader 均使用 `memforest-qa-prompt`；`contextfolder-qa-prompt` 只是行为相同的兼容别名。

所有内置普通摘要合并使用同一份 MemForest merge 模板。各方法、各基准的最终 QA 和 judge 均使用 `memforest-qa-prompt`、`memforest-judge`，judge 返回 JSON `CORRECT`／`WRONG`。LLMLingua-2 和 BabelTele 保留各自的压缩逻辑；ContextFolder 内部的事实提取、编码与恢复检查独立于最终评测。[提示词协议](docs/zh-CN/PROMPT_PROTOCOL.md)记录具体模板、哈希和缓存身份。

复现论文表格还需匹配原始记忆快照、模型版本、检索设置和评分覆盖。LoCoMo F1 可作为单独指标配置；MemForest judge 与各基准原始评分协议具有不同身份。使用 Mem0 原生评测流程时，应为导入的记忆库显式配置相应检索器。

</details>

#### 4. 运行并查看结果

```bash
python -m memfolder run build/configs/locomo-recordfolder.json
python -m memfolder verify build/experiments/recordfolder-001
python -m memfolder run build/configs/locomo-contextfolder.json
python -m memfolder verify build/experiments/contextfolder-001
python -m memfolder case build/experiments/recordfolder-001 \
  --dataset-id locomo --sample-id conv-26 --question-id conv-26:0 \
  --output build/cases/locomo-recordfolder-q0
```
这些实验会调用配置的模型 API。输出目录中的 `result.json` 包含原始/压缩后分数及逐样本统计，`run.manifest.json` 保存执行状态，样本子目录保存记忆快照和预测。`verify` 校验结果文件的完整性，`case` 导出一道问题用于检查。

方法与随机种子的批量对比可参照 [offline-matrix.json](examples/experiments/offline-matrix.json)，执行 `python -m memfolder matrix CONFIG.json`。`--resume` 复用校验通过的**已完成**实验。运行失败后，保留已有文件并使用新输出目录重试。

<details>
<summary><b>基线配置</b></summary>

[examples/recipes/](examples/recipes/) 提供各方法的压缩配置。复制已配置好的 RecordFolder 实验，将其中的 `compression.planner` 和 `compression.operator` 替换为所选方法的组件。每个所需特征只配置一次，保留 wrapper、模型服务及公共 QA/judge。recipe 是组件片段，不能直接作为完整实验配置运行。

- [MemForest 范围预算分配](examples/recipes/memforest-mst-capacity.json)版本需设置 `run.mode: "repeat"`，并在语义编码器之外使用 `aggregation: "latest"` 的 `event-time-features`。[逐簇向上取整](examples/recipes/memforest-mst-cluster-ceil.json)版本通过 Python API 配合 `resolve_memforest_budget` 运行。M3 的 average-linkage proxy 是单独命名的适配版本。
- [文本 ToMe](skills/memfolder-exp/references/tome.md)需要 `run.mode: "repeat"`、时间连续二分，以及同一声明 cosine 空间中的初始**内容绑定向量**。使用 `current-embeddings` 替换模板的 `semantic-encoder`，避免追加出两个 `semantic` 特征。纯文本 `history-initializer` 不生成初始向量，须在第一次合并前用显式 initializer 准备，或使用已验证的库；最终 wrapper 的向量刷新不能补齐这一步。历史交错分区版本名为 `tome-bsm`。
- [LLMLingua-2](skills/memfolder-exp/references/llmlingua2.md)压缩最终节点文本，默认保留比例为 `0.55`。已恢复的 LongMemEval service、全量文本向量刷新及显式 Mem0 owner 映射仍可分别配置。
- [record_then_context.py](examples/record_then_context.py) 将 ContextFolder 应用于其他压缩方法输出的最终节点，保持节点数量并改写文本。

</details>

<a id="main-results"></a>
<a id="full-results"></a>

## 全部结果

以下表格和图片保留论文报告的结果及原始方法、评测身份。仓库中新运行的
实验单独记录分数和协议 manifest；更新提示词或方法不会改写这些历史数值。

### RecordFolder：节点压缩

**All** 表示总体准确率，**Avg.** 表示跨基准平均准确率，**%** 表示相对未压缩系统的平均准确率保留比例。

#### Mem0 上的节点压缩

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

#### MemOS 上的节点压缩

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

#### M3-Bench 上的节点压缩

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

### ContextFolder：上下文压缩

<p align="center">
<a href="docs/assets/paper-context-results.pdf"><img src="docs/assets/paper-context-results.png" alt="在缩减 50% 节点后，比较 LoCoMo、LongMemEval 和 M3-Bench-robot 的准确率与每个节点的 token 数。" width="1000"></a>
</p>

缩减 50% 节点后，ContextFolder 相比单独使用 RecordFolder，进一步将 LoCoMo 和 LongMemEval 的每个节点的 token 数降低 **40.3%** 和 **37.9%**，最终准确率分别为 **56.6%** 和 **51.8%**。越靠左上越好，颜色表示节点压缩方法，标记表示上下文压缩方法。

### 检索效率

<p align="center">
<a href="docs/assets/paper-retrieval-efficiency.pdf"><img src="docs/assets/paper-retrieval-efficiency.png" alt="五个设置下的平均检索时延与 P95 时延，横轴依次为保留 100%、50%、30% 节点。" width="1000"></a>
</p>

保留 30% 节点时，五个设置的平均检索加速比为 **1.88–5.34×**。实线表示平均时延，虚线表示 P95 时延。横轴表示节点**保留比例**，上面的表格表示节点**缩减比例**。
