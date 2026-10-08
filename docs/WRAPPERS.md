# Wrapper：把压缩 pipeline 接入记忆框架

Wrapper 已接入 `assemble()`。数据加载器先产生 `MemoryInput`，组装器执行
`export → Planner/Operator → graph project → content embeddings → native encode → native write`。
方法实现不访问原生数据库；Wrapper 不包含某种 baseline 或 benchmark 的分支。

| 框架 | 当前输出与回读 | 具体边界 |
| --- | --- | --- |
| Mem0 | points JSON；新本地 Qdrant collection；SDK 回读、过滤、向量检索 | Qdrant writer 当前支持未命名的 dense vector。JSON 可保留未修改的 named/sparse slots；修改这些 slots 必须提供专用 codec/writer。不自动重建 Mem0 history DB、独立实体图或 BM25 索引。 |
| MemOS | NaiveTextMemory 列表 / TreeTextMemory nodes+edges；配置好实例的 `.load()`；保留 activation/parametric 文件 | 不复制服务凭据或推测 LLM 配置。树文件已用官方 load 方法检查，尚未连接真实 Neo4j。其固定版本 import_graph 不写入边权；bundle 保留权重用于分析。联合 text/pref cube、额外引用字段需扩展 codec；多向量槽修改也需专用 codec，Keep 保留各槽。 |
| M3 | VideoGraph JSON；注入真实 VideoGraph 类后生成对象或原生 pickle；原生搜索与图遍历 | 每个输出对应一个 video；重建 text/clip/event/next-ID 索引。保留媒体和角色映射、等价文本。原生搜索要求统一的文本向量形状。 |

以上对应固定上游版本，来源与 SHA 见 [LOADING_SOURCES.json](LOADING_SOURCES.json)
和 [WRAPPER_SOURCES.json](WRAPPER_SOURCES.json)。未知格式明确拒绝，避免静默丢失数据。
这不是对所有 SDK 版本、存储后端或在线生命周期的自动适配承诺。

## 配置和运行

完整离线示例：`python examples/wrapper_demo.py`。其中 concat 和向量生成器只做通路测试。
真实实验使用自己的模型服务与已有 RecordFolder / ContextFolder recipe：

```python
from memfolder.assembly import assemble
from memfolder.core import BudgetRequest, EmbeddingSpace, to_data
from memfolder.compression import ServiceMap, DiagnosticCollector

space = to_data(EmbeddingSpace(provider="your-provider", model="your-model",
    revision="exact-model-revision", dimension=1536))
config["wrapper"] = {
    "plugin": "mem0-wrapper",
    "parameters": {
        "output_dir": "runs/new-run/memory",
        "codec": {"plugin": "mem0-codec", "parameters": {"space": space}},
        "writer": {"plugin": "qdrant-writer", "parameters": {"collection": "mem0"}},
        "embedding_provider": {"plugin": "content-embeddings", "parameters": {"space": space}},
    },
}
assembly = assemble(config, base_path=project_directory)
diagnostics = DiagnosticCollector()
run = await assembly.run(loaded_library.inputs[0],
    budgets=(BudgetRequest(unit="nodes", ratio=.5, minimum=1, rounding="ceil"),),
    services=ServiceMap({"embeddings": your_encoder, "chat": your_chat_client}),
    diagnostics=diagnostics)
```

Encoder 提供 `encode(texts)`，可同步或异步；必须与查询使用同一模型和版本。
`content-embeddings` 默认重嵌入所有缺少该声明空间的文本，包括受保护的身份文本；
不改变文本、权限或身份，不重新嵌入图像/音频。这样不会将旧未知模型和新模型混用。
`preserve_native=true` 配合 `source_slot` 是调用方对原始模型的显式声明，仅校验维度，
不等于验证了原始向量的内容绑定。Planner 的 pooled feature 不可作为原生内容向量。

MemOS 可使用 `memos-wrapper`、`memos-codec` 和 `memos-writer`。已加载的树即使剪枝后
没有边，也应显式设置 `backend="tree_text"`。带外部资产时配置
`asset_copier={"plugin":"verified-assets","parameters":{"root":"original-cube"}}`。
输出 `memfolder.memos.components.json` 记录组件文件，供配置好的 cube 使用；它不是
包含完整供应商配置的 `GeneralMemCube.dump`。`load_memos_view(out, configured_empty_memory)`
拒绝写入非空目标；配置的 memory_filename 应为 `textual_memory.json`。

