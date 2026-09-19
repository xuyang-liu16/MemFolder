# 🧠 Memory Compression — RecallFlow

> **目标会议**：ICLR 2027 | **核心方法**：RecallFlow
> **协作环境**：Cursor + Claude Code + Codex（每个 role 可由任意一个 agent tool 担任）

> [!IMPORTANT]
> **LoCoMo sample0-9 full matrix results are available (updated 2026-07-16).**  
> Official comparison scope filters out category 5. `sample0`, `sample1`, and `sample2` use the 2026-07-14 full-grid versions by experiment-control decision; `sample3` to `sample9` use the completed relay/no-thinking runs.  
> Main artifact: [`sample0-9 weighted summary`](./results/locomo_sample0_to_9_weighted_mixed_20260716.md).

## 🔥 Latest LoCoMo sample0-9 Results

Total official `n=1540`, weighted by each sample's non-category-5 QA count.

| Method | total n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|
| Full Context | 1540 | 0.7208 | 0.5161 | 0.4323 |
| MemForest keep70 | 1540 | 0.7052 | 0.5008 | 0.4233 |
| MemForest keep50 | 1540 | 0.7065 | 0.4956 | 0.4184 |
| MemForest keep30 | 1540 | 0.6916 | 0.4761 | 0.4009 |
| RecallFlow-NC keep70 | 1540 | 0.7110 | 0.5011 | 0.4242 |
| RecallFlow-NC keep50 | 1540 | 0.7136 | 0.4961 | 0.4169 |
| RecallFlow-NC keep30 | 1540 | 0.6831 | 0.4849 | 0.4079 |

**Current read:** Full Context remains the upper bound. RecallFlow-NC keep50 has the best compressed weighted LLM Acc (`0.7136`), ahead of MemForest keep50 (`0.7065`) and MemForest keep70 (`0.7052`), while MemForest keep70 is still slightly stronger on BLEU1 than RecallFlow-NC keep50.

Per-sample result cards:
[`sample0`](./results/locomo_sample0_fullgrid_2026-07-14.md) ·
[`sample1`](./results/locomo_sample1_fullgrid_2026-07-14.md) ·
[`sample2`](./results/locomo_sample2_fullgrid_2026-07-14.md) ·
[`sample3`](./results/locomo_sample3_relay_nothink_20260715.md) ·
[`sample4`](./results/locomo_sample4_relay_nothink_20260715.md) ·
[`sample5`](./results/locomo_sample5_relay_nothink_20260715.md) ·
[`sample6`](./results/locomo_sample6_relay_nothink_side_20260715.md) ·
[`sample7`](./results/locomo_sample7_relay_nothink_side_20260715.md) ·
[`sample8`](./results/locomo_sample8_relay_nothink_side_20260715.md) ·
[`sample9`](./results/locomo_sample9_relay_nothink_side_20260716.md).

---

## 🎯 一句话

RecallFlow 把 Agent memory compression 从"删掉多少 node"改写成"压缩后还能不能唤起未来问题需要的证据"。面向长期多模态 Agent 记忆，做 **recall-preserving memory compression**。

详细方法定义见 [method_idea.md](./method_idea.md) 与 [recallflow_method.md](./recallflow_method.md)。

---

## 📊 当前状态（更新时间 2026-07-09）

### 最新结果看板

| 结果 | 结论 | 链接 |
|---|---|---|
| RecallFlow-URB random node response snapshot | 随机 15 个 LoCoMo sample0 memory node 显示：URB 10 维响应和 metadata/text 类型有弱到中等对应关系，但单 node top-1 不够尖锐，不宜当硬标签；更适合做 cell 级聚合和 response-loss 预算路由。 | [result card](./results/recallflow_urb_random_node_probe_response_2026-07-09.md) |
| LoCoMo sample0 keep70 baseline | RF-URB prune-only 总体 Acc 低于 MemForest keep70 2.63pp，但 F1/BLEU1 接近；主要损失集中在 cat 3 / cat 4。 | [MemForest card](./results/memforest_sample0_keep70_2026-07-08.md) |


|      | 模块                                                         | 当前状态 |
| ---- | ---------------------------------------------------------- | ---- |
| 项目主线 | 已收敛到 Memory Compression → RecallFlow                       | 转向 cell-level response-preserving routing |
| 调研   | 已有 v1 research_notes + 扩展调研在 `paper/refs/extended-survey/` | 继续对齐 MemForest / StreamMeCo |
| 方法文档 | RecallFlow v0 方法说明与实现指南已就位                                 | URB + routed compression 正在细化 |
| 代码实现 | v0 compression / baselines / adapter 骨架已出现                         | URB runner 仍需回流到 `code/` |
| 实验   | LoCoMo sample0 Mem0 / MemForest / RF-URB prune-only 已有初步结果        | 下一步做 cell profile 与 response-loss 预算路由 |
| 论文   | 未开始（`paper/` 骨架已建）                                         | 当前结果提供方法动机素材 |


