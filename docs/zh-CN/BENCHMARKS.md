# 基准与评测

[文档索引](README.md) · [English](../BENCHMARKS.md)

基准加载器读取历史、问题和参考答案，initializer 负责构建或选择记忆。压缩完成后，reader 检索记忆并回答问题，evaluator 按选定协议评分。

## 选择数据集和指标

| 数据集 | 加载器 | 输入 | 评测 |
| --- | --- | --- | --- |
| LoCoMo | `locomo-dataset` | 对话 session、日期、说话人和问答标注 | `locomo-f1`，可加 `evidence-recall` |
| LongMemEval | `longmemeval-dataset` | session 历史、日期、问题时间和答案 | `official-judge` 配合 `longmemeval-judge-prompt` |
| PersonaMem v1 | `personamem-dataset` | 问题 CSV 和上下文 JSONL | `personamem-accuracy` |
| M3 robot | `m3-dataset`，`variant: "robot"` | 标注及视频到记忆加载器的映射 | `official-judge` 配合 `m3-judge-prompt` |
| M3 web | `m3-dataset`，`variant: "web"` | 标注及视频到记忆加载器的映射 | `official-judge` 配合 `m3-judge-prompt` |

从 [dataset-components.json](../../examples/experiments/dataset-components.json) 选择组件，填入实验的 `dataset`，再设置实际路径和样本范围。例如：

```json
{
  "dataset": {
    "plugin": "locomo-dataset",
    "parameters": {"path": "data/locomo.json", "utc_offset_minutes": 0}
  },
  "evaluator": {
    "plugin": "metric-evaluator",
    "parameters": {"metrics": [{"plugin": "locomo-f1"}, {"plugin": "evidence-recall"}]}
  }
}
```

`utc_offset_minutes` 采用源数据的时区。reader、initializer、压缩和服务配置见[实验指南](EXPERIMENTS.md)。

## 保留任务规定的输入范围

**LoCoMo** 保留 session 顺序、说话人、对话 ID 和日期，证据标注对应原始对话 ID。默认 `evidence_policy: "strict"` 检查各条证据。选择 `preserve_unknown` 后，无法解析的证据标签会保留供检查，答案仍可评分。由于完整证据集合尚未解析，这类问题的 evidence recall 状态为 `not_run`。

**LongMemEval** 保持 session ID、日期和历史的对应关系，并用问题时间限定可用记忆。问题类型和可回答性标签由 evaluator 使用。

**PersonaMem v1** 只从截至 `end_index` 的历史前缀初始化记忆，共享上下文文件通过字节偏移索引加载。公开选项传给 reader，正确选项传给 evaluator。PersonaMem v2 需要对应的加载器和评分协议。

**M3 robot** 读取 `before_clip` 之前的记忆节点，**M3 web** 使用所选视频的完整图。每个视频都应明确配置 `memory_loaders`，并提供包含所需截断节点的图。两类任务均采用开放问答。

## 配置模型评分

LongMemEval 和 M3 评分需要 `judge` 服务和固定版本的上游提示词文件。例如：

```json
{
  "plugin": "metric-evaluator",
  "parameters": {
    "metrics": [{
      "plugin": "official-judge",
      "parameters": {
        "service": "judge",
        "prompt": {
          "plugin": "longmemeval-judge-prompt",
          "parameters": {"path": "upstream/evaluate_qa.py", "sha256": "REPLACE_PINNED_FILE_SHA256"}
        }
      }
    }]
  }
}
```

使用 [BENCHMARK_SOURCES.json](../BENCHMARK_SOURCES.json) 中记录的源文件和哈希，再在 `services.judge` 配置模型。加载器从源文件提取需要的提示词函数或字符串。指标版本会记录文件哈希和上游的 YES 子串判断规则。

通用 `chat-judge` 使用自己的 YES/NO 判断方式。实验要求采用固定版本的 LongMemEval 或 M3 规则时，请选择 `official-judge`。

## 一致地解读分数

- `locomo-f1` 采用固定版本的分类、多答案、拒答和词干处理规则，依赖可选 NLTK。`token-f1` 是更简单的 token 匹配指标。
- `personamem-accuracy` 采用发布版本的选项集合和 `final_answer` 解析规则；`choice-accuracy` 采用更严格的标签或文本匹配。
- `evidence-recall` 检查检索命中的原始来源，并通过状态说明证据标签无法解析的情况。
- 比较实验时，同时查看指标版本、评分状态和样本范围。

已有记忆库通过 `bank-initializer` 按样本绑定，详见[加载记忆](LOADING.md)。多数据集实验可以通过 `composite-dataset` 组合加载器，再用 `protocol-evaluator` 按协议选择评测器。论文报告值见[论文结果](PAPER_RESULTS.md)。
