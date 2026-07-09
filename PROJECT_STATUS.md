# 项目当前进展看板

> 更新时间：2026-07-05  
> 用途：给合作者快速判断项目现在做什么、缺什么、下一步先做什么。

## 一屏结论

| 项目项 | 当前结论 |
|---|---|
| 主路线 | Agent Memory Compression |
| 目标场景 | 流式多模态 Agent 的长期记忆管理 |
| 方法焦点 | RecallFlow：保持压缩前后的可唤起证据覆盖 |
| 核心 baseline | StreamMeCo、MemForest、Mem0、M3-Agent |
| 评测基准 | 纯文本 LoCoMo，多模态 MemEye |
| 当前阶段 | 文档和方向已收敛，代码与实验尚未开始 |

## 当前方法假设：RecallFlow

> 📌 **Research Survey 红线更新（2026-07-06, Cursor）**：下列 assume 中「MemForest = EventTree + MST Merging + AGPR」「LoCoMo 支持 online 评测」两点与 `docs/research_notes.md` 2026-07-06 版本不一致；red-line 列表见 `docs/research_notes.md` §4 与 `docs/online_evaluation_protocols.md`。若 Main Control / Paper Writing 引用本节，请同步检查最新红线。

| 组件 | 含义 | 需要验证 |
|---|---|---|
| Recall coverage | 压缩后仍能检索到未来问题需要的证据 | evidence recall@k 是否优于 embedding / recency baseline |
| Response fingerprint | 每个 node 用 probe queries 下的检索响应表示 | response space 是否比 embedding space 更适合压缩 |
| Memory capsule | response 相似的 nodes 合并，保留 representative、summary、raw pointer | capsule 是否比 prune-only 更少丢证据 |
| Exception keep | residual 大的节点单独保留 | rare evidence 是否能保住 |

核心直觉：不要只问“哪些 node 重要”，而要问“压缩后 memory system 面对未来 probe queries 时，还能不能产生接近原始 memory 的检索响应”。时间连续性、全局独特性和任务相关性都应通过 probe / response matrix 进入压缩目标，而不是手写多个 lambda 分数。

## 当前 baseline 位置

| Baseline | 为什么重要 | 当前状态 |
|---|---|---|
| StreamMeCo | 直接的 M3-Agent memory graph 压缩近邻工作 | 待深读与复现 |
| MemForest | 强相关先导工作，覆盖 EventTree / progressive merging / AGPR | 待深读与复现 |
| Mem0 | 纯文本 / agentic memory 基础系统 | 待选定实验入口 |
| M3-Agent | 多模态长期记忆图谱底座 | 待确认与 MemEye / StreamMeCo 的接口 |
| FIFO / recency / random | 简单 sanity baseline | 待实现 |

## 近期 TODO

| 优先级 | 任务 | 产出 | 状态 |
|---:|---|---|---|
| P0 | 深读 StreamMeCo / MemForest | 差异表、复现入口、不能 claim 清单 | ✅ 完成（`docs/research_notes.md` §3） |
| P0 | 调查 LoCoMo / MemEye online update 支持程度 | 是否需要自建 streaming wrapper | ✅ 完成（`docs/online_evaluation_protocols.md`）—结论：**需要自建 wrapper，参考 Neuromem** |
| P0 | 实现 RecallFlow v0 | probe generator、response matrix、coreset、capsule builder | ⏳ Coding 未启动 |
| P0 | 跑 RecallFlow 最小实验 | LoCoMo / Mem0 小样本 budget-accuracy 曲线 | ⏳ Experiment 未启动 |
| P1 | 固定 Qwen 系列评测模型 | model id、调用方式、成本估计 | ⏳ |
| P1 | 跑 LoCoMo / MemEye smoke test | 第一版评测可行性结果 | ⏳ |

## 风险和约束

| 风险 | 等级 | 处理方式 |
|---|---:|---|
| Novelty 与 MemForest / StreamMeCo 重叠 | 高 | 先深读并写清楚差异，避免“首个 memory compression”类 claim |
| benchmark 未必支持 online update | 高 | 先调查协议，必要时设计 online wrapper |
| probe query 设计可能带来 leakage | 高 | 不使用测试问题，只用 memory metadata、历史任务分布和当前 agent goal |
| 多模态细节可能被 caption 化丢失 | 中 | capsule 保留 raw image / frame / audio pointer，并在 MemEye 上做 visual evidence bad case 分析 |
| 代码和评测尚未启动 | 中 | 先搭最小 smoke test，不急于大规模实验 |

## 下次同步前目标

1. 完成 StreamMeCo / MemForest 的方法对照表。
2. 给出 LoCoMo / MemEye 是否支持 online evaluation 的明确结论。
3. 跑出一版 response fingerprint vs embedding clustering 的对比。
4. 形成 RecallFlow v0 的最小实现和 budget-accuracy 曲线。
