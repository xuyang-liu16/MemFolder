# RecallFlow 方法说明

> 更新时间：2026-07-05  
> 状态：方法设计 v0，供合作者对接实现和小规模实验。

## ✅ 一屏结论


| 问题                             | RecallFlow 的回答                                                                                         |
| ------------------------------ | ------------------------------------------------------------------------------------------------------ |
| 我们还在做 node 压缩吗？                | 工程上先从 memory node 开始，但论文目标不是“删 node”，而是保持压缩后的可唤起证据覆盖。                                                  |
| 和 StreamMeCo / MemForest 最大区别？ | 它们主要按结构冗余或事件相似性压缩；RecallFlow 直接压缩 memory system 的检索响应行为。                                               |
| 第一版怎么做？                        | 在 LoCoMo + Mem0 上，把每个 memory node 表示成 retrieval-response fingerprint，再做 coverage coreset 和 capsule 压缩。 |
| 为什么像 MixKV 精神？                 | 不手写多个 lambda 分数，而是根据 memory 内部冗余结构自适应决定 keep / merge / prune。                                          |


一句话：

> **RecallFlow 是一个 plug-and-play 的 recall-preserving compression layer：它在固定预算下尽量保持压缩前后的检索响应分布，从而让现有记忆系统记得更多、更准。**

工程实现细节、response 分数计算公式和代码骨架见 [recallflow_implementation_guide.md](./recallflow_implementation_guide.md)。

## 1. 核心动机

长期 Agent 的问题不只是 memory 越来越大，而是：

> 压缩之后，未来问题还能不能把关键证据找回来？

现有方法常把压缩写成“减少节点数量”：


| 旧视角             | 局限                            |
| --------------- | ----------------------------- |
| 删掉冗余 node       | 可能删掉未来问题唯一需要的证据               |
| 合并相似 event      | 可能把关键转折、时间顺序、视觉细节抹平           |
| 固定比例压缩          | 不同时间段、任务、模态的信息密度不同            |
| 只看 embedding 相似 | embedding 像不代表对 query 的检索作用相同 |


RecallFlow 把问题改写为：

> **在固定 memory budget 下，保持原始 memory 对未来 query 的 evidence coverage。**

这里的 recall coverage 不是狭义 Recall@K，而是“该被唤起的证据还能不能被唤起”。

## 2. 问题定义

给定一个随时间增长的 memory stream：

```text
M = {m_1, m_2, ..., m_n}
```

每个 memory item 至少包含：


| 字段            | 说明                                     |
| ------------- | -------------------------------------- |
| `node_id`     | memory node / item id                  |
| `text`        | 对话、事件、caption 或 summary                |
| `timestamp`   | turn、session、clip 或 event 顺序           |
| `embedding`   | 文本或多模态 embedding                       |
| `metadata`    | entity、speaker、modality、source pointer |
| `raw_pointer` | 可选，指向原始 turn、图片、视频帧或 memory graph node |


目标是在预算 `B` 下输出压缩记忆 `C`：

```text
|C| <= B
```

并尽量保持原 memory 和压缩 memory 面对 probe queries 时的检索响应一致：

```text
RetrievalResponse(Q, M) ≈ RetrievalResponse(Q, C)
```

这比“节点重要性打分”更接近最终 QA：QA 成败取决于关键 evidence 是否能被检索到。

## 3. RecallFlow v0 实现策略

### 3.1 统一 memory node schema

第一版先服务 LoCoMo / Mem0，之后再扩展到 MemEye / M3-Agent。

```json
{
  "node_id": "dialog_001_turn_023",
  "text": "Mark said he likes rice for lunch.",
  "timestamp": 23,
  "embedding": "...",
  "entities": ["Mark", "rice"],
  "modality": "text",
  "source": {
    "dataset": "LoCoMo",
    "dialog_id": "dialog_001",
    "turn_id": 23
  },
  "raw_pointer": "optional original evidence pointer"
}
```

多模态阶段可增加：


| 字段                 | 说明                        |
| ------------------ | ------------------------- |
| `visual_embedding` | 图像 / 视频帧 embedding        |
| `object_tags`      | 物体、区域、OCR、状态              |
| `audio_tags`       | speaker、voice、ASR         |
| `graph_links`      | M3-Agent text-media edges |
| `frame_pointer`    | 原始图像 / 视频帧指针              |


### 3.2 构造 probe queries

Probe queries 用来模拟未来可能如何唤起记忆。重要原则：

> **不要使用测试集问题作为压缩时的 probe，避免 oracle leakage。**

安全来源：


| Probe 类型                 | 例子                           | 目的            |
| ------------------------ | ---------------------------- | ------------- |
| Entity probe             | “关于 Mark 我们知道什么？”            | 保人物、物体、地点相关证据 |
| Temporal probe           | “会议之后发生了什么？”                 | 保时间顺序和前后关系    |
| Event probe              | “谁改变了计划？”                    | 保事件转折         |
| Preference / state probe | “Mark 喜欢什么？”、“任务状态如何变化？”     | 保长期偏好和状态记忆    |
| Task probe               | 当前 agent goal / session type | 让任务分布进入压缩策略   |
| Multimodal probe         | “桌上有什么物体？”、“谁出现在画面里？”        | 保视觉和音频证据      |


