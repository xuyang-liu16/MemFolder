# 公共数据契约 v1

正式实现以 `src/memfolder/core/` 为准。之前 `architecture_review/INTERFACE_CONTRACTS.pyi`
属于设计阶段草案；合成组装原型的接口也不作为正式包的 API。

## 依赖与模块边界

`values → memory → data/features/candidates/budgets/plans → observation/evaluation → plugins`。
所有值对象只依赖标准库。数据对象不导入 Mem0、MemOS、M3 或任何具体算法。
算法服务通过独立的 `AlgorithmContext` / `OperatorContext` 注入，不进入 JSON 或观察上下文。

| 文件 | 职责 |
| --- | --- |
| `values.py` | 严格类型、递归不可变 JSON、schema 注册、编码解码、结构 JSON Schema |
| `memory.py` | 内容、scope、原始来源、图与资产、时钟、存储 embedding、流式 delta |
| `data.py` | 原始历史/既有记忆、样本身份、公开问题与评测标签分区 |
| `features.py` | 实体/聚类/向量特征、质量 mass、方法自有流式状态 |
| `candidates.py` | 可选的候选、分数、门控、匹配选择契约 |
| `plans.py` | 动作、目标批次、结果、来源/保护/可见性、投影和 embedding 刷新校验 |
| `budgets.py` | 预算单位、计量身份、分配、舍入、严格或上限执行 |
| `observation.py` | 事件、诊断、覆盖范围、case、manifest、只读工具接口 |
| `evaluation.py` | 检索来源/排名、预测、评分状态 |
| `experiment.py` | CompressionStatistics、SampleRunResult、ExperimentResult；完整离线运行产物 |
| `plugins.py` | 插件能力协商、同步/异步角色协议 |

## 记忆与多模态图

`MemoryRecord` 是压缩处理单位，可以是文本记忆、实体、token、图节点。
`kind` 和 `ContentPart.modality` 是开放字符串，不按框架枚举写死。
文本可直接携带；图片/音频/视频/张量可用 `ArtifactRef`，附加 shape、dtype 等 JSON 描述。
张量读取与模型 forward 集成属于相应 provider/operator，不放进 core。

`ScopeRef(dataset_id, sample_id, partition_id)` 表达允许合并的边界。
partition 可为会话、cube、clip 或适配器声明的其他区域。时间窗口、角色、用户等附加语义
可以放在内容、时间字段或 namespaced extensions 中，不假定一个 scope 等于一个 session。
节点 ID 在 snapshot 内唯一；原始来源还包含 scope/source_id/revision，避免不同样本的同名 ID 混淆。
OriginRef.scope 标识原始数据范围，不随 backend cube 或压缩节点重新编号。
SampleRef.identity 以 dataset/sample/split/data fingerprint 对齐；附加分析注解不改变原始身份。

`eligible=False` 的身份节点及其他资产不进入压缩目标。保护策略分别规定
`may_drop/may_merge/may_rewrite`，允许研究者表达“可以合并但不能删除”等约束。
变化输出不能放宽成员的保护策略。

`Snapshot` 同时含 records/edges/assets。图边必须引用现存节点。
Operator 只返回节点动作结果；Wrapper 的 `project` 负责重连/删边等框架语义，
`materialize` 再写入最终后端。core 不猜测 entity 边、clip 可见性或 cube 关系怎么重写。

时钟由 `TimePoint.clock` 明确声明：绝对 UTC 秒、视频相对秒或逻辑时钟不可混算。
`available_at/expires_at` 与内容的 occurrence `time_ranges` 分离。
压缩输出不能提前暴露其原始成员的信息或延长其有效期。涉及不同时间区间时采用保守交集；
非交叠可见区间不可强行压成一个单位，可保留多个单位或先按可见窗口规划。

## 存储 embedding 与方法特征

`Embedding` 绑定实际 `ContentPart` 指纹及 provider/model/revision/dimension/metric。
修改内容而保留旧向量会直接报错。写端生成新文本时，应把 embedding 清空，之后由 provider 刷新。
artifact 模式的实际向量 hash/维度读取检查由 provider 实现。

ToMe 的 pooled vector、组质量 mass、聚类标签、实体标签等属于 `FeatureBatch`。
它们绑定输入 snapshot 指纹，不能冒充实际存储内容的 embedding。
不同向量空间用独立 FeatureBatch；外部大矩阵通过 artifact 引用，core 不要求 NumPy 或 GPU。

## 数据、问题、答案

Loader 输出 `DatasetSample(memory, evaluation)`；runtime 只把 `MemoryInput` 交给 Wrapper。
历史既可为 `HistoryEvent`，也可引用外部 artifact；已有记忆可直接作为 initial_snapshot。
空历史/空记忆合法，流式方法可以从空 snapshot 开始。

