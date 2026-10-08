# 记忆库加载模块

实现入口是 `memfolder.loading`。它读取**已经构建好的记忆库**，输出严格验证的
`LoadedLibrary → MemoryInput → Snapshot`，可以直接接上后续 Planner。
压缩方法、检索、评测、LoCoMo/PersonaMem/LongMemEval/M3 原始 benchmark 文件解析属于其他模块。

## 当前支持的格式

| 输入 | 调用 | 保留内容 |
| --- | --- | --- |
| Mem0 API 的 `results` 或记录列表 | `load_mem0(path)` | memory、原始 ID、user/agent/run、原始元数据 |
| Mem0/Qdrant point JSON、JSONL、scroll REST 文档 | `load_mem0(path)` | payload、所有 dense/named vectors、原始 sparse vector |
| 旧实验 exporter 的 RecallFlow MemoryNode JSONL | `load_mem0_legacy_nodes(path)` | source.point_id、user_id、sample_id、text、embedding、原始字段 |
| Mem0 本地 Qdrant 目录或包含 `qdrant/` 的库目录 | `load_mem0_qdrant(path, collection=...)` | 所有分页中的 point 与向量；SDK 只打开临时副本 |
| Mem0/Qdrant 离线 `collection/mem0/storage.sqlite` | `load_mem0_sqlite(path)` | 无需 meta.json 或 SDK；原始 payload、ID、向量逐值保留 |
| 调用方已经创建的 Qdrant client | `load_mem0_client(client, collection=...)` | 完整 scroll；连接和鉴权由调用方管理 |
| MemOS 普通文本列表或 tree 的 `nodes/edges` JSON | `load_memos(path, options=...)` | memory、cube、metadata、图关系、权重、状态、向量 |
| MemOS cube 目录 | `load_memos_cube(path)` | 按 `config.json` 的实际文件名读取；支持多个 cube 的 `MemOSCubeLoader` |
| MemOS cube 的 activation/parametric 组件 | 同上 | 带 SHA256 的受保护 artifact 引用；不会执行 pickle 或模型 |
| M3 官方/旧模块名的 VideoGraph `.pkl/.pickle` | `load_m3(path)` | 全部节点、向量、图边、clip、检索索引、身份映射、原始类型 |
| M3 图的 JSON 值导出 | `load_m3(path)` | 同上；字段为 video_id/nodes/edges 及原生索引 |
| 本项目的统一记忆包 | `save_library(...)` / `load_library(...)` | 全部契约、原生字段、诊断报告，重载后严格相等 |

JSON/JSONL/cube 文本和 Qdrant SQLite 读取只使用标准库。Qdrant 原生目录的 SDK 读取需要可用的 `qdrant-client`；
含 NumPy 数组的 M3 pickle 需要可用的 `numpy`。这些依赖在读取对应格式时才导入。
加载模块不会初始化 Mem0/MemOS/M3 模型，也不会触发 embedding/LLM 请求。

Mem0 的 SQLite `history.db` 是操作历史，**不是当前完整向量记忆库**；本模块不会把它误当成当前库。
MemOS 原始 PostgreSQL、Neo4j 目录、SQL dump 以及 Qdrant 服务端 snapshot 压缩包需要相应原生工具导出，
或者增加一个 Reader。当前本地 Qdrant reader 对应 `QdrantClient(path=...)` 的目录格式。

### 拆分备份与 SQLite

备份中的 `meta.json` 和 `storage.sqlite` 可能分布在不同目录。可以显式提供
`load_mem0_qdrant(bank_path, metadata_path="another-backup/qdrant/meta.json")`；
两个来源只会在临时副本中组装，原目录不会补文件。缺少元信息时 SDK 入口明确失败，
不会初始化一个新库再把它误报为空库。

