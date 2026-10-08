# 观察与 case 分析扩展契约

已实现 TraceRecorder、Observer 生命周期、只读 PublicArtifacts、FileReportWriter 与 FileRunReader。
完整实验自动观察 initialize/feature/plan/apply/project/materialize/reader/evaluator 和小组件诊断。
事件保留 span/parent span、round、sample、action/question、来源与 compressed/uncompressed 分支。
单独运行压缩仍可使用 DiagnosticCollector；完整运行见 [EXPERIMENTS.md](EXPERIMENTS.md)。

## 单向观察边界

`Observer.open/on_event/close` 只接收 `EventEnvelope` 和 `ObservationContext`。
上下文只有 run_id、只读 ArtifactReader 和独立 ReportWriter；没有 PlannerContext、数据库连接或模型资源。
Observer 不返回策略/文本给算法。想改变算法行为时应实现明确的 Planner/Operator 插件。

事件 summary 只允许 scalar，输入输出、候选表、大向量、检索上下文通过 artifact 引用。
`project_snapshot()` 提供字段明确的递归冻结投影；默认不输出正文/native payload/extension blobs。
`include_text=True` 是显式读取正文，不是脱敏引擎。进程内 Python 插件属于可信代码，边界不作为安全沙箱。

## 从节点到回答的链接

稳定身份由 dataset fingerprint、sample、scope、origin source_id/revision 构成。
新 node_id 与 action_id 仅用于运行内关联，不能用生成摘要或自增 action_id 跨 run 对齐。

`DiagnosticLinks` 能链接 node/origin/action/candidate/question。
候选、分数分解、gate 接受/拒绝与阈值有公共 typed contracts；方法特有解释用 versioned DiagnosticRecord。
诊断未提供的部分要声明 not_recorded，不从最终结果倒推虚构理由。

`RetrievalHit` 记录 canonical node/native ID、排名、分数和 origins；`Prediction` 关联 question 与 reader context artifact。
这样 RunReader 能提供三种查询：by_origin、by_action、by_question，以及 compare。
删除节点是有效的 case 终点；未跑 QA 时不能生成“回答链”。

## 录制范围与完整性

`CapturePolicy` 提供 off/summary/cases/full、sample/scope/stage/diagnostic 筛选及 text/vector policy。
FileRunReader 对相关动作和来源做 lineage 闭包；不从最终文本倒推未录制的决策。
`TraceCoverage` 明确采样范围、已写/丢弃事件、缺 artifact/stage。
`complete_for_capture` 只表示在声明范围内完整，不表示所有样本、正文、候选和向量均被记录。

RunManifest 分开 compression/evaluation/observation 状态，保存插件实现版本和参数指纹，不自动导出原始配置。
压缩成功但观察失败，应标记 incomplete；评分 not_run 与质量分数零不同。
optional observer 错误隔离；required observer 失败使实验失败。flush/close 与开销计时已经实现。
严格 trace 状态不能靠吞掉异常就声明 complete。

## 外部合作者的修改方式

外部 Observer 声明订阅和诊断 schema，通过 public refs 读数据，写自身 reports。
离线 notebook/UI 只依赖公共 wire schema 与 RunReader，不导入某个框架的内部类。
新增分析数据可使用 `lab.case_annotation` 一类命名空间，不扩散到业务模块字段。
第三方 schema 显式注册；dataset/协议身份不匹配时 RunComparison 必须标记 incomparable/partial。

## 已实现的 Wrapper 分析产物

原生物化 bundle 保存 source snapshot、最终 snapshot、native package、来源成员与 canonical/native ID 映射。
`run.compression.steps` 可查看每轮 request/plan/outcome；`run.snapshot` 包含最终内容向量。
`memfolder.wrapper.export / edges / embeddings / materialized` 冻结诊断可被外部 callback 读取。
`example.case-writer` 是独立 wheel，追加 cases.json；不修改方法模块。
详见 [WRAPPERS.md](WRAPPERS.md)。这些接口与回答链查询已经运行。

## 可运行配置与查询

```json
{
  "capture": {"profile": "cases", "text_policy": "omit", "vector_policy": "omit"},
  "observers": [{"plugin": "event-report-observer", "required": false}]
}
```

summary 保存事件，cases/full 增加公共投影。text_policy=redacted 必须配置 redactor；RegexRedactor 是可替换示例。
scope 筛选的诊断默认只公开链接和字段名。私有 source/final/prediction/evaluation 文件仍含对应数据；
capture 策略只控制公共分析投影，不表示整个运行目录脱敏。
PublicArtifacts 检查哈希和 allowlist，Observer 不可读私有 Snapshot/评分标签；Observer reports 纳入运行校验。

```python
from memfolder import FileRunReader

reader = FileRunReader("runs/run-001")
sample = reader.sample("locomo", "demo")
case = reader.by_question(sample, question_id, branch="compressed")
action_case = reader.by_action(sample, action_id)
origin_case = reader.by_origin(origin_ref)
reader.export(case, "cases/question-001")
comparison = reader.compare(FileRunReader("runs/run-002"), origins=(origin_ref,))
```

```powershell
python -m memfolder case runs/run-001 --dataset-id locomo --sample-id demo --question-id QUESTION_ID --output cases/question-001
```

未录制 case 为 not_recorded，缺文件/Observer 错误为 partial。complete_for_capture 只代表声明范围的完整性，
独立于算法/评测成功。失败运行也可检查已留下的 trace。比较时，数据版本不同为 incomparable；Reader、服务、
prompt、评分/问题协议不同为 partial 并给出差异。
[独立示例包](../examples/plugins/experiment_components/experiment_plugin.py) 同时提供 Answerer、Metric 和 Observer，
只使用公共契约，安装后修改配置即可。Observer 通过 context.artifacts.read_json(ref) 读取投影，
通过 context.reports.write_json(path, FrozenMap(...)) 写自身报告。
TraceRecorder 默认关闭，是有序本地文件实现；超大 trace、远程持久化、流式分析可扩展 store/recorder 层。
