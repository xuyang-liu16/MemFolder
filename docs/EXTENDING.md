# 接入新 benchmark 与外部模块

完整离线实验支持安装外部插件、修改配置后运行。核心契约和 Runner 不需要 benchmark 名称分支。
数据/初始化/压缩/原生写入/Reader/Evaluator/Observer 均已接入组装器，见 [EXPERIMENTS.md](EXPERIMENTS.md)。

## 两条独立的扩展边界

| 扩展对象 | 插件 role / 方法 | 输出 | 新组件负责的语义 |
| --- | --- | --- | --- |
| benchmark | `data_loader` / `samples()` | `DatasetSample` 迭代器 | 历史、样本归属、问题、答案、查询时间、评分 protocol |
| 原生记忆库 | `memory_loader` / `load(observer=...)` | `LoadedLibrary` | 存储格式、owner / cube / clip、图索引与向量 |

benchmark 采用已有 Mem0 / MemOS / M3 格式时，复用 `memfolder.loading` 的加载器。已有库由 `MemoryInput.initial_snapshot` 表达，原始历史由 `MemoryInput.history` / history_artifact 表达，均适配同一后续接口。历史 artifact 必须只含历史输入，不能引用包含评测答案的混合文件。

原始存储有新的字段结构时，只实现 `FormatAdapter.decode()`；全新文件 / 数据库 transport 只实现 Reader。新 benchmark 不要求再写一套数据库读取器。`attach_evaluation` 可以拼接既有记忆与评测数据，但插件必须明确对齐 dataset/sample/split/version，不能按列表位置拼接。

## 插件的最小约定

1. 工厂暴露 `.spec = PluginSpec(...)`，声明 `plugin_id`、`role`、`api_version` 和能力。
2. 工厂签名为 `build(parameters: FrozenMap, *, context: BuildContext)`，返回对应角色的实例；实例 `.spec` 与工厂一致。
3. 插件验证自己的参数和输入格式。未知参数明确失败，模块自有字段放入 namespaced extensions / native，新增核心语义走版本化契约。
4. `context.path(...)` 把相对数据路径解析到配置文件目录，不依赖启动进程的工作目录。若 CLI 需要保护原始目录，实例暴露 `source_paths`。
5. 资源由插件迭代器管理，在 finally 中关闭。完整实验消费同步或异步迭代器，结束或异常时关闭；动态 loader 声明 source_paths 或 input_fingerprint 以支持校验恢复。

模块导入时不初始化模型、数据库或 API 客户端。安装发现只读取 entry-point 元信息，未选择的插件及可选依赖不会被导入。注册器没有全局实例；重复名称、角色冲突、API 版本冲突、缺能力、工厂改变声明都明确报错。

## 两种挂载方式

开发中的模块可以直接配置：

```json
{
  "plugin": "my_benchmark:build",
  "parameters": {"path": "data/dataset.json", "split": "test"}
}
```

`my_benchmark` 必须是当前 Python 环境可导入的模块。插件工厂是显式 Python 代码入口，普通记忆数据文件不会自动导入其中指定的模块。

发布成独立包后，在插件自己的 pyproject.toml 声明：

```toml
[project.entry-points."memfolder.plugins"]
"lab.newbench" = "my_benchmark:build"
```

安装此包后，配置只需改为 `"plugin": "lab.newbench"`。不修改 MemFolder 的 __init__、内置 catalog、CLI 或压缩方法。内置 catalog 仅登记项目自带插件，外部模块通过统一注册器挂载。

如果已输出统一的 `DatasetSample` wire JSONL，也可以直接用内置 `dataset-jsonl`，无需自定义解析器。

## 一个实际可安装的例子

[外部示例包](../examples/plugins/new_benchmark/newbench_plugin.py) 在 src 之外，包含独立 pyproject.toml、2 个合成对话和配置。这是接口演示，不是新的科学 benchmark 或问答质量结果。

在开发环境安装 MemFolder 和该插件后，从 memfolder 项目目录运行：

```powershell
python -m memfolder.benchmarks --config examples/plugins/new_benchmark/config.json --output-dir runs/newbench-import-001
```

通用驱动产生 2 个样本、3 条历史事件、2 个问题。输出 memory.jsonl、evaluation.jsonl 和 report.json。evaluation.jsonl 含答案，仅交给 Evaluator；记忆分析回调与 Reader 的公开问题都不含标签。

Python 中可逐样本消费：

```python
from memfolder.benchmarks import load_benchmark_config

stream = load_benchmark_config("my-config.json", observer=my_memory_observer)
for sample in stream.samples():
    wrapper_input = sample.memory
    reader_questions = sample.evaluation.reader_input()
    evaluator_labels = sample.evaluation
```

驱动检查 DatasetSample 类型、样本身份不重复和 memory/evaluation 对齐。空选择默认失败；确需空 split 的程序调用显式 allow_empty=True。不会静默截断超出限制的文件。迭代驱动不物化整个 benchmark，具体插件仍负责其文件格式的读取策略。

## 配置化加载已有记忆库

```json
{
  "plugin": "mem0-sqlite",
  "parameters": {
    "path": "data/collection/mem0/storage.sqlite",
    "options": {"dataset_id": "mybench", "sample_id": "case-001"}
  }
}
```

```powershell
python -m memfolder.loading --config memory-config.json --output-dir runs/import-001
```

原有 `python -m memfolder.loading mem0-qdrant PATH ...` 用法保留，并走同一注册器。外部 memory_loader 可同样使用安装名或 module:factory。binding.json / benchmark report 记录角色、API 版本、工厂模块源码哈希和参数指纹，不保存原始配置；源码哈希当前覆盖工厂模块，完整依赖版本与模型身份仍需后续 RunManifest 收集。

## 新 benchmark 的维护与验收要求

- 保留原始 ID、native 字段、未知时间 / 模型信息；显式声明 partition、时间单位、时区和多模态资产归属。
- 文件和 conversation 边界可能不同；明确提供 owner → 样本映射，不在通用代码里猜姓名或目录后缀。
- 通过 SampleRef 的 dataset_fingerprint 标识数据版本；问题和记忆必须引用相同 SampleRef。
- 新评分任务实现或复用对应 Evaluator。数据加载成功不意味着已正确复现评分协议。
- 插件自带小 fixture 和契约检查：重复 / 缺失 / 空数据、样本隔离、原字段与向量保真、标签隔离、版本冲突、资源关闭。
- core 不 import 具体 benchmark；驱动不包含 if benchmark == ...；外部包不依赖项目内部 helper。

现有 4 个 benchmark 原始文件解析与版本化评分已实现，见 [BENCHMARKS.md](BENCHMARKS.md)。
新 benchmark 只需贡献 loader，并选择或贡献 metric；不改 Runner。所需模态、时间和后端能力仍应显式匹配。

## 验证证据

`tests/test_plugins.py` 和 `tests/test_benchmarks.py` 覆盖扩展边界。`tools/check_plugin_installation.py` 从隔离安装的 MemFolder wheel 与独立插件 wheel 验证真实 entry-point 发现、配置运行和标签隔离；不是用源码路径替代插件安装。

`build/plugin_validation/installation_validation.json` 给出本次安装验收；`build/contract_validation.json` 给出当前源码测试。原生记忆库验收另见 `build/real_loading_validation/user_library_validation.json`。
