# 支持的配置

[文档索引](README.md) · [English](../COMPATIBILITY.md)

一次实验由数据集、记忆框架、压缩方法和问答评测组件组成。选择时需要对齐各自的数据与服务要求。本页汇总已实现组件，以及具体实验需要补充的设置。

## 压缩方法要求

| 方法 | 需要的输入 | 执行方式 |
| --- | --- | --- |
| RecordFolder | 文本、语义向量、实体特征和事件时间 | 分组并整合文本 |
| ContextFolder | RecordFolder 输入、chat 和 tokenizer | 分组后编码与验证 |
| RandomPrune / RandomMerge | 记录、稳定 ID 和随机种子 | 选择记录或随机分组 |
| KmeansPrune / KmeansMerge | 同一声明空间的向量 | 选择代表或合并聚类 |
| DART 记忆变体 | 向量、pivot 设置和种子 | 选择记录 |
| 文本 ToMe | 当前文本向量、可比较的事件时间或全部采用顺序时钟、chat 和 embeddings | 按时间二分、逐对合并、允许重复目的节点、立即更新向量 |
| LLMLingua-2 Context | 最终 Record 快照和 LLMLingua-2 服务 | 每条当前记录改写一次，默认保留率 0.55；官方实现为可选依赖 |
| M3 pooled ToMe | 向量和累计质量 | 按配置合并特征 |
| 文本 MemForest | 语义特征和事件时间 | 逐轮聚类并沿树合并 |
| M3 MemForest proxy | 向量 | 归档中的平均链接分组 |
| StreamMeCo 图压缩 | M3 图结构、向量和类别信息 | 应用 clip、sample 级选择规则 |

报告结果时保留具体变体名称。[压缩方法](COMPRESSION.md)解释了 MemForest 预算变体、StreamMeCo 配额和 DART 记忆适配。

## 数据集要求

| 数据集 | 需要保留的信息 | 评分设置 |
| --- | --- | --- |
| LoCoMo | session、speaker、对话 ID 和日期 | 分类 F1 和可选证据召回 |
| LongMemEval | session、日期和问题时间 | 固定版本提示词与 judge 模型 |
| PersonaMem v1 | 逐题历史前缀和公开选项 | 选项集合评分 |
| M3 robot/web | 视频身份、图、媒体引用和 clip 可见范围 | 开放问答和固定版本评分提示词 |

M3 的数据加载器定义任务和问题，M3 wrapper 定义图存储与检索。其他数据集/框架组合也可在样本、时间、图和模态要求匹配时组装。评分细节见[基准与评测](BENCHMARKS.md)。

## 框架输出与检索

| 框架 | 已实现的接入 | 需要的配置 |
| --- | --- | --- |
| Mem0 | point JSON、本地 Qdrant 输出和检索 | 内置 Qdrant writer 使用单一声明的稠密向量空间 |
| MemOS | 文本/树输出，加载到已配置实例 | cube 范围、组件资产和后端设置 |
| M3 | VideoGraph JSON/对象/pickle 和原生搜索 | 视频映射、图类及相容的文本向量 |

通用 reader 还提供词项检索、稠密向量检索、图扩展、时间衰减，以及调用方提供的 SDK 搜索服务。模板中的 answerer 使用文本 chat。需要多模态回答时，可增加读取相应内容片段的 answerer。

当前 runner 执行离线实验，支持一轮或多轮压缩。实时数据库事务、持续数据接入和上游 M3 多步控制器需要针对目标系统接入。StreamMeCo 上游的时间检索同样需要专用实现。文件格式说明见[框架接入](WRAPPERS.md)。

## 验证你使用的组合

先用离线示例检查安装，再用少量真实记忆检查加载和框架输出，最后用目标数据集与模型设置测量问答质量。各阶段分别检查记录、原始来源、图边、向量模型和评分协议。

仓库包含组件测试、源码对照测试、插件安装检查和可选存储集成检查，执行范围取决于环境中的依赖和源码归档。[论文表格](PAPER_RESULTS.md)给出了原稿相应设置下的实验结果。
