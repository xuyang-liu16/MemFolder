# 调研笔记：Agent Memory Compression

> 更新日期：2026-07-06
> 维护：Research Survey（Cursor）
> 本文件是项目级公开调研笔记；可复用方法片段与引用候选见 `paper/refs/extended-survey/` 与 `coordination/research_survey/work_res_research_survey_cursor.md`。

---

## 一屏结论

| 结论 | 对本项目的影响 |
|---|---|
| Agent memory compression 已经不是空白问题 | 不能泛泛 claim「首次压缩 Agent memory」 |
| StreamMeCo 是直接剪枝 baseline（ACL 2026 Findings） | 复用其 M3-Agent graph 接口 + 自报「first memory compression framework for industrial-scale streaming video agent」需作为不能 claim 写入 |
| MemForest 是强相关先导工作（arXiv 2605.23986, 2026） | 注意：现有公开 arXiv 版本讲的是 **MemTree（hierarchical temporal index）+ parallel chunk extraction**，并非 reading notes 里曾提到的「EventTree + MST Merging + AGPR」；下游若需引用具体数字须重新验证 |
| Mem0 / M3-Agent / LoCoMo / MemEye 元数据全部在线可验证 | BibTeX 由 Semantic Scholar + ACL Anthology + arXiv 多源核对，不再凭记忆录入 |
| LoCoMo / MemEye 默认评测都是离线一次性摄入 | 需要自建 lightweight streaming wrapper（参考 Neuromem, arXiv 2602.13967） |
| 下一步机会在 online、temporal budget、多模态细节保留 | 项目应聚焦更具体的问题定义：recall-preserving memory compression |

---

## 1. 领域分层

| 层级 | 代表方向 | 与本项目关系 |
|---|---|---|
| Prompt / context 压缩 | LLMLingua、Selective Context、LLMLingua-2 | 可作为 retrieved memories 的辅助压缩（注意：用在 prompt 阶段而非 memory stage） |
| KV-cache 压缩 | H2O、StreamingLLM、SnapKV、StreamingLLM | 解决推理缓存，不直接管理长期记忆 |
| Agent memory 系统 | Mem0、MemGPT、Zep、MemoryOS、MIRIX、M2A、MMA | 提供长期记忆存取框架 |
| 多模态长期记忆 | M3-Agent、MovieChat、MIRIX、MemEye | 提供多模态 memory 表示和评测背景 |
| Agent memory compression | StreamMeCo、MemForest、SimpleMem、HyMem、R3Mem、ZipRL、ACON | 本项目最直接相关层 |
| Memory evaluation benchmarks | LoCoMo、LongMemEval、MemEye、MemoryAgentBench、RealMem | 评测压缩后 memory 是否仍能 recall evidence |
| Streaming memory testbeds | Neuromem（arXiv 2602.13967, 2026） | 项目级参考资料：interleaved insertion-and-retrieval protocol |

---

## 2. 关键 baseline 元数据（已联网验证）

> 所有元数据已在 2026-07-06 通过 Semantic Scholar / ACL Anthology / arXiv / 官方 GitHub **双源以上**核对。下游如需 BibTeX，请使用对应 Bibkey，不要从记忆录入。

