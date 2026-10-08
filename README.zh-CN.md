<div align="center">

# MemFolder

**Structure-Guided Memory Folding for Efficient Agent Memory Management**

**结构引导的记忆折叠：面向智能体的高效记忆管理**

更少的检索单元 · 更短的上下文 · 经过核验的记忆编码

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-173453?logo=githubactions&logoColor=white)](https://github.com/xuyang-liu16/MemFolder/actions/workflows/tests.yml) [![Python](https://img.shields.io/badge/Python-3.11%2B-173453?logo=python&logoColor=white)](pyproject.toml) [![Docs](https://img.shields.io/badge/Docs-Module_guides-247D7A)](#documentation)

[English](README.md) | **简体中文**

[最新动态](#news) · [核心亮点](#highlights) · [使用说明](#usage) · [全部结果](#full-results)

</div>

<a id="news"></a>

## 🔥 最新动态

- **2026-10-08：** 模块化开发版本已补充实验配置模板、论文插图、完整主结果表，以及中英文使用指南。

<a id="highlights"></a>

## 📌 核心亮点

- **两个阶段，共享分组结构。** RecordFolder 将相关记忆整合为更少的检索单元；ContextFolder 复用这些分组，将事实编码为紧凑文本，并通过事实恢复检查指导修订。
- **高性能的记录压缩。** 在 Mem0 上减少 50% 记录后，RecordFolder 在 LoCoMo、LongMemEval 和 PersonaMem 三个基准上仍保留未压缩平均性能的 **99.0%**。
- **更短的检索上下文。** 在同样减少 50% 记录的条件下，ContextFolder 相比仅使用 RecordFolder，进一步将 LoCoMo 和 LongMemEval 的每条记录 token 数降低 **40.3%** 和 **37.9%**。
- **更快的检索。** 仅保留 30% 记录时，论文的五个评测设置中最高取得 **5.34×** 的平均检索加速。
- **可组合的研究框架。** 通过配置替换分组策略、上下文编码、记忆封装和评测组件；支持 Mem0、MemOS、M3 集成、多种压缩基线和可追踪的实验产物。

<div align="center">
<a href="docs/assets/paper-intro.png"><img src="docs/assets/paper-intro.png" alt="所提供论文的图 1：记忆管理的两个成本瓶颈、单轴压缩方法的局限，以及 MemFolder 同时折叠记录数量和上下文长度。" width="1100"></a>
</div>

**MemFolder 摘要图（论文图 1）。** 同时减少存储的记录数量与每个检索单元的文本长度。上述定量亮点来自论文报告，详细比较见本页末尾。

<a id="usage"></a>
<a id="quick-start"></a>

## 🛠 使用说明

### 1. 安装

需要 **Python 3.11+**。核心包不强制依赖第三方库。

```bash
git clone https://github.com/xuyang-liu16/MemFolder.git
cd MemFolder
python -m pip install -e .
```

### 2. 运行离线示例

```bash
python -m memfolder run examples/experiments/offline-demo.json
python -m memfolder verify build/experiments/offline-demo
```

示例贯通“加载 → 压缩 → 原生输出 → 检索 → 回答 → 评测”，并包含未压缩对照和案例轨迹。示例使用合成历史与回显上下文的回答器，无需模型、API 密钥或网络访问；标为 `test_only` 的分数仅用于验证流程。

运行多方法、多随机种子的实验矩阵：

```bash
python -m memfolder matrix examples/experiments/offline-matrix.json
```

复用已经完成且通过校验的运行：

```bash
python -m memfolder run examples/experiments/offline-demo.json --resume
```

产物保存在 `build/experiments/` 下。校验会检查源数据指纹、配置与输出完整性。

### 3. 接入真实记忆与模型

```bash
python -m pip install -e ".[algorithms,contextfolder,qdrant,evaluation]"
```

从 [RecordFolder 模板](examples/experiments/recordfolder-template.json)或 [ContextFolder 模板](examples/experiments/contextfolder-template.json)开始。运行前，替换数据和输出路径、服务地址、模型名称、版本标识及向量维度，并通过环境变量 `MEMFOLDER_PROVIDER_KEY` 提供密钥。模板中的 `REPLACE_*` 与 `api.example.invalid` 均为占位值。

完成模板配置后运行：

```bash
python -m memfolder run examples/experiments/recordfolder-template.json
python -m memfolder run examples/experiments/contextfolder-template.json
```

已有记忆库可通过[原生加载器](docs/LOADING.md)与 `bank-initializer` 接入。完整组装方式见[实验指南](docs/EXPERIMENTS.md)，Mem0、MemOS 和 M3 的格式见[封装器指南](docs/WRAPPERS.md)。基准问题与标准答案不参与记忆压缩。

<a id="compose-an-experiment"></a>

### 4. 组合不同方法

记录分组与上下文编码可以独立替换。例如，在完整配置中修改以下字段，即可使用 ToMe 分组和 ContextFolder 编码：

```json
{
  "compression": {
    "planner": {"plugin": "tome"},
    "operator": {"plugin": "contextfolder-operator"}
  },
  "run": {
    "mode": "repeat",
    "budgets": [{"unit": "nodes", "ratio": 0.5}]
  }
}
```

这只是配置片段；请保留模板中的特征、封装器、服务、Reader 和 Evaluator。`ratio: 0.5` 表示**记录数量预算**；ContextFolder 的 token 目标另行配置，且是软约束。ToMe 文本压缩采用多轮处理，并为改写后的文本刷新向量。完整示例见 [ToMe + ContextFolder 配方](examples/recipes/tome-with-contextfolder.json)。

设置 `run.evaluate_source: true`，可使用相同 Reader 和 Evaluator 运行未压缩对照。比较压缩方法时，应固定检索设置、提示词与评分方式。

<details>
<summary><b>论文方法与代码架构</b></summary>

<a id="paper"></a>

<div align="center">
<a href="docs/assets/paper-overview.pdf"><img src="docs/assets/paper-overview.png" alt="论文方法主图：RecordFolder 使用互补锚点和实体感知时序分组；ContextFolder 规划事实、压缩分组并核验事实恢复。" width="1100"></a>
</div>

论文中的 RecordFolder 和 ContextFolder 通过独立的 Planner、Operator 组件实现。ContextFolder 也能接收其他整合方法产生的分组。论文公开链接、作者名单与引用信息将在确定后补充。

<a id="architecture"></a>

<div align="center">
<img src="docs/assets/memfolder-architecture.svg" alt="代码架构：通过配置组装加载器、特征、Planner、Operator、记忆封装器、Reader 和 Evaluator，观察器覆盖各处理阶段。" width="1100">
</div>

**Planner** 决定压缩哪些内容；**Operator** 执行压缩；**Wrapper** 保留原生存储和图语义；**Reader 与 Evaluator** 负责检索、回答和评分。标准答案仅进入 Evaluator。每种角色都可以由独立插件提供。

| 组件 | 已包含的实现 |
| --- | --- |
| 论文方法 | RecordFolder、ContextFolder |
| 记录压缩基线 | ToMe、MemForest、DART 记忆适配、StreamMeCo 图压缩、RandomMerge、RandomPrune、KMeansMerge、KMeansPrune |
| 评测基准 | LoCoMo、LongMemEval、PersonaMem、M3-Bench robot/web |
| 记忆加载与封装 | Mem0、MemOS、M3 |
| 实验工具 | 配置矩阵、未压缩对照、产物校验、恢复运行、观察器与案例查询 |

组件组合需满足图结构、时间、模态和向量空间要求。StreamMeCo 对应其图压缩阶段；MemForest 的 MST 实现与历史 M3 代理版本提供独立配方。具体范围见[兼容性](docs/COMPATIBILITY.md)和[方法变体](docs/COMPRESSION.md)。

</details>

<a id="extend-one-module"></a>

### 5. 扩展组件与查看过程

实现相应接口，以及返回 `PluginSpec` 的工厂函数，即可添加完整的 Planner、Operator 或其中一个子组件：

```json
{
  "plugin": "my_module:build",
  "parameters": {"my_parameter": 0.5}
}
```

安装的插件包也可注册 `memfolder.plugins` 入口。组装器会检查角色、API 版本和能力声明。现有示例包括[新基准](examples/plugins/new_benchmark)、[锚点选择](examples/plugins/recency)、[原生输出](examples/plugins/native_writer)和[回答或评测组件](examples/plugins/experiment_components)。详见[扩展指南](docs/EXTENDING.md)。

<a id="inspect-the-data-flow"></a>

启用案例记录与只读观察器：

```json
{
  "capture": {"profile": "cases", "text_policy": "omit"},
  "observers": [{"plugin": "event-report-observer", "required": false}]
}
```

使用 [`FileRunReader`](docs/ANALYSIS.md)，可以沿源记忆追踪分组、压缩、检索与回答过程，也可按来源标识比较不同运行。缺失的观察项会明确标记。捕获策略控制公开分析投影；私有运行产物仍可能包含原始记忆与评测数据。

<a id="documentation"></a>

### 文档导航

| 需求 | 指南 |
| --- | --- |
| 运行实验或参数扫描 | [实验](docs/EXPERIMENTS.md) |
| 理解压缩方法与变体 | [压缩](docs/COMPRESSION.md) |
| 加载记忆或选择评测协议 | [加载](docs/LOADING.md) · [基准](docs/BENCHMARKS.md) |
| 导出到记忆框架 | [封装器](docs/WRAPPERS.md) |
| 添加组件或查看案例 | [扩展](docs/EXTENDING.md) · [分析](docs/ANALYSIS.md) |
| 检查接口与兼容组合 | [契约](docs/CONTRACTS.md) · [兼容性](docs/COMPATIBILITY.md) |
| 查看论文全部分类分数 | [完整结果表](docs/PAPER_RESULTS.md) |

<details>
<summary><b>开发、来源与许可</b></summary>

安装可选依赖后运行：

```bash
python tools/fetch_test_sources.py
python tools/check_contracts.py
```

源代码获取工具会核验固定的上游版本与校验和，下载内容保存在被 Git 忽略的 `build/` 下。缺少对应源文件时，可选集成检查会明确跳过；历史归档检查需要单独提供归档。CI 在 Python 3.11 和 3.12 上运行检查与离线流程。完整论文分数复现、在线后端与多模态推理有各自的[验证范围](docs/EXPERIMENTS.md#验证范围)。

[方法](docs/METHOD_PROVENANCE.json)、[基准](docs/BENCHMARK_SOURCES.json)和[封装器](docs/WRAPPER_SOURCES.json)均记录了来源。RecordFolder、ContextFolder 分别是早期 G1S、V12 实现的正式名称。[第三方声明](docs/THIRD_PARTY_NOTICES.md)保留了来源与改编说明，包括 StreamMeCo 的 MIT 声明。历史源代码贡献的统一发布许可证尚未最终确定，本版本不会重新授予其许可。

</details>

<a id="main-results"></a>
<a id="full-results"></a>

## 📊 全部结果

以下展示论文的全部主结果比较：Mem0 的 30% / 50% / 70% 记录缩减，MemOS 与 M3-Agent 的 50% / 70% 记录缩减，以及上下文压缩和检索效率结果。数值来自论文稿件；本次代码重构并未独立复现全部论文分数。[完整分类指标表](docs/PAPER_RESULTS.md)与[原始数值及来源](docs/assets/paper-results-data.json)可供核对。

### RecordFolder：记录压缩

表格报告各基准的总体准确率；平均准确率与性能保留率均沿用论文原值。**性能保留率**指压缩后平均准确率相对于对应未压缩系统的比例。加粗行标识本文方法。**缩减 70% 记录，即保留 30% 记录**。

#### Mem0 · 缩减 50% 记录

| 方法 | LoCoMo | LongMemEval | PersonaMem | 平均准确率 | 性能保留率 (%) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Mem0（未压缩） | 60.2 | 55.2 | 67.9 | 61.1 | 100.0 |
| Random Pruning | 43.1 | 43.6 | 64.3 | 50.3 | 82.3 |
| KMeans | 46.8 | 47.0 | 65.2 | 53.0 | 86.7 |
| DART | 51.9 | 41.4 | 64.3 | 52.5 | 85.9 |
| Random Merging | 51.4 | 48.6 | 64.5 | 54.8 | 89.7 |
| ToMe | 54.7 | 50.8 | 65.9 | 57.1 | 93.5 |
| MemForest | 58.4 | 51.8 | 67.7 | 59.3 | 97.1 |
| **MemFolder (RecordFolder)** | **59.3** | **55.0** | **67.2** | **60.5** | **99.0** |

<details>
<summary><b>Mem0 · 30 / 70% 记录缩减</b></summary>

#### Mem0 · 缩减 30% 记录

| 方法 | LoCoMo | LongMemEval | PersonaMem | 平均准确率 | 性能保留率 (%) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Mem0（未压缩） | 60.2 | 55.2 | 67.9 | 61.1 | 100.0 |
| Random Pruning | 50.8 | 50.8 | 64.5 | 55.4 | 90.7 |
| KMeans | 56.8 | 52.0 | 65.7 | 58.2 | 95.3 |
| DART | 57.4 | 48.8 | 66.6 | 57.6 | 94.3 |
| Random Merging | 56.2 | 50.8 | 65.2 | 57.4 | 93.9 |
| ToMe | 57.2 | 51.2 | 66.4 | 58.3 | 95.4 |
| MemForest | 58.5 | 54.2 | 66.6 | 59.7 | 97.7 |
| **MemFolder (RecordFolder)** | **61.7** | **55.2** | **67.7** | **61.5** | **100.7** |

#### Mem0 · 缩减 70% 记录

| 方法 | LoCoMo | LongMemEval | PersonaMem | 平均准确率 | 性能保留率 (%) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Mem0（未压缩） | 60.2 | 55.2 | 67.9 | 61.1 | 100.0 |
| Random Pruning | 33.1 | 28.6 | 63.7 | 41.8 | 68.4 |
| KMeans | 36.7 | 34.8 | 63.8 | 45.1 | 73.8 |
| DART | 43.6 | 30.6 | 61.8 | 45.3 | 74.1 |
| Random Merging | 50.7 | 46.2 | 64.0 | 53.6 | 87.7 |
| ToMe | 52.7 | 49.6 | 65.7 | 56.0 | 91.7 |
| MemForest | 54.4 | 52.2 | 64.4 | 57.0 | 93.3 |
| **MemFolder (RecordFolder)** | **57.1** | **55.0** | **64.9** | **59.0** | **96.6** |

</details>

<details>
<summary><b>MemOS · 50 / 70% 记录缩减</b></summary>

#### MemOS · 缩减 50% 记录

| 方法 | LoCoMo | LongMemEval | PersonaMem | 平均准确率 | 性能保留率 (%) |
| --- | ---: | ---: | ---: | ---: | ---: |
| MemOS（未压缩） | 79.0 | 74.0 | 60.3 | 71.1 | 100.0 |
| Random Pruning | 65.3 | 47.8 | 55.9 | 56.3 | 79.2 |
| KMeans | 67.8 | 47.6 | 54.7 | 56.7 | 79.7 |
| DART | 70.1 | 40.8 | 53.7 | 54.9 | 77.2 |
| Random Merging | 73.3 | 59.6 | 56.2 | 63.0 | 88.7 |
| ToMe | 71.0 | 61.8 | 57.9 | 63.6 | 89.4 |
| MemForest | 76.0 | 60.0 | 54.8 | 63.6 | 89.5 |
| **MemFolder (RecordFolder)** | **75.3** | **64.2** | **54.7** | **64.7** | **91.0** |

#### MemOS · 缩减 70% 记录

| 方法 | LoCoMo | LongMemEval | PersonaMem | 平均准确率 | 性能保留率 (%) |
| --- | ---: | ---: | ---: | ---: | ---: |
| MemOS（未压缩） | 79.0 | 74.0 | 60.3 | 71.1 | 100.0 |
| Random Pruning | 54.9 | 30.2 | 52.8 | 46.0 | 64.7 |
| KMeans | 57.3 | 31.6 | 52.6 | 47.2 | 66.4 |
| DART | 59.8 | 26.8 | 48.9 | 45.2 | 63.5 |
| Random Merging | 68.1 | 53.8 | 54.0 | 58.6 | 82.5 |
| ToMe | 67.4 | 53.4 | 55.4 | 58.7 | 82.6 |
| MemForest | 70.7 | 50.0 | 55.5 | 58.7 | 82.6 |
| **MemFolder (RecordFolder)** | **71.3** | **54.4** | **55.2** | **60.3** | **84.8** |

</details>

<details>
<summary><b>M3-Agent · 50 / 70% 记录缩减</b></summary>

#### M3-Agent · 缩减 50% 记录

| 方法 | Robot | Web | 平均准确率 | 性能保留率 (%) |
| --- | ---: | ---: | ---: | ---: |
| M3-Agent（未压缩） | 30.3 | 47.9 | 39.1 | 100.0 |
| Random Pruning | 28.1 | 41.2 | 34.7 | 88.7 |
| KMeans | 29.2 | 43.9 | 36.6 | 93.6 |
| DART | 29.1 | 43.1 | 36.1 | 92.3 |
| StreamMeCo | 30.6 | 44.7 | 37.7 | 96.2 |
| Random Merging | 30.8 | 44.6 | 37.7 | 96.4 |
| ToMe | 30.9 | 46.1 | 38.5 | 98.5 |
| MemForest | 31.6 | 46.5 | 39.0 | 99.7 |
| **MemFolder (RecordFolder)** | **31.0** | **48.2** | **39.6** | **101.3** |

#### M3-Agent · 缩减 70% 记录

| 方法 | Robot | Web | 平均准确率 | 性能保留率 (%) |
| --- | ---: | ---: | ---: | ---: |
| M3-Agent（未压缩） | 30.3 | 47.9 | 39.1 | 100.0 |
| Random Pruning | 27.7 | 37.3 | 32.5 | 83.1 |
| KMeans | 28.9 | 39.1 | 34.0 | 87.0 |
| DART | 27.2 | 39.2 | 33.2 | 84.9 |
| StreamMeCo | 28.4 | 41.9 | 35.1 | 89.8 |
| Random Merging | 30.4 | 43.2 | 36.8 | 94.1 |
| ToMe | 30.6 | 45.7 | 38.2 | 97.7 |
| MemForest | 30.7 | 46.3 | 38.5 | 98.5 |
| **MemFolder (RecordFolder)** | **31.4** | **48.7** | **40.1** | **102.6** |

</details>

### ContextFolder：上下文压缩

<div align="center">
<a href="docs/assets/paper-context-results.pdf"><img src="docs/assets/paper-context-results.png" alt="论文上下文压缩结果：在缩减 50% 记录后，比较 LoCoMo、LongMemEval 和 M3-Bench-robot 的准确率与每条记录 token 数。" width="1100"></a>
</div>

**固定缩减 50% 记录，比较准确率与每条记录的 token 数。** 越靠左上越好；颜色表示记录压缩方法，标记表示上下文压缩方法。ContextFolder 在 RecordFolder 的基础上，进一步将 LoCoMo 和 LongMemEval 的每条记录 token 数降低 **40.3%** 和 **37.9%**，最终准确率分别为 **56.6%** 和 **51.8%**。这里的 token 降幅以仅使用 RecordFolder 为参照。

### 检索效率

<div align="center">
<a href="docs/assets/paper-retrieval-efficiency.pdf"><img src="docs/assets/paper-retrieval-efficiency.png" alt="五个设置下的平均检索时延与 P95 时延，横轴依次为保留 100%、50%、30% 记录；论文报告最高 5.34 倍平均检索加速。" width="1100"></a>
</div>

**平均检索时延与 P95 时延。** 保留 30% 记录时，论文在五个设置中报告了 **1.88–5.34×** 的平均检索加速。图中横轴表示**保留比例**，上面的表格表示**缩减比例**。点击图片可查看原始 PDF。

论文表格与上下文结果图的部分 LongMemEval 参考分数存在差异；这里分别保留原稿数值，具体见[来源一致性说明](docs/PAPER_RESULTS.md#source-consistency)。
