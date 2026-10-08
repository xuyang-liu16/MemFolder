# 查看运行过程

[文档索引](README.md) · [English](../ANALYSIS.md)

通过保存的事件，可以追踪一条原始记忆如何参与分组、文本压缩、检索和回答。`FileRunReader` 支持按原始记录、压缩动作或问题查询，并导出相关事件和文件。

## 开启记录

在实验配置中加入：

```json
{
  "capture": {"profile": "cases", "text_policy": "omit", "vector_policy": "omit"},
  "observers": [{"plugin": "event-report-observer", "required": false}]
}
```

`summary` 保存事件；`cases` 和 `full` 还会保存供分析使用的数据。可以按样本、scope、阶段和诊断类型筛选。根据分析需要选择文本和向量记录策略；`text_policy: "redacted"` 需要配置 redactor。

这些策略控制公开分析文件。运行目录中的原始快照、预测和评测文件仍保存执行与校验所需的数据。分享运行目录前，需要同时检查这些文件。

## 查看离线示例

完成[离线示例](EXPERIMENTS.md)后，导出其中第一道问题：

```bash
python -m memfolder case build/experiments/offline-demo --dataset-id locomo --sample-id demo --question-id demo:0 --output build/cases/demo-question
```

命令会显示记录状态、相关事件数和文件数，并在新目录中保存 `case.json` 及其引用文件。使用 `--action-id` 可以查看压缩动作，`--source-id` 可以查看原始记录。

Python 接口提供相同查询：

```python
from memfolder import FileRunReader

reader = FileRunReader("build/experiments/offline-demo")
sample = reader.sample("locomo", "demo")
case = reader.by_question(sample, "demo:0", branch="compressed")
print(case.status, len(case.events), len(case.artifacts))
```

## 追踪记录的变化

| 阶段 | 可以查看的内容 |
| --- | --- |
| 加载与初始化 | 原始身份、记忆内容和样本归属 |
| 分组 | 锚点、初始分配、候选连接、评分和最终分组 |
| 文本处理 | 动作成员、按策略保存的文本和 fallback 原因 |
| ContextFolder 验证 | 必要事实、各轮 token 数、恢复检查和选中轮次 |
| 框架输出 | 原始与最终快照、输出节点 ID 映射 |
| 检索 | 命中排名、分数、输出 ID 和原始来源 |
| 回答与评测 | 问题 ID、上下文引用、预测和评分状态 |

可查看的范围由 capture 策略和组件实际提供的诊断决定。`complete_for_capture` 表示策略要求的数据已完整记录；`partial` 表示缺少文件或记录过程出错；`not_recorded` 表示目标案例未被录制。

## 比较两个运行

通过原始来源身份对齐记录：

```python
from memfolder import FileRunReader

left = FileRunReader("runs/experiment-a")
right = FileRunReader("runs/experiment-b")
origins = left.origins(sample_id="demo", source_id="d1")
comparison = left.compare(right, origins=origins)
```

原始身份包含 dataset、sample、scope、source ID 和 revision。生成的节点 ID 用于定位运行内部的记录。比较结果还会列出数据版本、reader、服务、提示词和评分协议的差异，供分析时参考。

## 添加分析报告

observer 实现 `open`、`on_event` 和 `close`。它接收不可变事件、公开分析文件的读取接口，以及自身报告的写入接口，可以统计分组大小、事实恢复或逐题结果。需要改变分组或文本时，应实现 planner 或 operator。

可选 observer 出错后，实验继续并记录错误。设置 `required: true` 后，报告成功成为实验完成的条件。[实验组件示例](../../examples/plugins/experiment_components)包含 observer、回答组件和评分组件。

单独从 Python 调用压缩时，可以用 `DiagnosticCollector` 收集诊断并写入 JSONL。完整实验还会附加样本、轮次、问题及原始/压缩分支信息。组件注册方式见[添加组件](EXTENDING.md)。
