# 在线评测协议调研：LoCoMo / MemEye 的 streaming 支持

> 调研日期：2026-07-06
> 维护：Research Survey（Cursor）
> 输入依据：`docs/experiment_plan.md` §「Online update 需要确认」清单
> 关联调研：`docs/research_notes.md` §3（baseline 对照）、`paper/refs/extended-survey/`（Neuromem 精读）

---

## 一屏结论

| 问题 | 结论 |
|---|---|
| LoCoMo 原生支持 streaming 评测吗？ | ❌ **不支持**。Repo 现有脚本（`evaluate_rag_gpts.sh` 等）均为一次性喂入全部历史的离线评测；只有 §4 (Event Summarization) 显式使用了 incremental summarization，**但不适用于 QA 任务**。 |
| MemEye 原生支持 streaming 评测吗？ | ❌ **不支持**。`benchmark/methods.py` 中 `build_history()` 是 per-QA 调用的；M2A / MMA 等 agent method 在首次 answer 时一次性 `process_all_sessions(dataset)` 并用 `id(dataset)` 缓存结果，没有内建 incremental / online 接口。 |
| 我们需要自建 streaming wrapper 吗？ | ✅ **需要**。轻量级、按 session 顺序序列化即可，无需修改原始 benchmark。 |
| 有公开 streaming memory testbed 可参考吗？ | ✅ 有：**Neuromem**（arXiv 2602.13967, 2026）。它在 LoCoMo / LongMemEval / MemoryAgentBench 上实现了 interleaved insertion-and-retrieval 协议，并在固定 20% checkpoint 触发评测。**我们的 wrapper 可以复用其数据序列化与 checkpoint 策略**。 |

---

## 1. LoCoMo 的 streaming 协议现状

**证据**：
- 仓库：`https://github.com/snap-research/LoCoMo`（1k stars, 96 forks）
- 主分支入口脚本（README）：
  - `scripts/evaluate_gpts.sh`、`scripts/evaluate_claude.sh`、`scripts/evaluate_gemini.sh`、`scripts/evaluate_hf_llm.sh`：均一次性喂全部对话历史。
  - `scripts/evaluate_rag_gpts.sh`：把对话转成 observations 后一次性检索，top-k retrieval。
  - `scripts/generate_observations.sh`、`scripts/generate_session_summaries.sh`：pre-processing，可与 RAG 联用。
- 论文唯一提到 incremental 的地方：§4 (Event Summarization task)：「incremental summarization i.e., iteratively create a summary of a preceding sessions and then use that summary as a basis to summarize the subsequent sessions」。**只用于 event summarization，且不暴露给第三方方法包装**。

**数据结构能否支持 streaming**：
- ✅ 可以。`locomo10.json` 中每个 session 有 `session_N_date_time` 时间戳；QA annotations 包含 `evidence: [dia_id, ...]`，**说明原始数据保留了 turn-level 时间顺序**。
- ⚠️ caveat：QA 标签的时间粒度是 dia_id 而非绝对时间，需要我们自己维护一个 `dia_id → wall_clock_or_relative_time` 映射。

**结论**：LoCoMo 自身不支持 streaming 评测，但数据结构可以由 wrapper 串行化为流。我们应避免修改官方 eval script，而是在外层包一个 incremental harness（见 §4）。

---

## 2. MemEye 的 streaming 协议现状

**证据**（基于 source code 精读）：
- 仓库：`https://github.com/MinghoKwok/MemEye`（46 stars）
- 入口：`python run_benchmark.py --task-config ... --method-config ...`（per-task、per-method 单次跑完）
- `benchmark/methods.py` 关键设计（节选）：
  ```python
  class M2AAgentMethod(HistoryMethod):
      def _ensure_initialized(self, dataset):
          dataset_id = id(dataset)
          if self._system is not None and self._dataset_key == dataset_id:
              return  # 复用同一 dataset 的 cache
          from .m2a import M2ASystem
          self._system = M2ASystem(self.config)
          sessions = dataset.session_order()
          print(f"[M2A] Building memory from {len(sessions)} session(s)...")
          self._system.process_all_sessions(dataset)  # 一次性构建
  ```
  - `process_all_sessions()` 是 offline 一次性构建。
  - `_dataset_key` 缓存只支持「同一个 dataset 内不同 QA」共享 memory，**不支持跨 checkpoint 的 progressive update**。