第一版可以从 metadata 自动生成 probe：

```text
entity -> What do we know about {entity}?
time window -> What happened around {time/window}?
event phrase -> What happened when {event}?
speaker -> What did {speaker} say or do?
```

### 3.3 计算 retrieval-response fingerprint

给定 probe query 集合 `Q` 和现有 memory retriever `R`：

```text
A[q, i] = R(q, m_i)
```

实际 v0 建议先计算原始相似度 `S`，再做 query-wise softmax：

```text
S[q, i] = cosine(embed(q), embed(m_i))
A[q, :] = softmax(S[q, :] / tau)
```

`A` 是 response matrix。每个 memory node 的列向量：

```text
fingerprint(m_i) = A[:, i]
```

表示这个 node 在一组未来可能 query 下的响应模式。

同时计算 response mass：

```text
mass_i = sum_q A[q, i]
```

用于区分“和代表点很像但仍经常被 probe 命中”的 node，以及“几乎不会被 probe 命中”的 node。

直觉：


| 情况                                            | RecallFlow 动作                      |
| --------------------------------------------- | ---------------------------------- |
| 两个 node embedding 像，但 response fingerprint 不像 | 不直接合并，避免丢不同证据                      |
| 两个 node 文本不同，但 response fingerprint 很像        | 可以合并成 capsule                      |
| 某个 node 只对少数 probe 强响应                        | 保留为 exception，防止 rare evidence 被压掉 |
| 某个 node 对 probe 几乎无响应                         | prune 或 archive                    |


### 3.4 Coverage coreset 选择

在 response fingerprint 空间里选择代表 node，而不是直接在 text embedding 空间里聚类。

最小实现可以用：


| 方法                       | 用途                          |
| ------------------------ | --------------------------- |
| k-medoids                | 每簇选一个真实 memory node 作为代表    |
| facility-location greedy | 最大化 probe-response coverage |
| online k-center          | 更适合 streaming 增量版本          |


第一版建议：

```text
1. 计算 response fingerprint
2. 用 k-medoids / greedy facility-location 选 B 个代表 node
3. 将其他 node 分配给最接近的代表 node
```

### 3.5 Capsule 压缩与 residual routing

每个代表 node 形成一个 memory capsule。

簇内其他 node 根据 response residual 决定动作：


| 条件                  | 动作                               |
| ------------------- | -------------------------------- |
| residual 小          | merge / summarize 到 capsule      |
| residual 大且 mass 高  | keep as exception                |
| response mass 低     | archive / prune                  |
| 多模态 raw evidence 重要 | 保留 raw pointer，不把视觉证据只写进 summary |


v0 中 residual 可定义为 node 到代表 node 的 response fingerprint cosine distance：

```text
residual_i = 1 - cosine(f_i, f_representative)
```

不要先手写绝对阈值，建议在每个 cluster 内用分位数决定 merge / exception。

输出的 capsule 至少包含：

```json
{
  "capsule_id": "cap_001",
  "representative_node": "...",
  "summary": "...",
  "member_node_ids": ["..."],
  "exception_node_ids": ["..."],
  "raw_pointers": ["..."],
  "timestamp_span": [12, 38],
  "entities": ["Mark", "Alice"]
}
```

检索时如果命中 capsule，可以：

1. 直接使用 capsule summary；
2. 展开 representative node；
3. 必要时追溯 raw pointer 获取原始证据。

## 4. 与 StreamMeCo / MemForest 的区别


| 维度       | StreamMeCo                                         | MemForest                                       | RecallFlow                                 |
| -------- | -------------------------------------------------- | ----------------------------------------------- | ------------------------------------------ |
| 主要问题     | M3-Agent memory graph 太大                           | 相似事件和历史记忆可合并                                    | 压缩后还能否唤起关键证据                               |
| 压缩对象     | M3-Agent text nodes                                | Mem0 / M3-Agent memory events                   | 任意有 retriever 的 memory nodes / capsules    |
| 判断依据     | graph connectivity、edge weight、embedding diversity | semantic-temporal partition、progressive merging | retrieval-response fingerprint             |
| query 作用 | 主要在 retrieval 阶段                                   | AGPR retrieval 阶段                               | compression 阶段就参与 coverage objective       |
| 压缩动作     | 主要 pruning                                         | 主要 merging                                      | keep / merge / summarize / archive / prune |
| 多模态证据    | 主要压 text，不压 media nodes                            | 主要压 text/event memory                           | capsule 可保留 raw visual/audio pointer       |
| 核心风险     | fixed heuristic                                    | event merging 可能抹平细节                            | probe 设计和 response 近似需要验证                  |


一句话：

