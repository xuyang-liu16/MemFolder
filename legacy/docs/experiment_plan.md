# 实验计划：LoCoMo + MemEye

## 一屏结论

| 实验线 | 当前目的 |
|---|---|
| LoCoMo | 先验证 RecallFlow 在纯文本长期记忆压缩中的 recall coverage |
| MemEye | 验证视觉 / 多模态长期记忆中的证据保留 |
| StreamMeCo / MemForest | 作为必须对齐的直接 baseline |
| Online update 调查 | 决定是否需要自建 streaming evaluation wrapper |
| Bad case 分析 | 找出压缩后错在检索、时间断裂还是视觉证据丢失 |

## 评测矩阵

| 评测线 | Benchmark | 模型建议 | 目标 |
|---|---|---|---|
| 纯文本记忆 | LoCoMo | 固定 Qwen 系列文本模型，DeepSeek 可作备选 | 长对话、时间、多跳、开放问答 |
| 多模态记忆 | MemEye | 原生多模态 Qwen 系列 | 视觉证据、图文信息、长期多模态记忆 |
| 在线评测 | LoCoMo / MemEye wrapper | 与主评测一致 | 检查 memory 是否能边写入边压缩 |

## Baseline

| Baseline | 作用 |
|---|---|
| Mem0 / M3-Agent 原始系统 | 无压缩上限 |
| StreamMeCo | 删除式压缩 direct baseline |
| MemForest | 合并式压缩 must-beat baseline |
| FIFO / recency | 检查方法是否只是近因偏置 |
| random / fixed ratio | 检查方法是否超过简单预算策略 |
| embedding clustering | 检查 response fingerprint 是否优于普通 embedding 相似度 |
| similarity pruning / merging | StreamMeCo-like / MemForest-like proxy |

## RecallFlow v0 评测协议

| 阶段 | 任务 | 输出 |
|---:|---|---|
| 1 | 抽取统一 memory node | `node_id / text / timestamp / embedding / metadata / source` |
| 2 | 生成 probe queries | entity、temporal、event、task probes；不能使用测试问题 |
| 3 | 计算 response matrix | `A[q, i] = retriever_score(q, memory_i)` |
| 4 | 压缩 memory | response-space coreset + capsule builder |
| 5 | 评测 QA 和 evidence recall | budget-accuracy curve、evidence recall@k、latency |

Response 分数 v0 口径：

```text
S[q, i] = cosine(embed(q), embed(memory_i))
A[q, :] = softmax(S[q, :] / tau)
fingerprint(memory_i) = A[:, i]
mass_i = sum_q A[q, i]
```

`tau` 先固定为 `0.1`，后续只做敏感性分析，不作为方法主要调参点。

核心对比：

| 对比 | 目的 |
|---|---|
| RecallFlow vs embedding clustering | 证明压缩检索响应行为比压缩语义相似度更有效 |
| RecallFlow full vs prune-only | 证明 capsule / merge 有价值 |
| RecallFlow full vs merge-only | 检查保留 exception 是否防止 rare evidence 被抹掉 |
| no entity probes | 检查人物 / 偏好 / 地点问题是否下降 |
| no temporal probes | 检查 temporal QA 是否下降 |

## Online update 需要确认

| 调查项 | 需要回答 |
|---|---|
| 数据顺序 | benchmark 是否保留原始时间顺序 |
| 写入协议 | memory 是否能按 turn / image / event 增量写入 |
| 评测时机 | 问题是在全部写入后问，还是可在中间状态问 |
| 压缩触发 | 是否能每来一个 chunk 就触发 compression |
| 指标 | 是否能记录 update latency、memory size curve、retrieval latency |

如果原始协议不支持在线评测，则设计轻量 wrapper：按时间顺序喂入 memory，在每个窗口后触发压缩，并在 checkpoint 上评测 QA / retrieval。

## Bad case 表字段

| 字段 | 含义 |
|---|---|
| `sample_id` | 样本编号 |
| `benchmark` | LoCoMo / MemEye |
| `method` | baseline 或我们的方法 |
| `compression_policy` | RecallFlow / StreamMeCo / MemForest / random / recency / embedding clustering |
| `memory_size_before` | 压缩前记忆规模 |
| `memory_size_after` | 压缩后记忆规模 |
| `temporal_window` | 相关时间窗口 |
| `question_type` | single-hop / multi-hop / temporal / visual evidence |
| `error_type` | 检索失败、总结丢失、时间断裂、视觉细节丢失等 |
| `notes` | 人工分析备注 |

## 近期实验顺序

| 顺序 | 任务 | 产出 |
|---:|---|---|
| 1 | 确认 LoCoMo / MemEye 入口 | smoke test 能否启动 |
| 2 | 固定模型配置 | model id、token 成本估计 |
| 3 | 实现 RecallFlow v0 | probe generator、response matrix、coreset、capsule builder |
| 4 | 跑最小 baseline 对比 | recency / embedding clustering / similarity pruning / merging |
| 5 | 跑小样本 bad case | 检索失败、summary 丢失、时间断裂、视觉证据丢失 |