- 数据格式（README）：`multi_session_dialogues[*].session_id` 为 `"D1"`、`"D2"` ……；`dialogues[*].round` 为 `"D1:1"`、`"D1:2"` ……，**结构上可以按 round 增量喂入**。

**结论**：MemEye 自身不支持 streaming 评测，但 source 本身允许逐 `round`/`session` 调用 memory build API。Wrapper 必须直接读 `MemEye/benchmark/dataset.py` 拿到 `session_order()`，并自己写 `partial_history_builder(dataset, up_to_round)` 逻辑（见 §4）。

---

## 3. Neuromem：公开 streaming testbed 的直接参考

**元数据**：
- 标题：Neuromem: A Granular Decomposition of the Streaming Lifecycle in External Memory for LLMs
- 作者：Ruicheng Zhang, Xinyi Li, Tianyi Xu, Shuhao Zhang, Liao Xiaofei, Hai Jin
- 链接：arXiv 2602.13967 (2026-05-21 v1)
- 评测数据集：**LoCoMo、LongMemEval (LONGMEMEVAL)、MemoryAgentBench**

**核心协议**（与我们相关）：
1. **序列化**：LoCoMo 等数据集被 serialise 成连续流 `R`，**保持原始时间顺序**。
2. **Checkpoint 触发评测**：固定间隔（如 20%）触发 QA，捕获 memory 累积过程中的性能演化，**而非仅看最终状态**。
3. **LoCoMo 适配要点**：「each task comprises multiple sessions containing multi-turn dialogue sequences. ... the hierarchical organization makes LoCoMo inherently suitable for adaptation into a streaming format. ... evaluation queries are triggered immediately after their supporting evidence is ingested, ensuring strict temporal causality.」
4. **指标**：token-level F1 + insertion/retrieval latency。
5. **额外发现**：随着 memory 累积，**性能单调下降**；temporal reasoning 是持久瓶颈；aggressive compression 和 generative integration 多半把成本从 ingestion 转移到 retrieval，accuracy gain 有限。

**对我们的启发**：
- ✅ 复用 Neuromem 的 LoCoMo 串行化方案；它已经验证 LoCoMo QA 适配 streaming 在工程层是可行的。
- ✅ MemEye 的 streaming wrapper 可以照搬同样的 checkpoint（20%）策略。
- ⚡ **Claim**：Neuromem 的观察「performance degrades as memory accumulates」与 RecallFlow 的 v0 假设「response fingerprint 在 streaming 后期仍能保持 coverage」**正相关**——如果 streaming 后期 degradation 主要来自 retrieval 噪声而非 memory 压缩，RecallFlow capsule 设计就更显优势。这条 Claim 需要在我们自己的 streaming 实验里复现。

---

## 4. RecallFlow 自建 Streaming Wrapper 建议

> 本节是**实验层建议**，Coding Agent 可按此实现第一步 prototype。

### 4.1 LoCoMo streaming wrapper（最小骨架）

```python
# pseudo-code, NOT actual API
class LoCoMoStreamingWrapper:
    def __init__(self, locomo_json_path, compression_policy, budget_schedule=(0.25, 0.5, 0.75, 1.0)):
        self.dataset = load_locomo(locomo_json_path)  # 10 dialogs
        self.policy = compression_policy  # RecallFlow / StreamMeCo / MemForest / random / recency
        self.budget_schedule = budget_schedule
        self.checkpoints = {}

    def run(self, dialog_id):
        dialog = self.dataset[dialog_id]                          # 含 session_1..session_N + timestamps
        ordered_turns = sort_by_timestamp(dialog.turns)
        total = len(ordered_turns)

        for budget_frac in self.budget_schedule:
            checkpoint_size = int(total * budget_frac)
            memory = []
            for i, turn in enumerate(ordered_turns[:checkpoint_size]):
                memory.append(turn)
                if (i + 1) % chunk_size == 0:
                    memory = self.policy.compress(memory, budget=int(checkpoint_size * B))

            # 在 checkpoint 评测所有 evidence 命中该时间窗口的 QA
            qas = self.dataset.qas_for_dialog(dialog_id, within=[0, checkpoint_size])
            metrics = eval_qa(memory, qas, retriever=R)
            self.checkpoints[(dialog_id, budget_frac)] = {
                "memory_size": len(memory),
                "qa_acc": metrics.f1,
                "evidence_recall_at_k": metrics.recall_at_k,
                "retrieval_latency_ms": metrics.retrieval_ms,
                "insert_latency_ms": metrics.insert_ms,
            }
```