> **StreamMeCo 找结构上不冗余的 node，MemForest 合并语义-时间相似的 event，RecallFlow 保持压缩前后的可唤起证据覆盖。**

## 5. RecallFlow 的优势假设


| 优势                   | 为什么可能成立                                       | 需要实验验证                                          |
| -------------------- | --------------------------------------------- | ----------------------------------------------- |
| 更贴近 QA               | QA 依赖检索到 evidence，而不是 node 自身分数               | evidence recall@k、QA accuracy                   |
| 少手调超参                | 主目标是 response coverage，不是多个 lambda 加权         | ablation：response fingerprint vs weighted score |
| pruning / merging 统一 | residual 小则 merge，大则 keep                     | prune-only / merge-only / full 对比               |
| plug-and-play        | 只要求底层 memory system 有 retriever               | Mem0、M3-Agent、MemForest wrapper                 |
| 支持多模态扩展              | capsule 可保留 raw frame / image / audio pointer | MemEye visual evidence case                     |


## 6. 最小实验计划

### 6.1 LoCoMo + Mem0 v0


| 项目  | 设置                                                                              |
| --- | ------------------------------------------------------------------------------- |
| 数据  | LoCoMo 小样本，先 20-50 个 dialogue                                                   |
| 底座  | Mem0 或统一 memory node store                                                      |
| 预算  | 25%、50%、75% retained memory budget                                              |
| 方法  | RecallFlow v0 response-space coreset + capsule                                  |
| 指标  | QA accuracy、evidence recall@k、memory size、compression latency、retrieval latency |


### 6.2 Baseline


| Baseline               | 作用                                          |
| ---------------------- | ------------------------------------------- |
| no compression         | 上界                                          |
| random                 | sanity check                                |
| recency / FIFO         | 检查是否只是近因偏置                                  |
| embedding clustering   | 检查 response fingerprint 是否比 embedding 相似更有效 |
| similarity pruning     | StreamMeCo-like proxy                       |
| similarity merging     | MemForest-like proxy                        |
| StreamMeCo / MemForest | 后续必须接入的强 baseline                           |


### 6.3 必做 ablation


| Ablation                                      | 目的                     |
| --------------------------------------------- | ---------------------- |
| response fingerprint vs embedding fingerprint | 证明压缩检索行为比压缩语义相似度更有效    |
| no capsule, prune-only                        | 证明 merge / capsule 有价值 |
| merge-only, no exception                      | 检查是否抹平 rare evidence   |
| no entity probes                              | 看人物、偏好、地点问题是否下降        |
| no temporal probes                            | 看 temporal QA 是否下降     |
| no raw pointer                                | 看多模态细节是否被 summary 抹掉   |


## 7. 实现 TODO


| 优先级 | 任务                              | 产出                                                               |
| --- | ------------------------------- | ---------------------------------------------------------------- |
| P0  | 统一 memory node schema           | JSONL schema + loader                                            |
| P0  | LoCoMo / Mem0 memory extraction | 小样本 memory stream                                                |
| P0  | probe query generator           | entity / temporal / event probes                                 |
| P0  | response matrix builder         | `A[q, i]` 计算脚本                                                   |
| P0  | response-space coreset          | k-medoids / greedy facility-location                             |
| P0  | capsule builder                 | representative、summary、raw pointers                              |
| P0  | implementation guide 对齐         | 按 `recallflow_implementation_guide.md` 写 v0 模块                   |
| P1  | baseline wrappers               | random、recency、embedding clustering、similarity pruning / merging |
| P1  | budget-accuracy curve           | 第一张核心图                                                           |
| P1  | bad case 表                      | 解释 RecallFlow 保住了哪些 evidence                                     |
| P2  | MemEye / M3-Agent wrapper       | 多模态证据保留实验                                                        |


## 8. 当前不能 claim


| Claim                             | 原因                                                              |
| --------------------------------- | --------------------------------------------------------------- |
| 首个 Agent memory compression       | StreamMeCo / MemForest 已覆盖关键空间                                  |
| 首个 M3-Agent memory graph 压缩       | StreamMeCo 已是直接近邻                                               |
| 完整多模态 memory compression          | v0 先从 text node / caption node 开始，多模态需要 raw pointer 和 MemEye 验证 |
| query-conditioned compression 已解决 | probe query 不是未来测试问题，需要严格避免 leakage                             |
| 一定优于 MemForest / StreamMeCo       | 必须跑直接 baseline 或至少 strong proxy                                 |


## 9. 推荐 paper-facing 表述

> 现有 Agent memory compression 方法主要压缩记忆内容本身，例如删除冗余节点或合并相似事件。RecallFlow 将问题重新定义为 recall-preserving compression：在固定预算下保持压缩前后的检索响应分布，使现有记忆系统仍能唤起未来任务所需证据。

英文草稿：

> RecallFlow formulates agent memory compression as recall-coverage preservation rather than node reduction. It compresses the retriever's response behavior under a fixed budget, adaptively routing memory units to keep, merge, summarize, archive, or prune.

