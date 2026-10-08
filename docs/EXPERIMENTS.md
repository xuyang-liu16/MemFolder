# 完整实验组装与运行

离线 `once` / `repeat` 实验已经贯通：DatasetLoader → MemoryInitializer → Wrapper.export → FeatureProviders
→ Planner → Operator → Wrapper.project → 刷新内容向量与物化 → Reader → Evaluator。
TraceRecorder / Observer 单向观察各阶段，FileRunReader 用于离线 case 查询。

Runner 不判断 benchmark、baseline 或框架名称。各阶段通过 `memfolder.plugins` entry point 或 `module:factory`
挂载。原有 `assemble()` 继续支持只运行压缩；`assemble_experiment()` 负责完整实验，并强制 Reader/Evaluator 成对配置。

## 无模型的可运行示例

在 memfolder 目录运行：

```powershell
python -m pip install -e .
python examples/experiment_demo.py
python -m memfolder run examples/experiments/offline-demo.json
python -m memfolder verify build/experiments/offline-demo
python -m memfolder run examples/experiments/offline-demo.json --resume
python -m memfolder matrix examples/experiments/offline-matrix.json
```

示例采用合成 LoCoMo 格式历史、RandomMerge、拼接算子、MemOS 可移植文本输出与 context echo。
`test_only=true` 的评分仅验收基础设施，不代表官方 benchmark 成绩。示例不访问网络。
experiment_demo.py 使用临时目录，可重复运行；CLI 已有输出目录需要校验 resume，或换新目录。

## 配置入口

LoCoMo 数据中可能存在无效的 evidence 标注。加载器默认 `evidence_policy="strict"`
保持严格校验；做答案准确率评测时可显式选择 `"preserve_unknown"`，将无法解析的
原文保存在 evaluator-only 的 `ground_truth.unresolved_evidence` 中，同时保留合法的
OriginRef。该模式不猜测对话 ID，不丢弃 QA，也不向 Reader 或压缩模块提供标注。
含未解析证据的 case 不应被视为已经拥有完整可用的证据集合。
`EvidenceRecall`（`origin-set.v2`）对这些 case 返回 `not_run`，原因是
`unresolved_evidence_labels`，不会仅对合法标注的子集计算召回率。答案准确率
仍可使用保留的原始 answer 单独评测。

完整配置见 [offline-demo.json](../examples/experiments/offline-demo.json)。

| 字段 | 责任 |
| --- | --- |
| dataset | 输出 DatasetSample，明确时间、scope、数据版本和评分协议 |
| initializer | 保留已有 Snapshot；history-initializer 分段；summary-initializer 抽取；bank-initializer 显式连接已有库 |
| compression | planner / operator / features / wrapper，复用所有已实现 baseline |
| reader | 独立替换 retriever、context_builder、answerer、reader_prompt |
| evaluator | metric-evaluator 的 metrics；protocol-evaluator 按 protocol_id 路由 |
| services | 命名 chat、grounding、embeddings、tokenizer 等服务 |
| capture / observers / redactor | 录制范围、分析插件、正文脱敏 |
| run | seed、mode、max_rounds、budgets、allow_empty、evaluate_source |
| output_dir | 新的运行目录，相对配置文件定位 |

composite-dataset 组合多个 benchmark；Runner 消费同步或异步迭代器，结束时关闭资源。
重复样本、空选择、缺失答案覆盖、越界检索、过期向量与非法计划明确失败。

## 主线配置与模型服务

[RecordFolder](../examples/experiments/recordfolder-template.json) 和
[ContextFolder](../examples/experiments/contextfolder-template.json) 提供整链模板。
运行前替换 URL、模型、revision、向量 dimension、数据与输出目录。`api.example.invalid` / `REPLACE_*` 是占位值。
密钥通过 MEMFOLDER_PROVIDER_KEY 环境变量读取。安装 `.[algorithms,contextfolder,evaluation]` 后运行这些模板。

