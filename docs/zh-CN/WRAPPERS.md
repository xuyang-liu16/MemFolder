# 框架接入

[文档索引](README.md) · [English](../WRAPPERS.md)

wrapper 是框架适配组件，负责把压缩记录保存为目标框架的格式。它更新图关系、刷新文本向量、写入文件，并记录输出节点与原始记录的对应关系。

## 选择输出格式

| 框架 | 支持的输出 | 配置要点 |
| --- | --- | --- |
| Mem0 | point JSON 或新的本地 Qdrant collection | 内置 Qdrant writer 使用单一、未命名的稠密向量空间 |
| MemOS | NaiveTextMemory 列表或 TreeTextMemory 节点与边 | 加载到实例时，由调用方提供已配置的空 memory 对象 |
| M3 | VideoGraph JSON、指定类的对象或原生 pickle | 原生搜索需要匹配的文本向量维度和图类 |

Mem0 的 named/sparse 槽位可保存在未改写的 JSON 记录中；修改这些槽位需要对应的 codec 和 writer。历史数据库、实体图和附加搜索索引有各自的存储要求。

MemOS 的 activation 和 parameter 文件作为引用组件保留。包含额外跨组件引用的 cube，需要能处理这些引用的 codec。固定版本的 tree loader 可读取导出的图文件；真实 Neo4j 部署需要在目标环境中验证。源码版本见 [WRAPPER_SOURCES.json](../WRAPPER_SOURCES.json)。

## 运行本地示例

```bash
python examples/wrapper_demo.py
```

示例使用文本拼接和合成向量，展示导出、压缩、写入和重新读取。使用真实模型时，在[实验模板](EXPERIMENTS.md)中选择 wrapper。

以下配置创建新的 Mem0 Qdrant collection，可放入实验的 `compression.wrapper`：

```json
{
  "plugin": "mem0-wrapper",
  "parameters": {
    "output_dir": "runs/memory-001",
    "codec": {
      "plugin": "mem0-codec",
      "parameters": {
        "space": {"provider": "your-provider", "model": "your-model", "revision": "your-revision", "dimension": 1536}
      }
    },
    "writer": {"plugin": "qdrant-writer", "parameters": {"collection": "mem0"}},
    "embedding_provider": {
      "plugin": "content-embeddings",
      "parameters": {
        "space": {"provider": "your-provider", "model": "your-model", "revision": "your-revision", "dimension": 1536}
      }
    }
  }
}
```

安装 `.[qdrant]`，并提供具有 `encode(texts)` 接口的 `embeddings` 服务。存储文本与检索问题使用相同模型、版本和向量维度。完整实验会将各样本输出安排在运行目录下；直接调用 wrapper 时，使用其 `output_dir`。

## 理解写入过程

1. `export` 将输入记忆转为 `Snapshot`。
2. 压缩阶段产生动作计划和新记录。
3. `project` 根据保留与合并结果更新图边。
4. 向量组件为需要更新的文本计算 embedding。
5. codec 将最终记录转换为框架字段。
6. writer 保存文件，并生成完成清单。

默认图处理会把被合并节点的边连接到输出节点，删除被移除节点关联的边。相同端点和关系的边按配置的 `max`、`sum` 或 `mean` 合并。压缩产生的自环会移除，原有自环保留。

文本向量根据声明的空间更新。用于分组的聚合特征与存储文本的 embedding 各有用途。调用方能确认原向量模型时，可以通过 `preserve_native` 和 `source_slot` 指定复用。

## 读取输出

| 函数 | 返回或执行内容 |
| --- | --- |
| `open_qdrant_view(out)` | 返回 client 和 collection 名称，使用后关闭 client |
| `load_memos_view(out, configured_empty_memory)` | 将文件加载到指定的 MemOS 实例 |
| `load_m3_view(out, VideoGraph)` | 使用指定图类重建 M3 对象 |

这些函数由 `memfolder.wrappers` 导出。MemOS 树输出需要设置 `backend: "tree_text"`，最终边数为零时也保持该设置。输出 M3 原生 pickle 时，选择 `m3-pickle-writer`，并通过 `m3.graph_type` 服务传入真实图类。

## 检查输出文件

每次写入使用新目录，其中包含 `source.snapshot.json`、`snapshot.json`、`native.package.json`、框架文件、ID 映射、来源引用和哈希。完成写入后生成 `manifest.json`；失败时保留 `failure.json`，修复后在新目录重试。

`verify_materialization(out, artifact=...)` 检查文件、哈希、快照和 ID 映射。实验级命令 `python -m memfolder verify RUN_DIRECTORY` 也会检查引用的框架输出。编辑已保存文件会改变哈希，此时需要重新记录结果。

## 自定义接入

| 组件 | 职责 |
| --- | --- |
| `graph_projector` | 按压缩结果更新图边 |
| `embedding_provider` | 为存储内容计算向量 |
| `native_codec` | 转换成目标框架字段 |
| `native_writer` | 按目标格式写入 |
| `asset_copier` | 复制并验证引用文件 |

可以用 `framework-wrapper` 组装这些组件，也可以为特殊生命周期实现完整 wrapper。[原生 writer 示例](../../examples/plugins/native_writer)演示了如何附加输出与来源的映射文件。安装和注册步骤见[添加组件](EXTENDING.md)。