| 工作 | 验证来源 | 元数据（含 Bibkey / arXiv ID） |
|---|---|---|
| StreamMeCo | Semantic Scholar + aclanthology.org/2026.findings-acl.647 + arXiv 2604.09000 + GitHub `Celina-love-sweet/StreamMeCo` | Wang 等，ACL 2026 Findings, pp. 13234–13251, DOI 10.18653/v1/2026.findings-acl.647；Bibkey `wang-etal-2026-streammeco` |
| MemForest | Semantic Scholar + arXiv 2605.23986 + GitHub `Concyclics/MemForest` | Chen 等，arXiv 2605.23986，公开于 2026-05-16；**当前公开版本**聚焦 hierarchical temporal indexing + parallel chunk extraction（写时优化方向），并未实现 reading-notes-core-papers.md 里描述的「EventTree + MST Merging + AGPR」（[CITATION NEEDED]） |
| Mem0 | arXiv 2504.19413 + GitHub `mem0ai/mem0` | Chhikara 等，2025；60k+ stars 工业级 universal memory layer |
| M3-Agent | ICLR 2026 poster + arXiv 2508.09736 + GitHub `bytedance-seed/m3-agent` | Long 等，ICLR 2026, arXiv 2025-08-13；entity-centric 多模态 memory graph；M3-Bench-robot 100 + M3-Bench-web 920 |
| LoCoMo | aclanthology.org/2024.acl-long.747 + GitHub `snap-research/LoCoMo` | Maharana 等，ACL 2024, arXiv 2402.17753；10 个对话、~600 turns、~16K tokens |
| MemEye | arXiv 2605.15128 + GitHub `MinghoKwok/MemEye` | Guo 等，arXiv 2026；371 QA × 8 tasks、221 sessions、848 turns、438 images |
| Neuromem（streaming wrapper 参考） | arXiv 2602.13967, 2026 | Zhang 等；明示 LoCoMo / LongMemEval / MemoryAgentBench 上串行化为 stream + 固定 20% checkpoint 评测 |

---

## 3. StreamMeCo / MemForest / RecallFlow 深度对比表（v2）

> 标 ✅ Fact / ⚡ Claim / 💡 Hypothesis 三级标注，对应口径见 `paper/refs/extended-survey/SKILL.md`。

| 维度 | StreamMeCo ✅ Fact | MemForest（公开版）✅ Fact | RecallFlow（项目目标）💡 Hypothesis |
|---|---|---|---|
| 主要问题 | M3-Agent 多模态 memory graph 增长导致存储与检索开销 | 长上下文 LLM agent 的记忆维护开销（sequential、full-state rewrites） | Agent memory 在长期 streaming 中能否唤起未来证据 |
| 压缩对象 | M3-Agent 整张 memory graph（text + face + voice 节点） | 文本 memory stream + MemTree 索引 | 任意有 retriever 的 memory stream（先 text 起步，多模态后扩） |
| 判定依据 | graph connectivity、edge weight + 时间衰减（TMR） | MemTree 局部 path-level updates + lazy summary | retrieval-response fingerprint（probe queries 下的响应模式） |
| query 作用 | retrieval 阶段：TMR 用 query × time-segment 相似度动态配节点数 | retrieval 阶段：tree-level recall + browse | compression 阶段：probe queries 直接进入 coreset 选择目标 |
| 压缩动作 | pruning-only（EMsampling + EWpruning） | hierarchical tree partitioning（write-efficient，**非剪枝也非 LLM-摘要合并**） | keep / merge / summarize / archive / prune 全套路由 |
| 多模态处理 | 专门压 M3-Agent graph：face、voice、text nodes | 当前仅做文本与 entity tree | capsule 内保留 raw visual / audio pointer |
| 时间处理 | TMR 机制对不同 time segment 用非线性衰减 | MemTree 是 balanced temporal hierarchy，叶子存时间局部证据 | response fingerprint 自然吸收 time-anchored 探针；v0 不手写 |
| 在线更新 | 评测协议未声明 streaming；70% 是一次性后剪（[CITATION NEEDED] 需复核） | 明确设计为 write-efficient，对 incremental update 友好 | v0 默认 offline compression；wrapper 应支持 streaming 触发压缩 |
| 评测 benchmark | M3-Bench-robot、M3-Bench-web、Video-MME-Long | LoCoMo、LongMemEval-S | LoCoMo（text）；MemEye（multimodal） |
| 核心风险 ⚡ | 与 MemForest 对比下保留率并非最优（见下） | 评估覆盖 LoCoMo 是否同样支持 M3-Agent 未知（[CITATION NEEDED]） | probe 设计 + response 近似需要验证；不能保证超过 MemForest / StreamMeCo |