更新请见 [PROJECT_STATUS.md](./PROJECT_STATUS.md)。

---

## 📁 目录速查

```
memory-compression-v2/
├── 📘 AGENTS.md                       ← Agent 入口（英文，给 AI 看）
├── 📗 README.md                       ← 人类入口（本文档）
│
├── 🤖 .cursor/
│   ├── skills/                        ← 5 个 role 的共享 SKILL.md（提交）
│   └── rules/                         ← 5 个 role 的共享 rule（提交）
│
├── 🤝 coordination/                   ← 本地多 agent 工作日志（不提交）
│   ├── README.md
│   ├── control/                       ← Main Control Agent
│   ├── research_survey/               ← Research Survey Agent
│   ├── coding/                        ← Coding Agent
│   ├── paper_writing/                 ← Paper Writing Agent
│   └── experiments/                   ← Experiment / Results Agent
│
├── 📑 docs/                           ← 共享方法与实验文档
│   ├── README.md
│   ├── research_notes.md
│   ├── method_idea.md
│   ├── recallflow_method.md
│   ├── recallflow_implementation_guide.md
│   └── experiment_plan.md
│
├── 💻 code/                           ← RecallFlow v0 实现（待搭建）
│   ├── src/compression/
│   ├── evaluation/
│   ├── baselines/
│   └── configs/
│
├── 🧪 results/                        ← 小规模可共享结果（待跑）
├── 🔁 src/                            ← 本地历史压缩代码（不提交）
├── 📦 paper/refs/                     ← PDF 文献 + BibTeX + 笔记（不提交）
├── 📦 repo/                           ← 数据集 / benchmark（不提交）
└── 🔗 external/                       ← 大数据集 / 模型权重 symlink（不提交）
```

---

## 🔬 方法核心对比


| 对比                   | 近邻工作                                                                       | RecallFlow                                |
| -------------------- | -------------------------------------------------------------------------- | ----------------------------------------- |
| StreamMeCo           | 按 graph connectivity、edge weight、embedding diversity 剪 M3-Agent text nodes | 压缩检索响应行为，不只是结构冗余                          |
| MemForest            | EventTree partition + progressive merging + AGPR                           | response 相似才合并，保留 exception / raw pointer |
| Recency / FIFO       | 保最近的 memory                                                                | 保未来 probe 能唤起的 evidence                   |
| embedding clustering | 在 text embedding 空间聚类                                                      | 在 response fingerprint 空间做 coreset        |


一句话：

> **RecallFlow 把"压缩多少 node"改写成"压缩后检索响应还能不能保留"。**

---

## 🚀 下一步行动

- 深读 StreamMeCo / MemForest，写差异表与不能 claim 清单（Research Survey）
- 确认 LoCoMo / MemEye 是否支持 online update（Research Survey）
- 实现 RecallFlow v0：schema → probes → response matrix → coreset → capsule（Coding）
- 跑 50% budget，对比 recency、embedding k-center（Coding + Experiment）
- 写 paper spine 与不能 claim 清单（Paper Writing）

详细任务分配见 [collaborator_codex_workflow.md](./collaborator_codex_workflow.md)。

---

## 📚 关键文档


| 文档                                                                                   | 用途                   |
| ------------------------------------------------------------------------------------ | -------------------- |
| [PROJECT_STATUS.md](./PROJECT_STATUS.md)                                             | 项目当前状态看板             |
| [docs/method_idea.md](./docs/method_idea.md)                                         | RecallFlow 一句话与差异表   |
| [docs/recallflow_method.md](./docs/recallflow_method.md)                             | 方法细节与 ablation       |
| [docs/recallflow_implementation_guide.md](./docs/recallflow_implementation_guide.md) | v0 实现公式与代码骨架         |
| [docs/experiment_plan.md](./docs/experiment_plan.md)                                 | LoCoMo / MemEye 评测方案 |
| [docs/research_notes.md](./docs/research_notes.md)                                   | 调研笔记：领域定位、近邻工作       |
| [collaborator_codex_workflow.md](./collaborator_codex_workflow.md)                   | 多 agent 工作流搭建指南（强制）  |


---

> 💬 **合作者请看这里**：
>
> - 想了解项目 → 看本文档 + `docs/`
> - 想看 AI 工作的痕迹 → 看本地 `coordination/`（不提交）
> - 想跑代码 → `code/` 还在搭建中，先看 `docs/recallflow_implementation_guide.md`
> - 想了解多 agent 协作约定 → 看 `AGENTS.md` + `coordination/README.md`
