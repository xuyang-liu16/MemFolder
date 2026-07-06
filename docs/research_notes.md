# 调研笔记：Agent Memory Compression

## 一屏结论

| 结论 | 对本项目的影响 |
|---|---|
| Agent memory compression 已经不是空白问题 | 不能泛泛 claim “首次压缩 Agent memory” |
| StreamMeCo 是直接 baseline | 必须弄清它如何剪枝 M3-Agent memory graph |
| MemForest 是强相关先导工作 | 必须弄清 EventTree、progressive merging、AGPR 的边界 |
| 下一步机会在 online、temporal budget、多模态细节保留 | 项目应聚焦更具体的问题定义 |

## 领域分层

| 层级 | 代表方向 | 与本项目关系 |
|---|---|---|
| Prompt / context 压缩 | LLMLingua、Selective Context | 可作为 retrieved memories 的辅助压缩 |
| KV-cache 压缩 | H2O、StreamingLLM、SnapKV | 解决推理缓存，不直接管理长期记忆 |
| Agent memory 系统 | MemGPT、Mem0、Zep、MemoryOS | 提供长期记忆存取框架 |
| 多模态长期记忆 | M3-Agent、MovieChat、MIRIX | 提供多模态 memory 表示和评测背景 |
| Agent memory compression | StreamMeCo、MemForest | 本项目最直接相关层 |

## StreamMeCo / MemForest 对照

| 维度 | StreamMeCo | MemForest | 我们需要推进的点 |
|---|---|---|---|
| 压缩动作 | 偏冗余节点删除 | 偏相似事件合并 | 时间窗口级动态预算 |
| 主要对象 | M3-Agent memory graph | Mem0 + M3-Agent memory | 纯文本起步，多模态扩展 |
| 时间处理 | 待深读复核 | 语义-时间结构，待深读复核 | 显式约束 temporal continuity |
| 任务条件化 | 待深读复核 | query 主要用于 retrieval，待深读复核 | 让 task/query 影响 compression policy |
| 在线更新 | 待深读复核 | 可能偏 post-hoc，待深读复核 | 支持 bounded online memory growth |

## 当前不能直接写的 claim

| Claim | 原因 |
|---|---|
| 首个 Agent memory compression | StreamMeCo / MemForest 已覆盖关键空间 |
| 首个 M3-Agent memory graph compression | StreamMeCo 已是直接近邻 |
| event-level memory compression 首创 | MemForest 已有 EventTree / merging 设计 |
| 固定比例压缩不足即可证明我们优越 | 需要和 StreamMeCo / MemForest / recency / random 对照 |

## 推荐阅读顺序

| 顺序 | 内容 | 目标 |
|---:|---|---|
| 1 | StreamMeCo paper + repo | 明确 pruning 策略、评测协议、压缩对象 |
| 2 | MemForest paper + repo | 明确 merging 策略、AGPR、Mem0/M3-Agent 适配 |
| 3 | LoCoMo | 理解文本长期记忆 QA 任务 |
| 4 | MemEye | 理解视觉 / 多模态长期记忆评测 |
| 5 | MixKV / VidCom2 / V-CAST | 借鉴长短期组合和动态预算思想 |

