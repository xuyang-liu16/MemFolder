# 方法、benchmark、框架的兼容边界

名字不进入 core 的枚举或分发器；method/dataset/framework 都由插件声明能力。
“契约兼容”指能表达方法的输入、动作、状态和分析产物。实际实现、真实数据加载与后端联调
分别验证，不宣称任意方法 × benchmark × 框架都已完成端到端 QA。

当前已实现 [记忆库加载模块](LOADING.md)：Mem0 导出/本地 Qdrant、MemOS 文本/tree/cube、M3 VideoGraph
可转换为统一 MemoryInput。当前也已实现可组合 Planner / Operator、baseline 阶段、嵌套插件组装和诊断收集，见
[压缩实现说明](COMPRESSION.md)。原生物化与 Reader 桥接已实现，见 [Wrapper 指南](WRAPPERS.md)；
官方原始 benchmark parser、Reader/Evaluator 与完整离线实验已实现，见 [EXPERIMENTS.md](EXPERIMENTS.md)。

## 九类 baseline

| 方法 | 必要的通用数据 | 动作/执行特点 | 主要分析出口 |
| --- | --- | --- | --- |
| RecordFolder / ContextFolder | 文本、语义向量、实体特征、时间、anchors | 原 G1S 分组；Native Merge 或原 V12 Merge/Rewrite | grounding、anchors、候选、score、gate、matching、托管 |
| MemForest | 文本/向量；MST 变体另用时间/聚类信息 | 文本 MST 逐轮 merge；M3 proxy 可一次规划 | cluster、树边、路由、重嵌入、budget |
| ToMe | 同空间向量、可聚合 mass、有序节点 | BSM、pooled features；文本与 M3 版本分别登记 | pair 分数、匹配、质量累积、轮次 |
| DART | 当前本地记忆版本使用 pivots、向量、seed | Keep/Drop；官方 token 版本另需 tensor/model adapter | pivot、距离、排名、淘汰理由 |
| StreamMeCo | 完整方法需要图连接、权重、向量和时间 | Keep/Drop；方法相关检索策略属于 Reader 插件 | 孤立/连接节点、权重、选取理由、检索时间衰减 |
| RandomMerge | 稳定 ID、scope、seed | 显式随机分组 + Merge；原始或逐轮方案分别登记 | 随机种子、成员、round |
| RandomPrune | 稳定 ID、scope、seed | Keep/Drop，可零预算 | 选取/删除清单、来源保留率 |
| KmeansPrune | 向量空间、cluster assignment、centroid features | cluster 内选择代表 + Keep/Drop | label、距中心距离、每簇配额 |
| KmeansMerge | 向量空间、cluster assignment | cluster 分组 + 可替换 Merge Operator | label、成员、文本变化、token 配额 |

所有名字还需要独立 version/variant/provenance。不能把本地的 average-linkage proxy
命名成官方 MemForest 复现，或把 similarity-pruning proxy 命名成完整 StreamMeCo。
本地 DART 的随机锚点/medoid 版本都是记忆适配；[官方 DART](https://github.com/ZichenWen1/DART)
处理多模态模型的 token reduction。core 能承载 token/tensor 单位，但 model forward 集成不在本模块实现。
[官方 StreamMeCo](https://github.com/Celina-love-sweet/StreamMeCo) 基于 M3 memory graph 并包含压缩后的推理路径；
其图剪枝和时间检索要求需在 method + Wrapper + Reader 的锁定 recipe 中同时体现。
当前已移植官方 StreamMeCo 的图压缩阶段；其时间检索 Reader 尚未移植。KMeans 两方法按用户确认的
每 scope K=保留节点数定义实现。MemForest 的历史 cluster ceil 与精确 scope 预算适配分别配置。

## 四类 benchmark

| Benchmark | 输入表示 | 评测差异 |
| --- | --- | --- |
| LoCoMo | 原始对话历史或已建记忆，speaker/session/time 可保留 | QA、类别、证据留给 Evaluator |
| PersonaMem | 历史、persona/user 元数据、初始 memory | 偏好/画像标签及公开选项用独立 JSON 表达 |
| LongMemEval | 多 session 历史、绝对时钟、query as_of | 时序/更新/拒答/多答案协议由 evaluator 解释 |
| M3 robot/web | 图、clip、身份节点、多模态 artifact、可见时间 | 开放问答/读端控制与图检索协议独立 |

M3 benchmark 与 M3 框架是两个不同插件维度，不能用一个 `backend=m3` 同时代表二者。
benchmark 不强制某个后端；具体后端能否提供所需图、模态、clip 或 streaming 能力由声明决定。

## 三类框架

| 框架 | Wrapper 的责任 |
| --- | --- |
| Mem0 | 导出 payload/身份/向量；project 生成规范视图；最终文本与新向量物化为新实验库；原生 reader 能力声明 |
| MemOS | 导出 cube/关联和原生 metadata；明确保持 cube 边界或授权跨域；保留缺失依赖状态 |
| M3 | 导出 text/face/voice/identity、图边、clip 与 asset；project 按原生语义重连；保留 reader 的可见性 |

`MemoryRecord.native` 是 JSON 数据，原生对象/连接留在 Wrapper，不泄漏到 Planner 或 Observer。
`MaterializedView.node_id_map` 提供 canonical node ID 到 native ID 的可追踪映射。
流式框架可额外实现 `StreamingMemoryWrapper.ingest`；离线 Wrapper 无需假装支持在线更新。

## 插件作者怎么扩展

1. 实现一个完整 Planner，或只替换 feature/candidate/scorer/gate/matcher 小组件。
2. 声明 `PluginSpec` 的 API、requires/provides、动作、执行模式与诊断 schema。
3. 用 Keep/Drop/Merge/Rewrite 构建计划；新动作则声明 namespaced `ActionRule`。
4. 方法自有数据用 namespaced extensions/AlgorithmState，无需改通用 record。
5. 输出值经过 core validators；当前 registry/assembler 负责嵌套配置加载，调用方注入实时服务。

`validate_composition` 当前已实现能力、API、动作、执行模式检查。
数据加载、Planner / Operator 和 Wrapper 的配置组装已实现。原生文件输出、新 Qdrant 库、
配置好的 MemOS 实例加载和 M3 原生对象桥接可用，支持范围见 [WRAPPERS.md](WRAPPERS.md)。
Reader、评分插件和离线整链已实现；完整 SDK 生命周期、在线事务与真实模型成绩另行验收。
135 组合成 shape 是 wire 与不变量验收。另有实际压缩行为、原始代码对齐、独立插件安装和两份真实记忆库
贯通检查；真实库 Merge 使用拼接算子验证来源守恒，没有模型调用或 QA 指标复现。
