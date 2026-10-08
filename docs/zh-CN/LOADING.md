# 加载记忆

[文档索引](README.md) · [English](../LOADING.md)

`memfolder.loading` 读取已有的 Mem0、MemOS 或 M3 记忆库，返回包含各样本记忆和导入报告的 `LoadedLibrary`。每个样本的 `Snapshot` 保存可供压缩的记录、图边和资产引用。

从原始对话构建记忆时，先选择[基准加载器](BENCHMARKS.md)，再在[实验配置](EXPERIMENTS.md)中指定 initializer。

## 选择输入格式

| 输入 | Python 函数 | 依赖 |
| --- | --- | --- |
| Mem0 记录导出或 Qdrant point JSON/JSONL | `load_mem0(path)` | 标准库 |
| 历史 MemoryNode JSONL | `load_mem0_legacy_nodes(path)` | 标准库 |
| 本地 Qdrant 目录 | `load_mem0_qdrant(path, collection=...)` | `qdrant-client` |
| 离线 Qdrant `storage.sqlite` | `load_mem0_sqlite(path)` | 标准库 |
| 已创建的 Qdrant client | `load_mem0_client(client, collection=...)` | 调用方提供 client |
| MemOS 文本或树结构 JSON | `load_memos(path)` | 标准库 |
| MemOS cube 目录 | `load_memos_cube(path)` | 标准库 |
| M3 VideoGraph JSON 或 pickle | `load_m3(path)` | pickle 含 NumPy 数组时需要 NumPy |
| 已保存的 MemFolder 记忆包 | `load_library(path)` | 标准库 |

本地 Qdrant 加载器打开原库的临时副本。Mem0 的 `history.db` 保存操作历史，当前记忆记录位于 collection 的 `storage.sqlite`。PostgreSQL、Neo4j 和服务端 snapshot 需要先导出为支持的格式，或接入专用 reader。

## 从命令行导入

读取本地 Qdrant 库时，先安装可选依赖：

```bash
python -m pip install -e ".[qdrant]"
python -m memfolder.loading mem0-qdrant "path/to/store" --collection mem0 --options my-options.json --output-dir imported-memory-001
```

`my-options.json` 描述要读取的样本。下面选择同一对话的两位参与者：

```json
{
  "dataset_id": "locomo",
  "split": "test",
  "sample_id": "conversation-1",
  "selectors": {"user_id": ["Alice_1", "Bob_1"]},
  "naive_timezone": "UTC"
}
```

请填写实际 owner ID 和源数据时区。`sample_id` 将选中的 owner 归入一个基准样本，同时保留原始分区供后续压缩使用。

其他格式也会生成独立的导入目录：

```bash
python -m memfolder.loading memos-cube "path/to/cube" --output-dir imported-cube-001
python -m memfolder.loading m3 "path/to/video.pkl" --output-dir imported-video-001
```

输出包含 `library.json` 和 `report.json`。报告记录源文件哈希、节点与边数、筛选数量和解析问题。可通过 `python examples/loading_demo.py` 查看本地格式示例。

## 从 Python 导入

```python
from memfolder.loading import LoadOptions, load_mem0, save_library

library = load_mem0(
    "export.json",
    options=LoadOptions(
        dataset_id="my-dataset",
        sample_id="sample-1",
        namespace="store-1",
    ),
)

for memory in library.inputs:
    snapshot = memory.initial_snapshot
    print(memory.sample.sample_id, len(snapshot.records))

save_library(library, "imported-library.json")
```

先选定属于同一样本的记录，再填写 `sample_id`。一个文件包含多个样本时，通过 `sample_map` 提供精确的 owner 到样本映射。默认情况下，Mem0 按 owner、MemOS 按 cube、M3 按视频划分样本。M3 文本进一步按 clip 分区，媒体和身份节点受到保护。

## 在实验中使用已有记忆库

`bank-initializer` 将基准样本 ID 映射到记忆加载器。例如，对样本 `demo`：

```json
{
  "initializer": {
    "plugin": "bank-initializer",
    "parameters": {
      "loaders": {
        "demo": {
          "plugin": "mem0-sqlite",
          "parameters": {
            "path": "data/collection/mem0/storage.sqlite",
            "options": {"dataset_id": "locomo", "sample_id": "demo"}
          }
        }
      }
    }
  }
}
```

该加载器需要返回一个已选定的样本，且 dataset ID、sample ID 与基准一致。原库含其他对话时，通过 `selectors` 选出当前样本。实验随后将这份记忆与基准问题和评分标签配对。

## 声明向量与时间

原始字段和向量保存在 `record.native`。需要将某个向量用于计算时，在 `LoadOptions.embedding_spaces` 中声明槽位及真实的 provider、model、revision、dimension。模型身份未知的向量仍以原生字段保存。`native_vector_sets(record)` 可读取全部向量槽，包括多向量和稀疏向量。

导入时的模型声明代表调用方掌握的来源信息。改写文本后，重新计算向量可建立当前文本与向量的对应关系；具体步骤见[框架接入](WRAPPERS.md)。

| 时间字段或选项 | 含义 |
| --- | --- |
| `naive_timezone` | 原日期缺少时区时采用的源时区 |
| `numeric_timestamp_clock` | 数字时间戳的单位和时钟 |
| `visibility_field` | 用于确定可见时间的原字段 |
| 记录的事件时间区间 | 内容描述的事情发生在何时 |
| M3 clip 时钟 | 指定视频中的 clip 顺序 |

解析失败的时间保留在原字段中，并写入报告。`order_by` 可选 `source`、`native_id` 或 `time_id`；按时间排序需要已解析且可比较的时间。

## 检查导入范围

压缩前查看 `report.sources`。`declared_complete` 表示来源声明完整，`partial` 表示接受了部分导出，`unknown` 表示无法从文件确定原库覆盖范围。`records_filtered` 和 `edges_filtered` 记录显式筛选的数量。

读取 SQLite 时，使用已经停止写入、WAL/journal 为空的离线库。该入口检查临时副本并保留持久化向量值。Qdrant SDK 可能归一化向量或转换精度，因此数值对比应使用相同的导入方式。备份文件分散在不同目录时，可向 Qdrant 加载器明确传入 `metadata_path`。

加载器检查 ID、向量维度、图引用和样本归属。默认上限为一百万条记录、单文件 2 GiB，可通过 `LoadOptions` 调整。构建 `Snapshot` 时，选中的记录需要容纳在内存中。

MemOS 资产文件应和 cube 一起保存。M3 媒体路径沿用原始值，由读取媒体的组件负责解析。M3 pickle 加载器支持已识别的图和值类型；其他格式可先转成 JSON，或编写对应适配器。

## 添加格式

reader 从文件或数据库获取 `SourceDocument`，`FormatAdapter` 将其解析为记录和边，importer 再构建 MemFolder 数据对象。插件接入见[添加组件](EXTENDING.md)，内置格式采用的源码版本见 [LOADING_SOURCES.json](../LOADING_SOURCES.json)。
