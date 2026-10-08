# 添加组件

[文档索引](README.md) · [English](../EXTENDING.md)

MemFolder 按配置加载组件。新的数据集、压缩阶段、文本处理方法、框架适配器、回答组件、指标和分析报告，都可以作为 Python 模块或独立安装包接入。

## 选择接口

| 任务 | 组件角色 | 主要输出 |
| --- | --- | --- |
| 加载新基准 | `data_loader` | `samples()` 返回的 `DatasetSample` |
| 读取已有记忆库 | `memory_loader` | `load()` 返回的 `LoadedLibrary` |
| 选择代表性记录 | `anchor_selector` | `AnchorSelection` |
| 实现完整分组方法 | `planner` | `ActionPlan` |
| 编码组内文本 | `text_writer` | `TextWriteResult` |
| 保存框架格式 | `native_writer` | 文件及引用 |
| 生成或评测答案 | `answerer` 或 `metric` | 预测或评分结果 |
| 分析已记录事件 | `observer` | 报告文件 |

内置组件也使用这些接口。相关对象见[数据类型与接口](CONTRACTS.md)。

## 安装一个示例插件

仓库中的小型基准插件包含独立安装配置：

```bash
python -m pip install -e .
python -m pip install -e examples/plugins/new_benchmark
python -m memfolder.benchmarks --config examples/plugins/new_benchmark/config.json --output-dir build/newbench-import-001
```

它加载两段合成对话，共三条历史事件和两个问题，输出 `memory.jsonl`、`evaluation.jsonl`、`report.json`。该示例演示数据加载接口；真实任务按相应协议配置 evaluator。

## 实现工厂函数

工厂函数接收参数和 `BuildContext`，返回组件实例。工厂与组件都通过相同的 `PluginSpec` 声明 ID、角色和 API 版本。下面展示一个 selector 的工厂部分：

```python
from memfolder.core import ContractError, PluginSpec

SPEC = PluginSpec(plugin_id="lab.selector", role="anchor_selector", api_version=1)

def build(parameters, *, context):
    if set(parameters) - {"newest_first"}:
        raise ContractError("Supported parameter: newest_first")
    return MySelector(newest_first=parameters.get("newest_first", True))

build.spec = SPEC
```

实现 `MySelector.select(request, target, context)`，并令 `MySelector.spec = SPEC`。[完整 recency 示例](../../examples/plugins/recency/recency_plugin.py)展示了参数校验、受保护记录处理和返回值。

文件路径通过 `context.path(value)` 解析，以配置文件所在目录为起点。模型和数据库在被选中组件的执行阶段初始化。加载器声明 `source_paths` 或 `input_fingerprint`，供实验验证输入来源。

## 在配置中引用

开发时，可以直接引用当前环境能够导入的模块和工厂：

```json
{"plugin": "my_selector:build", "parameters": {"newest_first": true}}
```

发布独立包时，在它的 `pyproject.toml` 中声明：

```toml
[project.entry-points."memfolder.plugins"]
"lab.selector" = "my_selector:build"
```

安装后，配置使用 `"plugin": "lab.selector"`。例如替换 RecordFolder 的锚点选择：

```json
{
  "planner": {
    "plugin": "recordfolder",
    "parameters": {"anchors": {"plugin": "lab.selector"}}
  },
  "operator": {"plugin": "recordfolder-operator"}
}
```

组装时会检查角色、API 版本和组件声明的能力。

## 添加数据集或存储格式

基准加载器为样本分配稳定身份，加载历史或已有记忆，并附加评测问题。记忆、公开问题和参考答案分别保存。新任务可以选择现有 evaluator，或增加自己的评分指标。已包含序列化 `DatasetSample` 的文件可直接使用 `dataset-jsonl`。

读取已有库时，如果只是记录字段变化，可复用 reader 并实现 `FormatAdapter.decode()`；文件或数据库读取方式变化时，再增加 reader。[加载指南](LOADING.md)说明了 owner 映射、向量、时间与覆盖范围。

按 dataset、sample、split 和 version 对齐记忆与评测，保留原生 ID、源字段和已知的模型/时间信息。数据迭代结束或失败时关闭资源。

## 验证组件

准备小型测试数据，检查记录内容、样本身份、原始来源和返回类型。按组件职责覆盖空输入、重复 ID、非法参数和资源关闭。加载记忆或评测数据时，还应检查问题与参考答案是否只传给对应阶段。

示例包括[锚点选择](../../examples/plugins/recency)、[框架输出](../../examples/plugins/native_writer)，以及[回答、评分和报告](../../examples/plugins/experiment_components)。`tools/check_plugin_installation.py` 检查独立安装的插件包；`python tools/check_contracts.py` 执行仓库的组件和数据校验测试。
