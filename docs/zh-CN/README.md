# 文档索引

[English](../README.md) | [简体中文](README.md) · [项目首页](../../README.zh-CN.md)

MemFolder 压缩智能体保存的历史记忆，并评测使用压缩记忆后的问答效果。建议先运行离线示例，再接入自己的数据和模型服务。

## 运行实验

| 你要完成的任务 | 阅读指南 |
| --- | --- |
| 安装、运行示例、比较多组配置 | [实验指南](EXPERIMENTS.md) |
| 使用 RecordFolder、ContextFolder 或基线方法 | [压缩方法](COMPRESSION.md) |
| 读取 Mem0、MemOS 或 M3 记忆库 | [加载记忆](LOADING.md) |
| 选择数据集和评分方法 | [基准与评测](BENCHMARKS.md) |
| 查看统一的 merge、QA 和 judge 模板 | [MemForest 提示词协议](PROMPT_PROTOCOL.md) |
| 按框架格式保存压缩记忆 | [框架接入](WRAPPERS.md) |
| 查看分组、检索内容和答案 | [运行分析](ANALYSIS.md) |

第一次使用时，从[实验指南](EXPERIMENTS.md)开始。已有记忆库时，继续阅读[加载记忆](LOADING.md)。[支持的配置](COMPATIBILITY.md)汇总了各方法和框架需要的数据与服务。

## 开发组件

[添加组件](EXTENDING.md)介绍插件的实现、安装和配置方式。[数据类型与接口](CONTRACTS.md)解释加载、压缩、检索和评测之间传递的对象。

## 阅读论文结果

[论文结果](PAPER_RESULTS.md)收录完整对比表格。[图片来源](../assets/README.md)记录各图及数值的来源，代码来源和署名见[第三方说明](../THIRD_PARTY_NOTICES.md)。