只导入记忆记录时，直接 `load_mem0_sqlite(".../collection/mem0/storage.sqlite")`。
该入口用临时副本和 SQLite 只读连接，要求原库已经离线且 WAL/journal 为空；
逐条验证持久化 key 和 PointStruct.id 相符，拒绝未知 pickle 类/函数和尾随数据。
PointStruct、SparseVector 被替换为惰性值容器，不执行 Mem0/Qdrant/Pydantic 模型代码。
向量保留持久化值；SDK 路径可能做 cosine 归一化及 float32 转换，两个入口可能有末位差异。
SQLite 入口不读取 collection 配置，距离度量、embedding 模型和 benchmark 样本映射需另行声明。
报告的 `persisted_rows_complete` 只表示读完该表，`coverage=unknown` 不声称拿到了完整原始记忆库。

实盘 LoCoMo 库中，一个文件包含多个对话。用确切的 owner 名单设置 `sample_map`，
或者 `selectors={"user_id": ["Caroline_0", "Melanie_0"]}` 后再指定 `sample_id="s0"`。
LongMemEval 的同一个问题包含 User/Assistant 两个 owner，可以显式使用 `sample_id="s000"`。
这些映射由调用者提供；加载器不会从文件名或 owner 后缀猜测样本归属。

## Python 使用

```python
from memfolder.core import EmbeddingSpace, FrozenMap
from memfolder.loading import LoadOptions, load_mem0_qdrant, native_vector_sets

library = load_mem0_qdrant(
    "path/to/mem0-store",
    collection="mem0",
    options=LoadOptions(
        dataset_id="locomo",
        split="test",
        sample_id="locomo-1",
        selectors=FrozenMap({"user_id": ("Alice_1", "Bob_1")}),
        naive_timezone="UTC",  # 只在你确定原始时区时设置
        embedding_spaces={"default": EmbeddingSpace(
            provider="your-provider", model="your-actual-model",
            revision="your-model-revision", dimension=1536,
        )},
    ),
)

for memory in library.inputs:
    snapshot = memory.initial_snapshot
    for node in snapshot.records:
        original = node.native["record"]
        all_vectors = native_vector_sets(node)

report = library.report  # 不含记忆正文、向量或完整模型配置
```

也可以直接 `load_mem0("export.json")`、`load_memos_cube("cube-directory")`、
`load_m3("bedroom.pkl")`。M3 视频 ID 默认取文件 stem；存在同名视频时必须逐库设置
`LoadOptions(namespace="robot/bedroom")` 或在 JSON 中提供明确的 `video_id`。

`JsonMemoryLoader(paths=(...), adapter=...)`、`MemOSCubeLoader(paths=(...))`、
`M3GraphLoader(paths=(...))` 支持多个文件。相同原生记忆重复导入会报错，不会覆盖或去重。

## 样本和压缩边界

Mem0 默认以第一个存在的 owner 作为样本：`user_id:<id>`、`agent_id:<id>`、`run_id:<id>`；
身份类别不同但字符串相同的 owner 不会混为一个样本。
partition 包含完整 user/agent/run 组合。无身份导出需要显式 namespace 或 sample_id。
MemOS 默认按 cube 分样本、按 cube 分 partition。
M3 默认按视频分样本，文本按 clip 分 partition；非文本节点属于受保护的 identity partition。

不同 speaker 属于同一个 benchmark conversation 时，先用精确 selectors 选中相关原生 owner，
再显式设置 sample_id。也可以用 `sample_map={"user_id:Alice_1": "locomo-1", ...}` 映射。
不存在 `_1`/`_11` 后缀猜测，也不会隐式合并其他用户。
合并后的原生 partition 仍然独立；是否允许跨 partition 压缩由后续 Planner 与运行配置明确决定。

canonical node ID 由框架、scope、native namespace 和原始 ID 确定，不会用加载顺序重新编号。
`OriginRef.source_id` 保留导入节点的原始 ID；历史 `sources`、`merged_from` 等仍在 native 元数据里，
它们不会被猜测成未经验证的原始压缩 lineage。
导入文件改名、Qdrant page_size 改变都不改变样本版本身份和 node ID。