⚡ **Claim**：根据 reading-notes-core-papers.md §8.2 中 `StreamMeCo 50% 压缩在 M3-Agent M3-Bench-robot / web 仅保留 96.2% 平均性能（≈ Random Merging 96.4%）` 的描述，**StreamMeCo 即使专门为 M3-Agent 设计，在合并式压缩上仍弱于 MemForest (99.7%)**。该数字需在论文 §6.1 / Table 2 复核后才能正式引用。[CITATION NEEDED]

---

## 4. 当前不能直接写的 claim（项目级红线）

| Claim | 原因 / 证据 |
|---|---|
| 首个 Agent memory compression | StreamMeCo、MemForest、SimpleMem、HyMem、R3Mem 等已覆盖关键空间 |
| 首个 M3-Agent memory graph compression | StreamMeCo（ACL 2026 Findings）已是直接近邻，且 self-claim 为「first memory compression framework specifically designed for industrial-scale streaming video agent」（必须区分「我们」self-claim 与「StreamMeCo」self-claim） |
| 首个 event-level memory compression | MemForest 已有 hierarchical tree partitioning / local path update 设计 |
| MemForest = EventTree + MST Merging + AGPR | 当前 arXiv 2605.23986 公开版本**没有**这三件套；reading-notes-core-papers.md §8 中描述的方法细节应重新核对，不能直接 cite |
| 固定比例压缩不足即可证明我们优越 | 需要和 StreamMeCo / MemForest / recency / random / embedding clustering 全套对照 |
| query-conditioned compression 一定安全 | probe 不能用未来测试问题，必须严格避免 oracle leakage |
| 一定优于 StreamMeCo / MemForest | 需直接跑 baseline 或 strong proxy 实验支撑；不能凭宣称 |
| RecallFlow v0 = 完整多模态压缩 | v0 仅从 text node / caption node 起；多模态等 raw pointer + MemEye 验证 |

---

## 5. 推荐阅读顺序（next research agenda）

| # | 内容 | 目标 | 状态 |
|---:|---|---|---|
| 1 | StreamMeCo paper + repo（M3-Agent memory graph 接口） | 接入 baseline；理解 graph connectivity + TMR | ✅ 元数据已验证 |
| 2 | MemForest paper + repo（hierarchical temporal indexing） | 接入 baseline；对比 write-efficient vs recall-preserving 视角 | ✅ 元数据已验证；具体数字 [CITATION NEEDED] |
| 3 | LoCoMo paper + repo（QA / event summarization / multimodal dialog） | text 长期记忆评测 | ✅ 元数据已验证；streaming wrapper 需自建 |
| 4 | MemEye paper + repo（视觉证据粒度 × 记忆推理深度） | 多模态评测；visual evidence 保留实验 | ✅ 元数据已验证；streaming wrapper 需自建 |
| 5 | Neuromem（arXiv 2602.13967） | 借鉴 interleaved insertion-and-retrieval protocol | ⏳ 精读中 |
| 6 | MixKV / VidCom2 / V-CAST | 长短期组合与动态预算思想的可迁移信号 | ⏳ 待精读 |
| 7 | Mem0 graph memory variant（arXiv 2504.19413） | 复核 Mem0-graph 与 text-stream Mem0 的接口差异 | ⏳ 待精读 |
| 8 | MIRIX / M2A / MMA（MemEye baseline） | 多模态压缩对照 | ⏳ 待精读 |

---

## 6. 风险与下一步（与 Main Control 同步）

- ✅ 已消除：所有主要 baseline BibTeX 元数据已联网验证。
- ⏳ 待 Coding Agent：MemForest / StreamMeCo 接入 RecallFlow 评测需要 refactor 现有 `build_history()` 接口，建议用 incremental API 抽象。
- ⏳ 待 Experiment Agent：streaming wrapper 实现细节见 `docs/online_evaluation_protocols.md`（已落地）。
- ⏳ 待 Paper Writing Agent：related work 节写作以本表 §3 为骨架。
- 💡 备查：如果 main_control 或 coding 看到本表 §3「MemForest」与 reading-notes-core-papers.md §8 矛盾，**请以本表为准**（旧笔记数字仅作背景参考）。