M3 使用 `m3-wrapper` / `m3-codec`；默认 `m3-json-writer`。
`load_m3_view(out, VideoGraph)` 返回真实类对象；选择 `m3-pickle-writer` 时，通过
`ServiceMap({"m3.graph_type": VideoGraph, ...})` 注入真实可 pickle 的类。
不伪造生产 SDK 模块，不调用 caption/LLM 重建身份。
`open_qdrant_view(out)` 返回 client 和 collection，调用方关闭 client；SDK 客户端本身可写，
输出打开后发生修改会使原始 manifest 的校验失败。

## 独立可替换的模块

| 插件 role | 方法 | 默认实现 |
| --- | --- | --- |
| wrapper | export / project / materialize | FrameworkWrapper |
| graph_projector | project(source, plan, result, context) | RedirectEdges(max) |
| embedding_provider | refresh(snapshot, context) | ChangedTextEmbeddings |
| native_codec | encode(snapshot, archive, context) | Mem0Codec / MemOSCodec / M3Codec |
| native_writer | write(package, directory, context) | points / Qdrant / MemOS / M3 JSON或pickle |
| asset_copier | copy(snapshot, directory, context) | VerifiedAssetCopier |

新框架可只提交 codec/writer，选择 `framework-wrapper` 后配置这两个插件；特殊行为可
替换完整 Wrapper。插件经 `memfolder.plugins` entry point 或 `module:factory` 加载，
无需修改 registry、组装器、Planner 或 Operator。Factory `.spec` 必须声明相应 role。
所有这些调用都支持同步/异步。完整外部 writer 示例在
[examples/plugins/native_writer](../examples/plugins/native_writer)，它为原生写入追加案例来源映射。

默认投影将吸收节点的边重连至输出节点，删除被 prune 的边和压缩形成的自环；
保留已有自环。相同端点/关系/方向的边按 max/sum/mean 聚合；原始边和属性仍在
source snapshot 可查。专用图算法可替换 projector。单次动作一对多输出需专用 projector。
跨 scope 的合并仍由公共契约拒绝；cube/video 也由对应 codec 校验。

## 输出、分析和失败处理

每次写入必须使用不存在的新目录。原始库不会被 inplace 更新。写入完成才生成
`manifest.json`；失败目录留 `failure.json`，重试使用新目录。
`verify_materialization(out, artifact=run.materialized.artifact)` 校验完成状态、路径、
每个文件 SHA、规范快照和 ID 映射。原生文件写入不是服务数据库的跨资源事务。

Bundle 保存 `source.snapshot.json`、最终 `snapshot.json`、`native.package.json`、
native node ID 映射、origins/来源成员和文件 SHA；外部资产校验后按原相对路径复制。
`run.compression.steps` 保留每轮 request/plan/outcome；`run.snapshot` 是向量刷新后的最终快照。
研究者可比较源/终态，或通过冻结诊断的 export / edges / embeddings / materialized 事件
观察流转。可选插件增加自定义 case 文件，不影响 Planner/Operator。

## 验证证据

当前 272 项测试通过，其中 37 项 Wrapper 测试与 61 项完整实验测试；隔离依赖环境无跳过。
实际 Qdrant SDK 回读/查询通过；MemOS 官方模型与 Naive load/search 通过；Tree 官方
load 方法接收原生文件通过，未测试真实 Neo4j；M3 官方固定版类的原生 search/traversal
与 pickle 限制回读通过。测试从固定上游源码提取类/方法 AST，不启动其模型与配置副作用，
不等价于安装并验收三个完整 SDK。

真实本地 Mem0 LongMemEval：352 → 176 条，已生成新 Qdrant 库并查询。
真实 M3 study_04：365 → 203 节点，31 个保护节点保留，658 → 550 条边；原生搜索和索引检查通过。
原库 SHA 均不变。这两次使用 concat + 明确标注的离线测试向量，模型调用与 QA 评测均为 0，
只证明输入、压缩、原生物化、检索链路能接通，不能说明压缩质量或论文结果。

完整实验另增加未压缩对照、原生 Reader、合成回答/评分和 case 导出验收：
`build/experiment_validation/{mem0,m3}.json`，使用测试向量与 test_only 回答，真实模型 QA 次数为 0。
独立 Observer/Metric/Answerer wheel 与已有外部模块一起组成整条链，见 [EXPERIMENTS.md](EXPERIMENTS.md)。