Planner 接收 `PlanningRequest`，不包含问题或评测答案。
Reader 接收 `EvaluationSet.reader_input()` 产生的 `QuestionSet`，含问题、公开选项、查询时间；
它不含 ground_truth 或 evidence 标签。只有 Evaluator 接收完整 `EvaluationSet`。
问题类别、多个有效答案、选择题、拒答等通过标签 JSON 表达；metric 实现负责解释。

## 动作与执行

| 动作 | 成员/输出 | 约束 |
| --- | --- | --- |
| Keep | 1 / 1 | ID 与整条记录保持一致 |
| Drop | 1 / 0 | 合法删除显式记录 |
| Merge | 至少 2 / 1 | 来源完整保留 |
| Rewrite | 1 / 1 | 单节点编码/压缩，来源不变 |

`ActionPlan.target_ids` 显式表示处理批次；每个 target 必须恰好出现一次。
目标外的记录原样保留，不能通过遗漏节点暗中剪枝，也不能覆盖它们的 ID。
输入 snapshot 指纹避免旧 plan 被应用到新一轮数据。

默认 boundary=scope；跨 partition 合并需要 plan 声明 boundary=sample、指定输出 scope，
且 runtime 明确授权。数据集与样本始终不可跨越。
Wrapper 声明不支持跨 clip 时，runtime 不能授权 sample 边界。

`input_view=original/current` 明确算子取原始成员还是当前轮成员。
OperatorContext.originals 提供只读原始记忆查询，因此 V12 无需把摘要再编码，
迭代 ToMe 则能使用当前轮文本。

`ActionOutcome` 逐动作记 success/fallback/failed。fallback 需 reason，且仍满足计划输出契约。
改变输出数量/身份的降级必须重新制定显式计划，不能在同一结果里偷偷保留不同节点。
失败结果可以序列化供分析；`validate_result` 拒绝将其当成功结果物化。

每轮流程：`Planner → Operator → validate_result → Wrapper.project → Embedding.refresh → 下一轮`。
最后 `Wrapper.materialize → Reader → Evaluator`。project 不写库，允许图方法安全地逐轮重规划。
同步和异步插件都可声明同样的数据协议；调度及服务生命周期在 M1/M2 实现。

流式更新用 `MemoryDelta(base_fingerprint, upserts, removals, edge edits, watermark)`；
删节点必须同步明确删/重连边。`apply_delta` 原子生成新 revision，拒绝旧版本 delta。
`AlgorithmState` 是方法自有版本化 JSON/asset 数据，不将模型对象、数据库句柄或 pickle 放进状态。

## 预算

结构和文本预算可以同时出现在 `PlanningRequest.budgets`；各自使用独立的单位和计量规则。
nodes 按 eligible 节点数计；characters 明确按 Python Unicode code points 计。
tokens/words/bytes/edges/custom units 必须声明 measurement_id 并提供显式计量；
edge 计量应由 wrapper 给出可加和的边归属，不允许把双端边无意重复计数。

支持 absolute limit 或 ratio，允许 ratio=0；支持 global/scope/group allocation，
group 必须构成 eligible 节点的完整不相交分区。每个组独立舍入，故 per-cluster ceil
不必等于 global round。minimum、half_even/half_up/floor/ceil 全部显式。

enforcement 为 exact/at_most/advisory。原始预算由 runtime 一次解析后复用，
reference=current 的预算必须每轮重新解析。`validate_budget` 检查已计量的结果；
runtime/provider 负责从最终结果产出同单位、同组归属的真实计量，不能拿节点减少数冒充 token 节省。

## 扩展、序列化与版本

公开对象是 frozen dataclass，容器转换为 tuple/FrozenMap，嵌套对象也不暴露共享可变 dict。
未知核心字段、非有限数、错误类型、未知 schema/version 会报 `ContractError`。
缓存的指纹只来自不可变字段，序列化不包含缓存。

wire 格式是 `{"schema_id": "memfolder.snapshot", "schema_version": 1, "data": {...}}`。
`dumps/loads` 不导入字符串指定模块、不执行 pickle。第三方 schema 用显式 `@record("lab.name")` 注册。
扩展数据用 `extensions={"lab.routing": {...}}`；新核心字段或迁移需要明确版本策略，
不自动吞掉旧代码的字段。旧研究原型 JSON 并未自动转换为正式契约。

`json_schema(Type)` 与 `tools/export_schemas.py` 从真实类型生成结构 schema。
跨字段的维度、来源、覆盖、图引用、保护与时间等语义由构造器/validator 检查。
对外部文件必须经过 `loads` 或 `from_data`，不能只通过 JSON Schema 就绕过语义校验。

## 本模块验收

运行 `python tools/check_contracts.py`。报告写入 `build/contract_validation.json`。
测试包含恶意/错误输入、来源丢失、过时 plan/features、答案边界、保护继承、可见性、
新增自有动作/状态 schema、图 delta、插件能力冲突，以及 135 组合成 shape 场景。
实际算法、后端和模型结果将在后续模块分别做 characterization/integration 验证。