## 字段和向量的解释

- 正文不会 strip、重写或默认拼成摘要。M3 多条 contents 转成多个 ContentPart，全部保留。
- 原始记录、未知 JSON 字段、时间字符串、所有向量均保留在 `node.native`。
- 没有模型身份时，向量留在 native，不会仅凭维度猜模型。`embedding_spaces` 显式声明后，
  单向量可以绑定成 `MemoryRecord.embeddings`；维度不符会报错。
- 上述绑定是对调用方/原生存储声明的信任。`source_fingerprint` 关联当前导入内容，
  **不能证明原存储中的向量确实由该内容生成**；native 标记为 `source_declared_unverified`，
  `native_vector_sets(...).content_verified` 为 false。
- 一个节点同一空间的多条向量全部保留，提供 `NativeVectorSet`；后续 FeatureProvider 明确选择
  pooling/routing 方法。本模块不会只取第一条或自动求均值。
- 稀疏向量保留原始 indices/values，不会伪装成 dense embedding。
- Mem0 entity relations 不是以 memory ID 为端点的边，原样保存在 snapshot 的导入 metadata 中；
  完整 Mem0 entity graph 的读取/检索还需要单独适配器。

M3 的 img、voice、equivalence 文本均设置 `eligible=False`，并禁止 drop/merge/rewrite。
`text_nodes`、`text_nodes_by_clip`、`event_sequence_by_clip` 与 forward/reverse character mapping
保持原顺序，并验证其引用与真实节点一致。双向存储的边逐条保留，不合并、不加倍权重。
NumPy 数组转换后保留 dtype/shape；不兼容的 pickle global/对象类型会明确报错，需转 JSON。
这是受限的迁移读取器，不是任意 Python pickle 的执行环境或资源消耗沙箱。

## 时间、完整性和一致性

默认保留事件 timestamp 原文。ISO 带时区日期可以转成 unix_seconds；无时区 ISO/LoCoMo 格式
需要显式 naive_timezone；数字 timestamp 的时钟/单位不作推测，可用 numeric_timestamp_clock 显式声明。
解析不了的事件时间给出 `timestamp_unparsed`，不会变成 0。
created_at/updated_at 默认保留在 native，不当成事件发生时间。
如确需存储可见时间，显式设置 `visibility_field="created_at"` 或点路径；该字段缺失/无法解析会报错。
M3 `available_at` 使用 `m3:<video>:clip`，不会假设 clip 为 30 秒。
官方 Reader 的 `before_clip` 是严格上界，后续 Reader 仍需实现相应查询规则。

旧 Mem0 exporter 用 timestamp=0 代替缺失/解析失败，本模块会报告 legacy_zero_timestamp。
不声明 numeric_timestamp_clock 时只保留原数字；历史 JSONL 已经丢失的原 payload/时间字符串无法恢复。

`order_by="source"` 保留来源顺序；`native_id` 按 partition/字符串 ID 排序；
`time_id` 按已解析事件时间和 ID 排序，缺时间或混用时钟时会报错。

`LoadReport` 给出每个来源的 SHA256、读入节点/边、保留/筛除计数、eligible 计数与 issue。
有未读下一页、MemOS total 与实读数量不一致时默认拒绝；显式 allow_partial 才能接受，并保留 partial 标记。
普通导出 JSON 无法证明调用者导出了所有记忆，coverage 为 unknown。
完整 Qdrant scroll 标记 declared_complete，但一致性仍为 best_effort：在线库变动时不保证原子快照。
临时副本读取前后检查原目录 inventory；这是变化检测，不代替停止写入后制作的离线快照。

重复 ID、非有限向量、非法维度、坏 JSON、悬空边、跨样本边及索引不一致会报错；不静默跳过坏记录。
显式 selectors 产生的子图计入 records_filtered/edges_filtered。
默认 max_records=1,000,000、max_file_bytes=2 GiB，可按实际库调整。
JSONL 文件按行解析；生成 Snapshot 时仍需容纳选中记忆。当前不是无限规模的磁盘流式索引。

