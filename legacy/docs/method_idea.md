# 方法想法：RecallFlow

> 更新时间：2026-07-05  
> 详细设计见 [recallflow_method.md](./recallflow_method.md)。

## ✅ 一句话

**RecallFlow 把 Agent memory compression 从“删掉多少 node”改写成“压缩后还能不能唤起未来问题需要的证据”。**

工程上，第一版仍从 memory node 压缩开始；论文上，目标是 **recall-preserving memory compression**。

## 核心动机

现有记忆压缩方法容易关注 memory size：

| 传统问题 | RecallFlow 问的问题 |
|---|---|
| 哪些 node 冗余？ | 哪些 evidence 未来仍需要被检索到？ |
| 哪些 event 可以合并？ | 合并后会不会抹掉关键转折和细节？ |
| 怎样减少检索节点数？ | 压缩后 retriever 的响应分布是否仍接近原始 memory？ |

最重要的观点：

> 长期 Agent 不只是需要更小的记忆，而是需要在预算受限时仍然“想得起来”的记忆。

## 方法概览

| 阶段 | 说明 |
|---|---|
| 1. 统一 memory node | `node_id / text / timestamp / embedding / metadata / raw_pointer` |
| 2. 构造 probe queries | entity、temporal、event、task、multimodal probes；不能使用测试问题 |
| 3. 计算 response matrix | `A[q, i] = retriever_score(q, memory_i)` |
| 4. 生成 response fingerprint | 每个 node 用 `A[:, i]` 表示其检索响应模式 |
| 5. 选择 coverage coreset | 在 response space 选代表 node，而不是只按 embedding 聚类 |
| 6. 构建 memory capsule | residual 小的 merge，大的 keep as exception，低响应的 archive / prune |

## 与近邻工作的差异

| 对照 | 近邻工作做什么 | RecallFlow 的差异 |
|---|---|---|
| StreamMeCo | 按 graph connectivity、edge weight、embedding diversity 剪 M3-Agent text nodes | 压缩检索响应行为，不只是找结构上不冗余的 node |
| MemForest | EventTree partition + progressive merging + AGPR | response 相似才合并，并保留 exception / raw pointer |
| temporal budget 草案 | 手写 global uniqueness、local variation、continuity 等信号 | 用 retrieval-response fingerprint 自动吸收这些信号 |
| recency / FIFO | 保最近的 memory | 保未来 probe 能唤起的 evidence，不等同于最近 |

## 第一版最小实验

| 优先级 | 任务 | 产出 |
|---:|---|---|
| P0 | LoCoMo / Mem0 memory extraction | 统一 memory stream |
| P0 | Probe generator | entity / temporal / event probes |
| P0 | Response matrix builder | `A[q, i]` |
| P0 | Response-space coreset | RecallFlow v0 |
| P0 | Capsule builder | representative + summary + raw pointers |
| P1 | Baseline 对照 | random、recency、embedding clustering、similarity pruning / merging |
| P1 | Budget-accuracy curve | 25% / 50% / 75% budget |

## 当前不能 claim

| Claim | 原因 |
|---|---|
| 首个 Agent memory compression | StreamMeCo / MemForest 已经覆盖 |
| 完整多模态压缩 | v0 先从文本 memory node 开始 |
| 使用 query-conditioned compression 一定安全 | probe 不能用未来测试问题，必须避免 leakage |
| 一定优于 StreamMeCo / MemForest | 需要直接 baseline 或 strong proxy 实验支撑 |
