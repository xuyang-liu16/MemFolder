# 运行实验

[文档索引](README.md) · [English](../EXPERIMENTS.md)

一次实验会依次加载记忆、压缩记忆、按问题检索相关记录、生成答案并评分。JSON 配置文件指定数据、压缩方法、模型服务和输出目录。

## 运行离线示例

使用 Python 3.11 或更新版本，在仓库根目录执行：

```bash
python -m pip install -e .
python -m memfolder run examples/experiments/offline-demo.json
python -m memfolder verify build/experiments/offline-demo
```

示例包含四条合成对话，使用随机分组和文本拼接，回答组件直接返回检索到的上下文。它只依赖 Python 标准库，评分标记为 `test_only`，适合检查安装和了解输出文件。

`run` 命令会输出运行 ID、样本数、压缩状态、评测状态和结果目录。`verify` 检查文件及哈希，通过后输出 `"status": "verified"`。

## 配置 RecordFolder 或 ContextFolder

先安装实验模板使用的依赖：

```bash
python -m pip install -e ".[algorithms,contextfolder,evaluation]"
```

以 [recordfolder-template.json](../../examples/experiments/recordfolder-template.json) 或 [contextfolder-template.json](../../examples/experiments/contextfolder-template.json) 为起点。这两个模板都包含数据加载、压缩、回答和评测。运行前填写以下字段：

| 字段 | 需要填写的内容 |
| --- | --- |
| `dataset.parameters.path` | 数据集路径；模板默认使用小型示例 |
| `services.*.parameters` | 文本生成、实体抽取服务的 URL、模型名称和版本 |
| `services.embeddings.parameters.provider.parameters` | 向量服务的 URL、模型名称和版本 |
| `compression.features` 中 `semantic-encoder.parameters.space` | 与向量服务一致的模型信息和向量维度 |
| `output_dir` | 本次实验使用的新目录 |

将 `REPLACE_*` 和 `https://api.example.invalid/v1` 替换为实际设置。在启动实验的终端中设置 `MEMFOLDER_PROVIDER_KEY`：

```powershell
$env:MEMFOLDER_PROVIDER_KEY = "YOUR_API_KEY"
```

Bash 等终端使用：

```bash
export MEMFOLDER_PROVIDER_KEY="YOUR_API_KEY"
```

完成配置后运行：

```bash
python -m memfolder run examples/experiments/recordfolder-template.json
python -m memfolder run examples/experiments/contextfolder-template.json
```

相对路径以配置文件所在目录为起点。例如，`examples/experiments/` 中的 `../../build/experiments/recordfolder-001` 指向仓库根目录下的 `build/experiments/recordfolder-001`。

ContextFolder 通过 `contextfolder-qa-prompt` 引导问答模型读取编码后的记忆，调整模板时请保留这一设置。接入已有记忆库时，按[加载指南](LOADING.md)配置 `bank-initializer`。

## 理解配置结构

| 配置项 | 用途 |
| --- | --- |
| `dataset` | 加载对话历史、问题和评分标签 |
| `initializer` | 从历史建立记忆，或选择已有记忆库 |
| `compression` | 选择分组方法、文本处理方法、特征和输出框架 |
| `reader` | 检索记录、组织上下文并生成答案 |
| `evaluator` | 评测答案和检索证据 |
| `services` | 配置文本生成、向量和 token 计数服务 |
| `run` | 设置随机种子、记录预算、运行轮次和原始记忆对照 |
| `capture`、`observers`、`redactor` | 选择过程记录、分析组件和脱敏方式 |
| `output_dir` | 设置实验保存位置 |

问答实验同时配置 `reader` 和 `evaluator`。只做记忆压缩时可省略两者。压缩阶段接收记忆，回答阶段接收问题，评测阶段接收参考答案和证据标签。

下面的设置在每个 scope 内保留一半可压缩记录，并对原始记忆做相同评测。scope 是加载器定义的记录范围，例如同一会话或同一视频片段。

```json
{
  "run": {
    "seed": 7,
    "evaluate_source": true,
    "budgets": [{"unit": "nodes", "ratio": 0.5}]
  }
}
```

`ratio` 表示保留比例。`nodes` 控制记录数量，文本长度由 tokenizer 另行统计。文本 ToMe 和 MST MemForest 需要设置 `run.mode: "repeat"`，逐轮合并并更新向量，详见[压缩方法](COMPRESSION.md)。

## 比较方法与随机种子

```bash
python -m memfolder matrix examples/experiments/offline-matrix.json
```

该示例比较 RandomMerge、RandomPrune，以及随机种子 7、11，共四次运行。矩阵配置的 `axes` 指定要变化的字段，`seeds` 列出种子，`max_runs` 限定组合总数。每次运行都有独立目录和运行清单。

## 查看输出

| 文件或目录 | 内容 |
| --- | --- |
| `sources.json` | 输入文件及指纹 |
| `run.manifest.json` | 组件版本、运行状态及结果文件引用 |
| `result.json` | 各样本的压缩统计与评测结果 |
| `completion.json` | 完成运行的校验信息 |
| 各样本目录 | 原始与最终记忆、每轮压缩过程、框架格式文件、预测及评分 |
| `trace/` | 启用 capture 后记录的事件及索引 |
| Observer 报告 | 分析组件生成的报告 |

压缩统计包含记录数、字符数和边数。配置 tokenizer 后，还会记录 token 数及计数方式。服务使用情况包括调用次数和可获取的用量信息。耗时包含运行中保存记录和执行分析组件的开销。

`evaluate_source: true` 会让原始和压缩后的记忆使用同一套问答与评测配置，并分别保存结果。单条记录或单道问题的查看方式见[运行分析](ANALYSIS.md)。

## 复用结果或重试

输入与配置相同时，可复用已完成的实验：

```bash
python -m memfolder run examples/experiments/offline-demo.json --resume
```

复用前会核对输入、配置、组件、运行环境和文件哈希。修改这些内容后，请使用新目录。失败的实验会保留已经写出的文件，便于排查；修复原因后，在新目录重跑。`--resume` 处理已完成的运行，部分完成的目录可用于诊断。

CLI 失败时显示异常类型。在 Python 中调用 `assemble_experiment(config, base_path=...).run()`，可以获取完整异常。自行注入的服务通过 `cache_identity` 声明复用标识，并由调用方负责关闭。

## 按目的验证实验

离线示例检查执行过程和文件完整性。评测问答质量时，需要目标数据集、记忆库、模型设置和对应的[评分协议](BENCHMARKS.md)。复现论文比较还需要对齐方法变体、记录预算、提示词、随机种子和向量模型。[论文结果](PAPER_RESULTS.md)列出了原稿实验的分数。

开发时可运行：

```bash
python tools/fetch_test_sources.py
python tools/check_contracts.py
```

下载脚本将固定版本的测试来源保存到 `build/` 并检查哈希。集成测试使用环境中已提供的依赖和源码归档。CI 在 Python 3.11、3.12 上执行测试和离线示例。