MemOS activation/parameter artifact 不复制到统一 JSON 包，path 相对于原 cube；应一起保留 cube 文件。
M3 媒体内容/路径保留其原生值，不会下载、解码媒体或猜测外部文件根目录。

## 分析接口和扩展

`loader.load(observer=...)` 或 `load_mem0(..., observer=...)` 接受两个回调：
`on_input(MemoryInput)` 与 `on_report(LoadReport)`。回调在整库验证成功后触发，只接收不可变数据，
不接收连接、模型、原生图对象或评测答案。回调异常向上传播；不把失败分析报告伪装成成功。

配置化安装 / 发现外部插件、benchmark 接入与可安装的示例见 [EXTENDING.md](EXTENDING.md)。
原有 CLI 也支持 `--config plugin-config.json`，新插件无需增加命令行 choices 或修改 dispatcher。

新增文件/数据库 Reader 输出 `SourceDocument`；新增记忆格式实现 `FormatAdapter.decode` 输出
`NativeLibrary/NativeRecord/NativeEdge`，交给 `Importer(adapter=..., options=...)`。
无需修改 core 或各个压缩方法。参见 `test_contributor_format_adapter_works_without_core_or_dispatcher_edits`。
`attach_evaluation(library, evaluations)` 才组装为 DatasetSample，并严格核对 sample identity；
加载器不会编造空评测或把答案塞进记忆输入。

## 本地测试与命令行

源代码 checkout 下可运行：

```powershell
python tools/check_contracts.py
python examples/loading_demo.py
```

安装本项目后，导入实际库并输出新目录：

```powershell
python -m memfolder.loading mem0-qdrant "path/to/store" --collection mem0 --options my-options.json --output-dir imported-run-001
python -m memfolder.loading memos-cube "path/to/cube" --output-dir imported-cube-001
python -m memfolder.loading m3 "path/to/video.pkl" --output-dir imported-m3-001
```

输出 `library.json` 和不含正文/向量的 `report.json`。输出目录必须不存在，原记忆库保持原样。
`examples/loading_options.json` 使用 synthetic fixture 模型，实际测试前需要填写真实 owner 和模型信息，
或者删除 embedding_spaces，让向量保持未绑定状态。

可选真实 SDK 检查：`python tools/check_storage_loaders.py`。
源码测试证据在 `build/contract_validation.json`，SDK/NumPy 证据在 `build/storage_validation.json`。
本地实盘验收使用 `tools/check_user_libraries.py --inventory-dir <本地盘点目录> --sdk-path <可选SDK目录>`。
它按变体抽测 LongMemEval / LoCoMo 的真实 Mem0 库和 M3 robot 图，核对原始文本、
payload、向量、边、样本边界及原文件哈希。结果保存在 `build/real_loading_validation/`。
具体范围以 `user_library_validation.json` 为准；MemOS / PersonaMem / M3 web 的真实库
仍需提供；这份加载验收未执行检索、QA 或压缩质量评测。
后续 Wrapper 已在 Mem0 / M3 两份真实库验证原生物化与检索通路，见 [WRAPPERS.md](WRAPPERS.md)。

官方格式与旧实验代码的核对记录见 [LOADING_SOURCES.json](LOADING_SOURCES.json)。
核对固定版本的 [Mem0 Qdrant 实现](https://github.com/mem0ai/mem0/blob/abb81c88e1f738a8117d8293530fbc31a5ef8fd9/mem0/vector_stores/qdrant.py)、
[MemOS 图导出](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/graph_dbs/neo4j.py)
和 [M3 VideoGraph](https://github.com/ByteDance-Seed/m3-agent/blob/0e3e41939bd8a0b66d756e7b7eb8d5fe9992da5c/mmagent/videograph.py)。
