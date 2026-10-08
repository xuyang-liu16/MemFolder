# 压缩方法

[文档索引](README.md) · [English](../COMPRESSION.md)

MemFolder 关注长期记忆的两项开销：搜索大量记录，以及读取较长的检索文本。RecordFolder 把相关记录整合为更少的单元；ContextFolder 再压缩每组内容，并检查重要事实能否从编码中恢复。

## RecordFolder：减少记录数量

RecordFolder 先选择代表性记录作为锚点，再利用语义、实体和事件顺序形成分组。配置的文本处理组件负责整合每组内容。

实现包含以下步骤：

1. 根据局部密度和多样性选择锚点。
2. 将记录分配给最近的锚点，形成初始分组。
3. 在较早的记录中寻找候选连接，结合实体与语义相似度评分。
4. 保留优于原锚点分配的连接，通过匹配形成时间链。
5. 将时间链分配给锚点组，生成各组的输出记录。

[RecordFolder 实验模板](../../examples/experiments/recordfolder-template.json)已配置所需特征与服务。以下阶段可以单独替换：

| 配置字段 | 默认插件 | 作用 |
| --- | --- | --- |
| `anchors` | `density-peaks` | 选择代表性记录 |
| `assignment` | `nearest-anchor-assignment` | 建立初始分组 |
| `candidates` | `temporal-candidates` | 提出指向较早记录的候选连接 |
| `scorer` | `fused-affinity` | 结合实体与语义相似度 |
| `gate` | `anchor-gate` | 比较候选连接和原锚点分配 |
| `matcher` | `chain-matcher` | 选择相容的连接 |
| `hosting` | `chain-hosting` | 将时间链分配给各组 |

默认候选窗口为 50 条记录，候选保留 top-8，密度计算使用 5 个邻居，方差下限为 `1e-6`。RecordFolder 的早期实现名为 G1S。

## ContextFolder：缩短每组文本

ContextFolder 使用 RecordFolder 的分组，也会改写仅含一条记录的文本组。它提取事实、选择需要保留的内容、生成紧凑编码，再让验证模型根据编码回答事实问题，并据此修订。

| 文本组件字段 | 默认插件 | 作用 |
| --- | --- | --- |
| `fact_planner` | `fact-planner` | 提取事实和验证问题 |
| `triage` | `fact-triage` | 根据重要性与可推断性选择必要事实 |
| `compiler` | `context-compiler` | 生成紧凑编码 |
| `verifier` | `blind-verifier` | 检查编码中的事实恢复情况 |
| `feedback` | `repair-feedback` | 指出遗漏事实和长度问题 |
| `selector` | `shortest-clean-round` | 在已生成编码中选择结果 |

默认目标长度为组内原文 token 数的 80%，最多三轮，长度宽容系数为 1.15。这些参数指导文本生成；实际结果记录在 `final_tokens`、`required_lost` 和 fallback 原因中。当前执行器强制检查节点预算；严格限制全局 token 数需要相应的文本预算执行器。

验证问题来自组内记忆。基准问题和参考答案在后续评测阶段使用。[ContextFolder 实验模板](../../examples/experiments/contextfolder-template.json)也配置了读取编码记忆的问答提示词。ContextFolder 的早期实现名为 V12。

## 选择方法配置

方法配置分别选择 planner 和 operator：前者决定记录如何保留、删除或分组，后者执行文本处理。[recipes 目录](../../examples/recipes)提供压缩配置，完整实验配置位于 [examples/experiments](../../examples/experiments)。

