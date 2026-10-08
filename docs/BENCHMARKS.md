# 原始 benchmark 与评分协议

benchmark loader 与原生 memory loader 独立。前者输出历史/已有 Snapshot 与 EvaluationSet，Initializer 决定如何构建记忆。
评分由 evaluator 配置选择，不由框架名猜测。组件配置见 [dataset-components.json](../examples/experiments/dataset-components.json)。

| benchmark / plugin | 输入与处理 | 评分插件 |
| --- | --- | --- |
| LoCoMo / locomo-dataset | 数字顺序 session、speaker、dia_id、日期、caption；QA/category/evidence 独立 | locomo-f1、evidence-recall |
| LongMemEval / longmemeval-dataset | session ID/date/history 平行数组，query time；has_answer 不进入历史 | official-judge + longmemeval-judge-prompt |
| PersonaMem v1 / personamem-dataset | CSV + context JSONL，初始化前按 end_index 截取；公开 options 独立 | personamem-accuracy 或更严格的 choice-accuracy |
| M3 robot / m3-dataset | annotations + 显式 video→库映射；before_clip 限制原生节点前缀、清理悬空边 | official-judge + m3-judge-prompt |
| M3 web / m3-dataset | annotations + 显式 video→库映射，已提供视频的完整图 | official-judge + m3-judge-prompt |

无时区日期要求 utc_offset_minutes，缺失时间不推断。PersonaMem 为共享 context 建字节偏移索引，每题只初始化历史前缀；v2 是独立协议。
M3 的 mem_path 不作为可信路径，所选视频必须配置 memory_loaders；缺失 cutoff 对应节点时拒绝回退完整图。
M3 是开放问答，不将其改成选择题。

## 锁定官方来源

[BENCHMARK_SOURCES.json](BENCHMARK_SOURCES.json) 保存 commit、文件哈希和链接：

- [LoCoMo 评价代码](https://github.com/snap-research/locomo/blob/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376/task_eval/evaluation.py)：分类 F1、Porter stemming、多答案与拒答约定。
- [LongMemEval 评价代码](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/evaluation/evaluate_qa.py)：按问题类型生成评分 prompt。
- [PersonaMem 推理代码](https://github.com/bowen-upenn/PersonaMem/blob/d07e6ade22e85e0e5d562247323a9c3e07553226/inference_standalone_openai.py)：context 前缀、options 与 final_answer 解析。
- [M3 控制器](https://github.com/ByteDance-Seed/m3-agent/blob/0e3e41939bd8a0b66d756e7b7eb8d5fe9992da5c/m3_agent/control.py) 和 [评分 prompt](https://github.com/ByteDance-Seed/m3-agent/blob/0e3e41939bd8a0b66d756e7b7eb8d5fe9992da5c/mmagent/prompts.py)：clip 截断与开放问答验证。

LoCoMoF1 使用可选 nltk，不下载语料；token-f1 无 stemming，版本不同。
PersonaMemAccuracy 保留官方 option-set 匹配；choice-accuracy 使用严格标签/文本匹配。
ChatJudge 是框架提供的 YES/NO 策略，不等于官方 LongMemEval/M3 judge。

官方 prompt 从用户持有的哈希锁定源文件提取，不直接 import 官方代码。
LongMemEval 只编译限制 AST 的 get_anscheck_prompt；M3 只提取指定字符串常量。
指标版本包含源文件 SHA，保留官方 YES 子串解析；配置真实 judge service 后才有模型评分。
不打包官方数据集或私有记忆库，各来源许可独立遵守。

```json
{
  "plugin": "metric-evaluator",
  "parameters": {
    "metrics": [{"plugin": "official-judge", "parameters": {
      "service": "judge",
      "prompt": {"plugin": "longmemeval-judge-prompt", "parameters": {
        "path": "upstream/evaluate_qa.py", "sha256": "REPLACE_PINNED_FILE_SHA256"
      }}
    }}]
  }
}
```

已有记忆库通过 bank-initializer 按 sample_id 明确绑定，不按数组位置拼接。
composite-dataset + protocol-evaluator 可以混合数据集和评分，无需增加 Runner 分支。
格式测试、真实库验收与合成 QA 链路分别记录，不代表论文成绩。