### 4.2 MemEye streaming wrapper（最小骨架）

- 数据迭代粒度：按 `round_id`（`"D1:1"`, `"D1:2"`, ...）单 turn 增量。
- 每个 checkpoint（20%）后跑一次 `run_benchmark.py` 子集（可人工裁剪 QA 列表只保留 `clue_round_ids <= checkpoint` 的子集），避免重复跑全量。
- raw image 可按 `round_id` 单独加载（`input_image` 字段），不必一次性塞进 memory；多模态压缩后保留 raw image pointer。

### 4.3 实验产出（最小集合）

| 输出 | 字段 |
|---|---|
| `results/streaming/locomo_recallflow.csv` | `(dialog_id, budget_frac, method, qa_acc, evidence_recall@10, retrieval_latency_ms, compression_latency_ms, memory_size)` |
| `results/streaming/memeye_recallflow.csv` | 同上，并按 X/Y 维度拆分 |
| `results/streaming/checkpoint_curve.png` | `budget_frac → qa_acc` 曲线，对比 RecallFlow / StreamMeCo / MemForest / recency / random |
| `results/streaming/bad_cases.md` | 哪些 QA 在 streaming 后期退化、原因分类（retrieval miss / summary loss / time break / visual detail loss） |

### 4.4 必须避免的 leakage

| 风险 | 规避方式 |
|---|---|
| 测试 QA 出现在 probe queries | Probe queries 只用 metadata / 已知 entity / 历史任务分布生成，禁止使用测试题面 |
| Compress 时访问了未来 turn 的 embedding | Streaming 模式下 commit-by-commit，**第 t 个 turn 压缩时只能用 t ≤ i 的 memory**（online k-center / sliding-window facility-location） |
| 时间戳归一化使用测试 QA evidence | 时间戳归一化只依赖 `session_N_date_time`，不参考 QA.evidence |

---

## 5. 实验阶段路线图（建议给 Experiment Agent）

| 阶段 | 任务 | 产出 |
|---|---|---|
| 1 | 接入 Neuromem 的 LoCoMo streaming serialization（可 fork 复用代码，若可获得） | `code/src/streaming/locomo_wrapper.py` |
| 2 | 实现 v0 streaming wrapper：按 `session` 增量 → checkpoint 评测 | smoke test 在 1 个 dialog 上跑通 |
| 3 | 加 MemEye 同等 wrapper | `code/src/streaming/memeye_wrapper.py` |
| 4 | 用 RecallFlow v0 + recency / random / embedding clustering 三个 baseline 跑 budget curve | 三条曲线对比图 |
| 5 | 接入 StreamMeCo / MemForest 做 must-beat baseline | 完整 baseline 矩阵 |
| 6 | 写 bad case 分析 | `docs/bad_cases_streaming.md` |

---

## 6. 不能 claim / 谨慎表述

| Claim | 备注 |
|---|---|
| "首个在 MemEye 上做 online memory compression 评测" | 需先复核 Neuromem / SimpleMem / HyMem 等是否已报过同类实验。最稳妥表述：「RecallFlow is one of the first to evaluate streaming memory compression on MemEye's visual-evidence benchmark」 |
| "Neuromem 验证 LoCoMo 可 streaming" | 是 Fact（来自 arXiv 2602.13967 §对应章节），可以直接 cite，但要写明 Neuromem 不覆盖 MemEye |
| "streaming 评测 = RecallFlow 直接强化" | 这是 Claim，需等实验支撑 |
| "StreamMeCo / MemForest 是为 offline 设计的" | 是 Claim（基于我们目前对两篇 paper 的阅读）。**精确表述为「其公开论文未声明 streaming 协议」**更安全 |

---

*更新：2026-07-06*
*下次同步：等 Coding Agent 完成 v0 + 实验 wrapper 接入 smoke test 后，再扩展 checkpoint 数量和 baseline 矩阵。*