| 方法 | 配置文件 | 处理方式 |
| --- | --- | --- |
| RecordFolder | [recordfolder.json](../../examples/recipes/recordfolder.json) | 按锚点、实体、语义与时间关系分组 |
| ContextFolder | [contextfolder.json](../../examples/recipes/contextfolder.json) | 在相同分组上执行编码与验证 |
| RandomPrune | [random-prune.json](../../examples/recipes/random-prune.json) | 按随机种子抽取记录 |
| RandomMerge | [random-merge.json](../../examples/recipes/random-merge.json) | 随机分组并整合文本 |
| KmeansPrune | [kmeans-prune.json](../../examples/recipes/kmeans-prune.json) | 保留靠近各聚类中心的真实记录 |
| KmeansMerge | [kmeans-merge.json](../../examples/recipes/kmeans-merge.json) | 整合各聚类的记录 |
| DART | [随机锚点](../../examples/recipes/dart-random_anchor_farthest.json)、[medoid](../../examples/recipes/dart-medoid_pivot.json) | 使用归档实验中的记忆选择变体 |
| 文本 ToMe | [tome-text.json](../../examples/recipes/tome-text.json) | 逐轮匹配、合并文本并更新向量 |
| M3 ToMe | [tome-m3-pooled.json](../../examples/recipes/tome-m3-pooled.json) | 按累计质量合并特征 |
| 文本 MemForest | [scope 预算](../../examples/recipes/memforest-mst-capacity.json)、[分簇预算](../../examples/recipes/memforest-mst-cluster-ceil.json) | 按语义和时间聚类，再沿树边合并 |
| M3 MemForest proxy | [memforest-m3-proxy.json](../../examples/recipes/memforest-m3-proxy.json) | 使用归档中的平均链接近似实现 |
| StreamMeCo | [streammeco-official.json](../../examples/recipes/streammeco-official.json) | 按固定版本的分类与选择规则裁剪记忆图 |

具体变体需要对应的运行设置：

- **文本 ToMe 和文本 MemForest：** 使用 `mode: "repeat"`，并提供对改写文本重新计算向量的服务。MemForest 在合并后采用成员中最新的事件时间。
- **MemForest 分簇预算：** 历史实现对每个初始簇的保留数量分别向上取整。使用 `resolve_memforest_budget()`，并配合相同的聚类器和比例。scope 预算变体则分配指定的总记录数。
- **StreamMeCo：** 按 clip 和 sample 分别设置类别配额。配置应采用这些配额，或与它们相容的外部预算。当前移植内容为图压缩；上游方法的时间检索阶段需要单独的 reader 实现。
- **DART 与 M3 MemForest proxy：** 对应归档实验中的记忆适配版本。报告结果时请同时注明具体配置名。

## 组合分组方法与文本编码

下面使用 ToMe 分组，再用 ContextFolder 编码：

```json
{
  "planner": {"plugin": "tome"},
  "operator": {"plugin": "contextfolder-operator"}
}
```

将这部分放入实验的 `compression` 配置，同时加入特征和 wrapper。设置 `run.mode: "repeat"`，并配置 chat、embeddings 和 tokenizer。压缩配置示例见 [tome-with-contextfolder.json](../../examples/recipes/tome-with-contextfolder.json)。

## 提供特征与服务

| 组件 | 提供的内容 |
| --- | --- |
| `semantic-encoder` | 当前记录文本的语义向量 |
| `chat-grounding` | 从记忆中提取的实体和关系特征 |
| `event-time-features` | 时间分组需要的事件时间 |
| 已存向量或 grounding 特征组件 | 带来源声明和记录映射的缓存特征 |
| `chat` 服务 | 文本生成与事实检查 |
| `embeddings` 服务 | 通过 `encode(texts)` 计算当前文本向量 |
| `tokenizer` 服务 | 通过 `count(text)` 统计长度，并声明 `measurement_id` |

向量空间需要一起声明 provider、model、revision 和 dimension。文本改写后更新对应向量。ToMe 的聚合向量用于分组；检索使用与实际存储文本对应的向量。

事件时间描述事情何时发生，可见时间描述读端何时能访问记录。时间分组使用已声明时钟的事件时间；需要按记录顺序实验时，可明确选择 `order` 变体。

## 理解执行过程

```text
记忆 → 计算特征 → 制定分组计划 → 处理文本 → 更新记忆
                    ↑                       |
                    └──── 需要时进入下一轮 ──┘

最终记忆 → 保存为框架格式 → 检索 → 回答 → 评测
```

`assemble(config)` 构建压缩组件。`CompressionEngine.step()` 执行一轮计划；`run()` 根据方法需要重复执行，并检查最终节点预算。计划使用保留、删除、合并、改写四种动作。执行时检查记录保护规则、样本归属和来源信息。

本地小示例：

```bash
python examples/compression_demo.py
```

它通过文本拼接将九条合成记录整合为四条。使用真实模型时，参考[完整实验模板](EXPERIMENTS.md)。[运行分析](ANALYSIS.md)介绍分组与事实检查记录，[组件扩展](EXTENDING.md)介绍替换方法。源码版本见 [METHOD_PROVENANCE.json](../METHOD_PROVENANCE.json)。