主线使用 semantic-encoder、chat-grounding、event-time-features，候选显式指定 temporal_feature=temporal。
缺失事件时间不填成 epoch zero。实体缓存/可信内容向量可替换在线特征组件。
ContextFolder 的 Reader 使用独立解码提示；内部事实验证问题来自压缩输入，benchmark QA/答案不进入 Planner/Operator。

compatible-http 提供文本 chat/embedding 服务；cached-service 以 provider 身份、参数、内容指纹缓存请求。
不同模型/revision 使用不同缓存身份；Tokenizer 提供明确 measurement_id。也可直接注入自有服务：

```python
import asyncio
from memfolder import assemble_experiment

assembly = assemble_experiment(config, base_path=config_directory)
result = asyncio.run(assembly.run(services={"chat": my_chat, "embeddings": my_encoder}))
```

注入服务由调用者管理，配置创建的服务由 Runner 关闭。HTTP 失败不自动生成答案。
默认 Answerer 使用文本接口；ContextBuilder 保留多模态 parts，可替换 Answerer 接图像/语音模型。

## Wrapper 与读取

Mem0/MemOS/M3 wrapper 为每个样本创建独立输出。完整实验将 wrapper.output_dir 绑定到本次样本目录。
支持格式见 [WRAPPERS.md](WRAPPERS.md)。Reader 可选 lexical、dense、graph expansion、time decay、Qdrant、M3 原生搜索、SDK bridge。
原生查询必须匹配内容向量模型；旧模型未知不能默认匹配。M3 搜索显式注入 m3.graph_type；SDK bridge 注入 memory_search 服务。
数据库资源不进入 Planner/Observer。Reader 仅接收 QuestionSet，Evaluator 单独接收 EvaluationSet；每题检查 as_of、有效期、sample、native ID 和来源。

## 产物、失败与恢复

输出包含 sources.json、run.manifest.json、result.json、completion.json，以及逐样本 source/final Snapshot、每轮计划/结果、
native bundle、prediction context、评分产物。启用 capture 后增加 trace/events.jsonl、trace/index.json、公共投影与 Observer reports。
私有产物可能包含原始记忆和答案；capture 正文策略仅控制公开分析投影。

verify_experiment() 检查所有引用文件与原生 bundle 的 SHA256。Resume 只复用已完成且哈希一致的运行，
输入/runtime/插件/参数变化拒绝复用。动态 loader 声明 source_paths 或 input_fingerprint；注入服务 resume 时提供 cache_identity。
失败保留 partial manifest/trace，没有 completion.json，不把缺失评分记成零。失败尝试用新目录重跑。

结果包含节点/字符/边保留率、轮数、计时、服务调用次数。配置 tokenizer 后记录带 measurement_id 的 token 数；
不把字符数称为 token。计时含录制/观察开销，provider token 账单未知时为 null。
evaluate_source=true 在独立未压缩分支使用相同 Reader/Evaluator，分开汇总两分支。
矩阵对点路径配置与 seeds 做笛卡尔积，每个子运行独立 manifest；见 [offline-matrix.json](../examples/experiments/offline-matrix.json)。

## 验证范围

原始格式和评分来源见 [BENCHMARKS.md](BENCHMARKS.md)，分析 API 见 [ANALYSIS.md](ANALYSIS.md)。
已完成 Mem0/LoCoMo 的真实 API 单次全量验收：6,817条原记忆、10个会话，每组1,986道QA，按官方规则1,540题计分；覆盖未压缩检索、RecordFolder keep50、RecordFolder＋ContextFolder keep50。keep50 为节点预算，另计 cl100k_base 正文token；不能据此声称50% token压缩或全部历史论文效果复现。ContextFolder 还需要改进格式读取和QA保持能力。
其他环境的真实模型 QA、全部历史实验的分数复现、在线 Neo4j/事务、流式调度、官方 M3 多轮 Control、完整多模态推理需针对目标环境验收。
StreamMeCo 官方图压缩已实现；通用时间衰减检索与官方方法推理分别标识版本。
