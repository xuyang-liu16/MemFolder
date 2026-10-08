# 数据类型与接口

[文档索引](README.md) · [English](../CONTRACTS.md)

[`src/memfolder/core`](../../src/memfolder/core) 定义加载、压缩、检索和评测之间传递的数据。这些对象在 Python 中使用不可变值，并可保存为带版本的 JSON。本页介绍开发组件时最常用的类型。

## 记忆与样本

| 类型 | 含义 |
| --- | --- |
| `MemoryRecord` | 一条记忆，包含内容、来源、时间和可选向量 |
| `ContentPart` | 文本或图片、音频、视频等资产的引用 |
| `ScopeRef` | 由 dataset、sample、partition 组成的记录范围 |
| `OriginRef` | 某个 scope 内的原始 source ID 与版本 |
| `Snapshot` | 压缩某一阶段的记录、边和资产 |
| `MemoryInput` | 某个样本的历史或已有快照 |
| `DatasetSample` | 记忆及其评测问题 |
| `QuestionSet` | 传给 reader 的问题和公开选项 |
| `EvaluationSet` | 传给 evaluator 的参考答案、证据和评分信息 |

partition 可以表示对话、memory cube、视频片段或加载器定义的其他区域。计划通常在同一 scope 内处理记录。跨 partition 的样本内合并需要计划声明和运行时授权，dataset 与 sample 身份始终保持一致。

`eligible` 表示记录是否参与压缩。`RetentionPolicy` 分别控制删除、合并和改写权限，输出继承成员的相关保护规则。来源引用用于追踪输出记录由哪些原始记录产生。

## 计划与结果

planner 接收 `PlanningRequest`，其中包括当前快照、特征、预算、执行模式和可选的方法状态，返回 `ActionPlan`：

| 动作 | 输入记录数 | 输出记录数 | 用途 |
| --- | --- | --- | --- |
| Keep | 1 | 1 | 保留记录 |
| Drop | 1 | 0 | 删除记录 |
| Merge | 至少 2 | 1 | 整合多条记录 |
| Rewrite | 1 | 1 | 改写单条文本 |

每条目标记录恰好对应一个动作，目标集合之外的记录保留在快照中。计划包含输入快照指纹，执行器据此核对版本。

operator 为每个动作生成 `ActionOutcome`，并汇总为 `OperatorResult`。动作状态包括成功、带原因的 fallback 和失败。fallback 仍满足该动作规定的输出数量与来源；若需要改变成员或输出数量，应重新制定计划。

`input_view` 选择原始成员或当前轮成员。ContextFolder 可以使用组内原始内容，迭代合并方法可以使用当前文本。结果验证后，wrapper 更新图和向量，再进入下一轮或最终写入。

## 向量、特征与时间

`Embedding` 关联实际存储内容，并声明 provider、model、revision、dimension、metric。文本改写后需要更新对应向量。`FeatureBatch` 关联某个快照，可保存分组向量、累计质量、实体或聚类标签。

`TimePoint.clock` 声明时钟。事件区间描述事情发生的时间，`available_at` 和 `expires_at` 描述内容可见区间。合并采用成员可见区间的相容交集；交集为空时，需要保留为独立单元。

## 预算

`BudgetRequest` 描述保留量，接受绝对 `limit` 或比例 `ratio`，并指定分配和舍入方式。

| 字段 | 选项与含义 |
| --- | --- |
| `unit` | `nodes`、`characters`、`tokens`、`words`、`bytes`、`edges` 或带命名空间的单位 |
| `allocation` | 按 `scope`、`global` 或调用方给定的 `group` 分配 |
| `rounding` | `half_even`、`half_up`、`floor`、`ceil` |
| `minimum` | 每个分配目标的下限 |
| `enforcement` | 精确 `exact`、上限 `at_most` 或建议 `advisory` |
| `reference` | 从 `initial` 或 `current` 快照解析 |
| `measurement_id` | tokenizer 或其他计量方法的标识 |

节点数只统计 eligible 记录，字符数按 Python Unicode code point 统计，其他单位需要逐记录提供测量值。当前压缩执行器强制检查节点预算，其他单位可作为 advisory；严格文本限制需要相应的计量与执行组件。

group 分配需要完整且互不重叠地覆盖 eligible 记录。舍入在各组内分别进行，因此 MemForest 等方法的逐簇向上取整需要按组解析。

## 序列化与验证

核心对象使用不可变 dataclass，`FrozenMap` 保存递归不可变的 JSON 值。`dumps()`、`loads()` 使用包含 `schema_id`、`schema_version` 和 `data` 的格式：

```python
from memfolder.core import ScopeRef, dumps, loads

scope = ScopeRef(dataset_id="demo", sample_id="sample-1", partition_id="history")
encoded = dumps(scope)
restored = loads(encoded, expected=ScopeRef)
assert restored == scope
```

构造器和验证函数检查类型、ID、维度、图引用、时间、来源覆盖和保护规则。`json_schema(Type)` 导出结构描述；导入外部数据时使用 `loads` 或 `from_data`，同时执行语义检查。

组件自有字段放在带命名空间的 `extensions` 中，新类型通过 `@record("lab.type")` 注册。`MemoryDelta` 表达记录与图边的版本化更新，`AlgorithmState` 保存方法的 JSON 状态和资产引用。模型、client 等运行时服务单独传入。

## 源码导航

| 模块 | 内容 |
| --- | --- |
| `memory.py`、`data.py` | 记忆、样本、问题和参考标签 |
| `features.py`、`candidates.py` | 特征和可选分组阶段 |
| `plans.py`、`budgets.py` | 动作、结果和保留量目标 |
| `evaluation.py`、`observation.py` | 预测、评分、事件和案例 |
| `plugins.py`、`values.py` | 组件接口与序列化 |

使用 `python tools/check_contracts.py` 检查实现，完整插件示例见[添加组件](EXTENDING.md)。
