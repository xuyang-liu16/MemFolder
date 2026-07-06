# 🧠 Memory Compression — RecallFlow

> **目标会议**：ICLR 2027 &nbsp;|&nbsp; **核心方法**：RecallFlow  
> **协作环境**：Cursor + Claude Code + Codex（每个 role 可由任意一个 agent tool 担任）

---

## 🎯 一句话

RecallFlow 把 Agent memory compression 从"删掉多少 node"改写成"压缩后还能不能唤起未来问题需要的证据"。面向长期多模态 Agent 记忆，做 **recall-preserving memory compression**。

详细方法定义见 [method_idea.md](./method_idea.md) 与 [recallflow_method.md](./recallflow_method.md)。

---

## 📊 当前状态（更新时间 2026-07-05）

|| 模块 | 当前状态 |
|---|---|---|
| 项目主线 | 已收敛到 Memory Compression → RecallFlow |
| 调研 | 已有 v1 research_notes + 扩展调研在 `paper/refs/extended-survey/` |
| 方法文档 | RecallFlow v0 方法说明与实现指南已就位 |
| 代码实现 | 未开始（`code/`、`src/` 骨架已建） |
| 实验 | 未开始（`results/`、`experiments/` 骨架已建） |
| 论文 | 未开始（`paper/` 骨架已建） |

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

| 对比 | 近邻工作 | RecallFlow |
|---|---|---|
| StreamMeCo | 按 graph connectivity、edge weight、embedding diversity 剪 M3-Agent text nodes | 压缩检索响应行为，不只是结构冗余 |
| MemForest | EventTree partition + progressive merging + AGPR | response 相似才合并，保留 exception / raw pointer |
| Recency / FIFO | 保最近的 memory | 保未来 probe 能唤起的 evidence |
| embedding clustering | 在 text embedding 空间聚类 | 在 response fingerprint 空间做 coreset |

一句话：

> **RecallFlow 把"压缩多少 node"改写成"压缩后检索响应还能不能保留"。**

---

## 🚀 下一步行动

- [ ] 深读 StreamMeCo / MemForest，写差异表与不能 claim 清单（Research Survey）
- [ ] 确认 LoCoMo / MemEye 是否支持 online update（Research Survey）
- [ ] 实现 RecallFlow v0：schema → probes → response matrix → coreset → capsule（Coding）
- [ ] 跑 50% budget，对比 recency、embedding k-center（Coding + Experiment）
- [ ] 写 paper spine 与不能 claim 清单（Paper Writing）

详细任务分配见 [collaborator_codex_workflow.md](./collaborator_codex_workflow.md)。

---

## 📚 关键文档

| 文档 | 用途 |
|---|---|
| [PROJECT_STATUS.md](./PROJECT_STATUS.md) | 项目当前状态看板 |
| [docs/method_idea.md](./docs/method_idea.md) | RecallFlow 一句话与差异表 |
| [docs/recallflow_method.md](./docs/recallflow_method.md) | 方法细节与 ablation |
| [docs/recallflow_implementation_guide.md](./docs/recallflow_implementation_guide.md) | v0 实现公式与代码骨架 |
| [docs/experiment_plan.md](./docs/experiment_plan.md) | LoCoMo / MemEye 评测方案 |
| [docs/research_notes.md](./docs/research_notes.md) | 调研笔记：领域定位、近邻工作 |
| [collaborator_codex_workflow.md](./collaborator_codex_workflow.md) | 多 agent 工作流搭建指南（强制） |

---

> 💬 **合作者请看这里**：
> - 想了解项目 → 看本文档 + `docs/`
> - 想看 AI 工作的痕迹 → 看本地 `coordination/`（不提交）
> - 想跑代码 → `code/` 还在搭建中，先看 `docs/recallflow_implementation_guide.md`
> - 想了解多 agent 协作约定 → 看 `AGENTS.md` + `coordination/README.md`