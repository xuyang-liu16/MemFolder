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
<img src="assets/paper-intro.png" alt="记忆增长带来检索和上下文开销，RecordFolder 减少节点数量，ContextFolder 缩短每个检索单元的文本。" width="1000">
</p>

> **TLDR:** 随着智能体记忆不断积累，节点检索和上下文处理的开销持续增加。
> 为降低这些开销，我们提出 **MemFolder**，包含用于节点压缩的 **RecordFolder** 和用于上下文压缩的 **ContextFolder**。

<a id="news"></a>

## 🔥 最新动态

- **`2026.11.20`** 新版[方法概览](#overview)展示了 MemFolder 如何合并记忆记录、缩短每次查询取回的文本。[实验指南](#quick-start)提供了在 LoCoMo 上运行这两个步骤的示例。

<a id="highlights"></a>

## 🎯 核心亮点

- **记录数减半。** 在 LoCoMo、LongMemEval 和 PersonaMem 上，RecordFolder 保留了 Mem0 原始平均准确率的 **99.0%**，相同记录数下 MemForest 保留 **97.1%**。
- **每条记录更短。** RecordFolder 将记录数减半后，ContextFolder 让每条记录的平均 token 数在 LoCoMo 上再降 **40.3%**，在 LongMemEval 上再降 **37.9%**。
- **检索更快。** 保留 30% 的记录时，五个评测设置下的检索加速比为 **1.88 至 5.34 倍**，其中 LongMemEval 的加速最大。

<a id="overview"></a>

## ✨ 方法概览

<p align="center">
<img src="assets/paper-overview.png" alt="RecordFolder 通过渐进式锚点选择、实体感知亲和度和时间链完成分组。ContextFolder 规划事实、生成编码并验证盲恢复结果。" width="1000">
</p>

MemFolder 包含两个模块：**RecordFolder** 选择互补锚点，结合实体感知亲和度与时间链整合相关节点，减少检索单元。**ContextFolder** 使用规划器确定事实优先级、压缩器生成紧凑编码，再通过盲验证器检查事实恢复并指导迭代修订。

<a id="usage"></a>
<a id="quick-start"></a>

## 使用说明

对于 Coding Agent 用户，可以发送以下指令，按仓库内的 [memfolder-exp skill](skills/SKILL.md) 开始实验：

> 请按 `https://github.com/xuyang-liu16/MemFolder` 中的 `skills/SKILL.md`，使用我配置的模型服务运行 LoCoMo 小规模实验，对比保留 50% 节点的 RecordFolder 和 ContextFolder。

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
```

运行 RecordFolder 和 ContextFolder 还需安装：

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

将 [dataset-components.json](examples/experiments/dataset-components.json) 中对应的条目作为实验的 `dataset` 配置。PersonaMem 还需填写 `contexts_path`，M3 还需填写 `memory_loaders` 和 `variant`。下载 M3 问答标注及对应记忆图，并保留媒体路径与 clip 截止范围。完整多模态评测还需配置 [M3-Agent 控制器](https://github.com/ByteDance-Seed/m3-agent#control)。

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

所有路径以配置文件所在目录为基准。两个模板使用同一输入，并评测原始与压缩后的记忆。对比时保持模型、样本、检索和评分设置一致。ContextFolder 的 writer 默认使用 **0.8 token 保留目标**、最多 **3 轮**和 **1.15 预算容差**。目标用于指导修订，结果报告最终输出的实际 token 保留比例。

<details>
<summary><b>向量检索与论文设置</b></summary>

入门模板默认使用词项匹配 top-10 检索、MemForest judge 准确率评分和 MemOS 格式输出。向量检索与压缩阶段的语义特征分别配置。需要向量检索时，在 `reader.parameters` 下加入以下内容，并保留原有 answerer：

```json
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
```

同时在 `compression.wrapper.parameters` 下加入 `embedding_provider`，为改写后的节点重新生成向量：

```json
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
```

两处 `space` 与语义特征提供器保持一致，并填写模型实际维度。两个 reader 均使用 `memforest-qa-prompt`，评测使用 `memforest-judge`。

复现论文表格时，需匹配原始记忆快照、模型版本、提示词、检索设置和评分协议。入门模板使用统一的 MemForest judge，LoCoMo F1 是可选的独立指标。使用 Mem0 原生评测流程时，应为导入的记忆库显式配置相应检索器。

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

方法与随机种子的批量对比可参照 [matrix-template.json](examples/experiments/matrix-template.json)，执行 `python -m memfolder matrix CONFIG.json`。`--resume` 复用校验通过的**已完成**实验。运行失败后，保留已有文件并使用新输出目录重试。

<details>
<summary><b>基线配置</b></summary>

[examples/recipes/](examples/recipes/) 提供各方法的压缩配置。复制已配置好的 RecordFolder 实验，将其中的 `compression.planner` 和 `compression.operator` 替换为所选方法的组件，合并所需特征与语义编码器，并保留 wrapper 和模型服务。

- [MemForest 范围预算分配](examples/recipes/memforest-mst-capacity.json)版本需设置 `run.mode: "repeat"`，并在语义编码器之外使用 `aggregation: "latest"` 的 `event-time-features`。[逐簇向上取整](examples/recipes/memforest-mst-cluster-ceil.json)版本通过 Python API 配合 `resolve_memforest_budget` 运行。M3 的 average-linkage proxy 是单独命名的适配版本。
- 文本 ToMe 同样需要 `run.mode: "repeat"`，按时间连续二分，交错分区版本名为 `tome-bsm`。
- LLMLingua-2 压缩最终节点文本，默认保留比例为 `0.55`。
- [record_and_context_compression.py](examples/record_and_context_compression.py) 将 ContextFolder 应用于其他压缩方法输出的最终节点，保持节点数量并改写文本。

</details>

## 📩 联系方式

如有论文或代码相关问题，欢迎发邮件给刘旭洋（<liuxuyang@stu.scu.edu.cn>）。
