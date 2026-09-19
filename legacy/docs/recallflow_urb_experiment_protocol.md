# RecallFlow-URB Experiment Protocol

> Status: v0 experiment protocol  
> Audience: Experiment Coding Agent  
> Scope: implement and validate RecallFlow with a fixed Universal Recall Basis over Mem0-generated memory items.  
> Hard constraint: this protocol must not read benchmark test questions, gold answers, or evidence annotations during compression.

## 0. 给实验 Coding Agent 的执行合同

本文件是 RecallFlow-URB 原型实验的唯一执行口径。实验 agent 应先实现 **P0 压缩诊断闭环**，再进入检索代理评测和完整 QA。不要在 P0 阶段调用 answer model，也不要为了提高 LoCoMo 分数改 URB 文本、调 `tau` 或读取 QA 字段。

### 0.1 本轮目标

| 层级 | 必须完成 | 不在本轮阻塞 |
|---|---|---|
| P0 | 在 LoCoMo sample0 的 Mem0 memory nodes 上跑通 `embedding_kcenter`、`recallflow_urb_prune_only`、`recallflow_urb_full`，输出压缩诊断 JSONL + 详细 JSON。 | 完整 QA、judge、论文表格。 |
| P0 | 固定 URB bank，计算并缓存 family centroid，生成 10 维 response fingerprint。 | memory-conditioned probe、LLM probe generation。 |
| P0 | 每个新增模块至少一个 smoke/unit test。 | 大规模并发、成本优化。 |
| P0 | 写清楚 no-leakage 审计结果。 | 证明最终 benchmark SOTA。 |

### 0.2 代码路径必须按现有仓库布局

当前仓库已经使用 `code/compression/`，不要另建 `code/src/compression/`。预期文件级变更如下：

| 文件 | 动作 | 内容 |
|---|---|---|
| `code/compression/urb.py` | 新增 | 固定 URB bank、basis hash、centroid 计算、cache 读写、variant 构造。 |
| `code/compression/recallflow.py` | 修改 | 增加 `recallflow_compress_with_urb` 与 `recallflow_urb_prune_only` 包装，复用现有 response/coreset/capsule。 |
| `code/baselines/base.py` | 修改或复用 | 确保 `embedding_kcenter` 可直接接受 `MemoryNode.embedding`，预算口径与 URB 方法一致。 |
| `code/evaluation/scripts/run_recallflow_urb_diagnostics.py` | 新增 | P0 主入口：读取 memory nodes JSONL，运行 method，写 JSONL + detailed diagnostics。 |
| `code/evaluation/scripts/run_recallflow_urb_stability.py` | 新增 | URB wording stability ablation 入口；P0 之后实现即可。 |
| `code/tests_run/test_urb_smoke.py` | 新增 | URB bank、centroid shape、cache metadata、compression smoke。 |
| `coordination/experiments/work_log_experiments_codex.md` 或对应 agent 文件 | 追加 | 记录命令、输入路径、输出路径、异常和结论。 |

不要改动或提交 `external/`、datasets、models、API keys、`.env`。

### 0.3 P0 输入输出合同

P0 输入必须是已经生成好的 Mem0 memory item，不是原始对话 turn：

```text
external/rf_inputs/locomo_sample0_mem0_nodes.jsonl
```

每行一个 `MemoryNode` JSON，字段最低要求：

```json
{
  "node_id": "stable_memory_id",
  "text": "Mem0 generated memory text",
  "timestamp": 0.0,
  "embedding": [0.01, 0.02],
  "entities": [],
  "events": [],
  "modality": "text",
  "source": {
    "dataset": "LoCoMo",
    "sample_id": "locomo_0",
    "point_id": "optional_qdrant_id"
  },
  "raw_pointer": "optional_source_pointer"
}
```

如果输入缺少 embedding，P0 脚本可以调用 embedding API 补齐，但必须把补齐后的 nodes 另存为：

```text
external/rf_inputs/locomo_sample0_mem0_nodes.embedded.text-embedding-v4.jsonl
```

P0 输出：

```text
results/recallflow_urb_p0_locomo_sample0.jsonl
external/rf_outputs/diagnostics/locomo_0/{method}_budget50_seed0.json
external/cache/urb/urb_v0_text-embedding-v4_1024.npy
external/cache/urb/urb_v0_text-embedding-v4_1024.meta.json
```

`results/` 中只放可分享的小结果；完整 arrays、cache、Mem0 store dump 放 `external/`。

### 0.4 API 与模型配置

文档和代码中只允许引用环境变量名，不允许写入真实 key。

| 用途 | 环境变量 | 模型 |
|---|---|---|
| Embedding | `DASHSCOPE_API_KEY` | `text-embedding-v4`, dim `1024` |
| Chat/answer/judge，P0 不需要 | `RELAY_BASE_URL`, `RELAY_API_KEY` | `qwen3.6-plus` |

P0 只需要 embedding；不要因为 P0 调通而调用 chat model。

### 0.5 预算口径

给定 `n = len(nodes)` 和 `budget_ratio = 0.5`：

```python
budget = max(1, int(round(budget_ratio * n))) if n > 0 else 0
```

`recallflow_urb_prune_only` 必须严格保留 `budget` 个 representative。  
`recallflow_urb_full` 的 representative 数量也必须是 `budget`，但最终 retained memory 数可因 exception keep 大于 `budget`；必须分别记录：

```json
{
  "representative_budget": 123,
  "num_representatives": 123,
  "num_retained_after_exceptions": 135,
  "num_exceptions": 12
}
```

### 0.6 P0 主命令

实验 agent 实现后，至少运行：

```bash
python -m code.evaluation.scripts.run_recallflow_urb_diagnostics \
  --input-memory-nodes external/rf_inputs/locomo_sample0_mem0_nodes.jsonl \
  --methods embedding_kcenter,recallflow_urb_prune_only,recallflow_urb_full \
  --budget-ratio 0.5 \
  --embedding-model text-embedding-v4 \
  --embedding-dim 1024 \
  --basis-version urb_v0 \
  --tau 0.1 \
  --seed 0 \
  --output results/recallflow_urb_p0_locomo_sample0.jsonl \
  --diagnostics-dir external/rf_outputs/diagnostics/locomo_0
```

并运行 smoke tests：

```bash
python -m pytest code/tests_run/test_urb_smoke.py
python -m pytest code/tests_run/test_compression_smoke.py
```

如果当前环境没有 `pytest`，用已有项目约定的 test runner，但必须在 work log 中记录替代命令和结果。

### 0.7 No-Leakage 审计

P0 脚本和 `code/compression/urb.py` 必须能在不读取以下字段的情况下运行：

```text
question
qa
answer
gold
evidence
supporting_facts
```

最低审计要求：

1. 在 diagnostics JSON 写入：

```json
{
  "leakage_audit": {
    "compression_reads_qa": false,
    "compression_reads_gold": false,
    "compression_reads_evidence": false,
    "basis_is_fixed": true,
    "basis_conditioned_on_sample": false
  }
}
```

2. P0 输入 loader 只解析 `MemoryNode` 字段；遇到额外 QA/evidence 字段时，要么忽略，要么报错。推荐 P0 默认报错，可加 `--allow-extra-fields` 仅用于调试。
3. URB bank 必须是代码常量或版本化配置，不能由 dataset 文件动态生成。

### 0.8 P0 验收清单

| 检查项 | 通过标准 |
|---|---|
| URB bank | family 数 = 10；总 paraphrase 数 = 40；顺序稳定。 |
| Centroid | shape = `[10, 1024]`；每行 L2 norm 在 `[0.999, 1.001]`。 |
| Response | `A.shape = [10, n]`；每个 family row softmax sum 接近 1。 |
| Budget | prune-only retained 数严格等于 `budget`。 |
| Determinism | 同输入、同 seed，representative IDs 完全一致。 |
| Difference | `recallflow_urb_prune_only` 与 `embedding_kcenter` 的 representative set 不应在所有样本上完全相同；P0 sample0 如果相同，要记录而不是强行改算法。 |
| Diagnostics | JSONL 行包含 method/budget/path；详细 JSON 包含 representative IDs、mass、assignments、residuals、capsules。 |
| No leakage | diagnostics 中 no-leakage audit 为 true/false 明确，不留空。 |

## 1. One-Screen Summary

RecallFlow-URB compresses a Mem0 memory store by representing each memory item through its response to a fixed, dataset-agnostic set of long-term-memory recall-intent families.

The main method is:

```text
Universal Recall Basis with Paraphrase Pooling
F = 10 recall families
P = 4 paraphrases per family
K = 40 fixed texts
family centroid pooling
response fingerprint dimension = 10
tau = 0.1
```

The first experiment prototype should answer:

> Under a fixed memory budget, does response-space compression over a fixed Universal Recall Basis select different and more recall-useful Mem0 memories than embedding-space compression?

The first official prototype target is:

```text
Dataset: LoCoMo
Memory base: Mem0-generated memories
Budget: 50% retained
Methods: embedding_kcenter, recallflow_urb_prune_only, recallflow_urb_full
Metric stage: compression diagnostics first, QA/evidence evaluation second
```

## 2. Non-Negotiable Rules

| Rule | Requirement |
|---|---|
| Dataset-agnostic | The same URB bank must be used for LoCoMo, LongMemEval, PersonaMem, MemEye, and future datasets. |
| No leakage | Compression must not read test questions, gold answers, or evidence annotations. |
| No memory-conditioned probes in main method | The main method must not generate probes by extracting entities/events from the current memory stream. |
| Stable wording | Each family uses paraphrase pooling, not a single wording. |
| Auditable | The exact URB bank, centroids, config, and output diagnostics must be saved. |
| Cheap | URB text embeddings should be cached and reused. |
| Fixed tau | `tau = 0.1` for v0. Do not tune on benchmark performance. |
| v0 summary | Use `simple_capsule_summary`; no LLM summary in RecallFlow v0. |

Do not implement a method that uses:

```text
QA question -> probe
gold answer -> probe
evidence clue -> probe
per-sample generated future query -> probe
dataset-specific manually edited probe text
```

## 3. Method Name and Variants

Use these exact method IDs in code and result files:

| Method ID | Meaning |
|---|---|
| `embedding_kcenter` | Farthest-first k-center directly in memory embedding space. |
| `recallflow_urb_prune_only` | URB response fingerprint + coreset representatives only. |
| `recallflow_urb_full` | URB response fingerprint + coreset + capsule routing + exception keep. |
| `urb_single_first` | Stability ablation: one paraphrase per family, first text only. |
| `urb_all_40_no_pool` | Stability ablation: all 40 paraphrases used as 40 separate axes. |
| `urb_random_text` | Negative control: generic random texts with same count/shape as URB. |

The main method is:

```text
recallflow_urb_full
```

## 4. Universal Recall Basis v0

The following bank is part of the method configuration. Do not edit it per dataset.

```python
UNIVERSAL_RECALL_BASIS = {
    "profile_identity": [
        "What stable personal facts should be remembered?",
        "What background information is important?",
        "What identity or profile details are mentioned?",
        "What long-term attributes describe a person or user?",
    ],
    "preference_habit": [
        "What preferences are mentioned?",
        "What does the user like or dislike?",
        "Which tastes, habits, or choices should be remembered?",
        "What personal preferences may matter in the future?",
    ],
    "goal_plan": [
        "What goals or intentions are mentioned?",
        "What future plans should be remembered?",
        "What does someone want or plan to do?",
        "Which intended actions may be useful later?",
    ],
    "event_action": [
        "What important events happened?",
        "What actions or decisions were made?",
        "What happened that may need to be recalled later?",
        "Which completed activities are worth remembering?",
    ],
    "temporal_change": [
        "What changed over time?",
        "What happened earlier versus later?",
        "Which updates or changes should be remembered?",
        "What temporal sequence or transition is important?",
    ],
    "relationship_role": [
        "What relationships between people are important?",
        "What roles, affiliations, or organizations are mentioned?",
        "Who is connected to whom and how?",
        "What social or professional relationship should be remembered?",
    ],
    "location_object": [
        "What places or locations are mentioned?",
        "What objects, possessions, or physical details matter?",
        "Which environment or setting information should be remembered?",
        "What location or object detail may be useful later?",
    ],
    "commitment_task": [
        "What commitments or promises were made?",
        "What tasks or obligations should be remembered?",
        "What needs to be done later?",
        "Which responsibilities or follow-ups are mentioned?",
    ],
    "constraint_need": [
        "What constraints or requirements are mentioned?",
        "What needs, limitations, or conditions matter?",
        "What restrictions should be remembered for future decisions?",
        "Which practical requirements may affect future actions?",
    ],
    "specific_exception": [
        "What unusual or specific detail may be important later?",
        "What rare fact should not be lost?",
        "Which precise detail could be needed for future recall?",
        "What exception or special case is worth preserving?",
    ],
}
```

Expected constants:

```text
num_families = 10
num_paraphrases_per_family = 4
num_probe_texts = 40
fingerprint_dim = 10 for main method
```

## 5. Mathematical Definition

Let:

```text
B_f = paraphrases in family f
q_fj = j-th paraphrase in family f
z_fj = embed(q_fj)
e_i = embed(memory item i)
```

Normalize each paraphrase embedding:

```text
z'_fj = normalize(z_fj)
```

Family centroid:

```text
u_f = normalize(mean_j z'_fj)
```

Normalize memory item embedding:

```text
e'_i = normalize(e_i)
```

Raw family response:

```text
S[f, i] = cosine(u_f, e'_i)
```

Query-wise softmax over memory items:

```text
A[f, :] = softmax(S[f, :] / tau)
tau = 0.1
```

Memory fingerprint:

```text
fingerprint(m_i) = A[:, i]
```

Response mass:

```text
mass_i = sum_f A[f, i]
```

Main method response matrix shape:

```text
A.shape = [10, num_memory_items]
fingerprints.shape = [num_memory_items, 10]
```

## 6. Pipeline Definition

The RecallFlow-URB compression pipeline must be:

```text
Mem0-generated memory items
  -> export MemoryNode[]
  -> load fixed Universal Recall Basis
  -> compute/cache family centroids
  -> compute response matrix A[f, i]
  -> response fingerprints f_i
  -> farthest-first k-center + mass tiebreak
  -> assign nodes to representatives
  -> residual routing
  -> capsules / exceptions / archive
  -> diagnostics
```

Do not use this pipeline:

```text
Mem0 memory items
  -> extract entity/event from this sample
  -> generate sample-specific probes
```

Memory-conditioned probes may be implemented later as an appendix/future extension, but not as the main method.

## 7. First Prototype Scope

### Prototype P0: URB Representation Sanity

Input:

```text
LoCoMo sample 0 Mem0-generated memory items
```

Methods:

```text
embedding_kcenter
recallflow_urb_prune_only
recallflow_urb_full
```

Budget:

```text
budget_ratio = 0.5
budget = round(0.5 * num_memory_items)
```

Output:

```text
results/recallflow_urb_p0_locomo_sample0.jsonl
```

P0 does not run QA. It only validates compression diagnostics.

Success criteria:

| Criterion | Requirement |
|---|---|
| Deterministic | Same input and same seed produce the same representative IDs. |
| No leakage | Compression code path does not load QA/gold/evidence fields. |
| Budget respected | `recallflow_urb_prune_only` retains exactly `budget` representative nodes. |
| Diagnostics complete | Row contains mass, residuals, assignments, representative IDs. |
| Non-degenerate | `recallflow_urb_prune_only` representative set is not always identical to `embedding_kcenter`. |

### Prototype P1: LoCoMo Store-Level Compression

Input:

```text
LoCoMo Mem0 full memory store
```

Methods:

```text
embedding_kcenter@50
recallflow_urb_prune_only@50
recallflow_urb_full@50
```

Output:

```text
external/.../rf_outputs/locomo_sample0_rf50_plan.json
results/recallflow_urb_p1_locomo_store_diagnostics.jsonl
```

P1 still does not need full QA. It should verify that RecallFlow can compress real Mem0-generated memory items.

### Prototype P2: Retrieval/Evidence Proxy

Use the same compressed plans from P1.

Evaluate:

```text
evidence_recall_at_1
evidence_recall_at_3
evidence_recall_at_5
retrieval_latency_sec
```

Important: evidence annotations can be used for evaluation only after compression finishes. The compression code must not read them.

### Prototype P3: Full QA

Materialize compressed stores and run the same Mem0/MemForest search-answer evaluator:

```text
Mem0 full store
MemForest@50 store
RecallFlow-URB prune-only@50 store
RecallFlow-URB full@50 store
```

Report:

```text
QA score
evidence recall@k
memory size
retrieval latency
compression time
```

## 8. Data and Memory Item Definition

The main compression input is a list of Mem0-generated memories, not raw dialogue turns.

Required `MemoryNode` fields:

```python
MemoryNode(
    node_id="qdrant_point_id_or_stable_id",
    text="memory text from payload['data']",
    timestamp=float_or_parseable_time,
    embedding=[...],  # from Qdrant vector or embedding API
    entities=[],      # optional in v0
    events=[],        # optional in v0
    modality="text",
    source={
        "dataset": "LoCoMo",
        "sample_id": "...",
        "user_id": "...",
        "point_id": "...",
    },
    raw_pointer="qdrant://..."
)
```

Do not compress raw turns for the main experiment:

```text
Raw dialogue turn compression = not main v0 experiment
Mem0-generated memory item compression = main v0 experiment
```

## 9. Required Implementation Interfaces

### 9.1 UniversalRecallBasis

Suggested location:

```text
code/compression/urb.py
```

Required public API:

```python
from dataclasses import dataclass
from typing import Callable, Dict, List


@dataclass(frozen=True)
class UniversalRecallBasis:
    families: Dict[str, List[str]]

    @property
    def family_names(self) -> List[str]:
        return list(self.families.keys())

    @property
    def num_families(self) -> int:
        return len(self.families)

    @property
    def num_paraphrases(self) -> int:
        return sum(len(v) for v in self.families.values())


def load_universal_recall_basis() -> UniversalRecallBasis:
    """Return the fixed v0 Universal Recall Basis.

    This function must not inspect dataset files, memory items, QA, answers,
    or evidence annotations.
    """
    return UniversalRecallBasis(families=UNIVERSAL_RECALL_BASIS)
```

Required deterministic hash:

```python
import hashlib
import json


def basis_hash(basis: UniversalRecallBasis) -> str:
    """Hash the exact ordered URB text bank for cache invalidation."""
    payload = json.dumps(
        basis.families,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
```

The hash must be written into every centroid cache metadata and every diagnostics row.

### 9.2 Family Centroid Computation

Required behavior:

```python
import numpy as np


def l2_normalize(x: np.ndarray, axis: int = -1, eps: float = 1e-12) -> np.ndarray:
    norm = np.linalg.norm(x, axis=axis, keepdims=True)
    return x / np.maximum(norm, eps)


def compute_basis_centroids(
    basis: UniversalRecallBasis,
    embed_fn,
) -> tuple[np.ndarray, list[str]]:
    """Compute normalized family centroids.

    Returns:
        centroids: [num_families, dim]
        family_names: list aligned with centroids rows
    """
    centroids = []
    names = []
    for family_name, paraphrases in basis.families.items():
        embs = np.asarray([embed_fn(text) for text in paraphrases], dtype=np.float64)
        embs = l2_normalize(embs, axis=1)
        centroid = l2_normalize(embs.mean(axis=0, keepdims=True), axis=1)[0]
        centroids.append(centroid)
        names.append(family_name)
    return np.stack(centroids, axis=0), names
```

Cache requirement:

```text
Cache centroids by:
  embedding_model
  basis_version
  hash of all basis texts
```

Suggested cache path:

```text
external/cache/urb/urb_v0_text-embedding-v4_1024.npy
external/cache/urb/urb_v0_text-embedding-v4_1024.meta.json
```

Required metadata shape:

```json
{
  "basis_version": "urb_v0",
  "basis_hash": "16_hex_chars",
  "embedding_model": "text-embedding-v4",
  "embedding_dim": 1024,
  "family_names": ["profile_identity"],
  "num_families": 10,
  "num_paraphrases": 40,
  "created_at": "2026-07-07T00:00:00+08:00"
}
```

Cache loading must validate:

```text
basis_version matches
basis_hash matches current bank
embedding_model matches
embedding_dim matches
centroids.shape == [10, 1024]
```

If any validation fails, recompute and overwrite cache.

### 9.3 RecallFlow Compression With URB

Required signature:

```python
def recallflow_compress_with_urb(
    nodes: list[MemoryNode],
    basis_centroids,
    family_names: list[str],
    *,
    budget: int,
    tau: float = 0.1,
    seed: int = 0,
) -> CompressedMemory:
    """Compress memory nodes using URB family centroids.

    This function must reuse existing response, coreset, assignment, and
    capsule logic wherever possible.
    """
```

Expected internal flow:

```python
node_embs = np.asarray([node.embedding for node in nodes])

response, fingerprints, mass = compute_response_fingerprints(
    query_embs=basis_centroids,
    node_embs=node_embs,
    tau=0.1,
)

representatives = select_representatives(
    fingerprints=fingerprints,
    mass=mass,
    budget=budget,
    seed=seed,
)

assignments, residuals = assign_to_representatives(
    fingerprints=fingerprints,
    representative_indices=representatives,
)

capsules = build_capsules(...)
```

Reference implementation skeleton:

```python
from time import perf_counter
import numpy as np

from .capsule import assign_to_representatives, build_capsules, capsules_retained_ids
from .coreset import select_representatives
from .recallflow import CompressedMemory
from .response import compute_response_fingerprints


def recallflow_compress_with_urb(
    nodes,
    basis_centroids,
    family_names,
    *,
    budget,
    tau=0.1,
    seed=0,
    full=True,
):
    """Compress with fixed URB response fingerprints.

    Implements docs/recallflow_urb_experiment_protocol.md §5 and reuses
    docs/recallflow_implementation_guide.md §4-§7.
    """
    t0 = perf_counter()
    if tau != 0.1:
        raise ValueError("RecallFlow v0 fixes tau=0.1; use a separate sensitivity script.")

    n_list = list(nodes)
    if not n_list:
        return CompressedMemory(diagnostics={"reason": "empty"})

    node_embs = np.asarray([n.embedding for n in n_list], dtype=np.float64)
    if node_embs.ndim != 2:
        raise ValueError("all MemoryNode.embedding values must be present before URB compression")

    response, fingerprints, mass = compute_response_fingerprints(
        query_embs=np.asarray(basis_centroids, dtype=np.float64),
        node_embs=node_embs,
        tau=tau,
    )

    b = min(max(int(budget), 0), len(n_list))
    reps = select_representatives(
        fingerprints=fingerprints,
        mass=mass,
        budget=b,
        seed=seed,
    )
    assignments, residuals = assign_to_representatives(
        fingerprints=fingerprints,
        representative_indices=reps,
    )

    if full:
        capsules = build_capsules(
            nodes=n_list,
            representative_indices=reps,
            assignments=assignments,
            residuals=residuals,
            mass=mass,
        )
        retained = capsules_retained_ids(capsules)
    else:
        capsules = []
        retained = [n_list[i].node_id for i in reps]

    retained_set = set(retained)
    archived = [n.node_id for n in n_list if n.node_id not in retained_set]
    diag = {
        "family_names": list(family_names),
        "tau": tau,
        "budget": b,
        "num_representatives": len(reps),
        "representative_indices": [int(i) for i in reps],
        "representative_ids": [n_list[i].node_id for i in reps],
        "response_shape": list(response.shape),
        "fingerprint_shape": list(fingerprints.shape),
        "mass": mass.tolist(),
        "assignments": assignments.tolist(),
        "residuals": residuals.tolist(),
        "num_retained_after_exceptions": len(retained),
        "num_archived": len(archived),
        "compression_latency_sec": float(perf_counter() - t0),
    }
    return CompressedMemory(
        capsules=capsules,
        retained_node_ids=retained,
        archive_node_ids=archived,
        diagnostics=diag,
    )
```

Important: if existing `build_capsules` requires additional quantile args, use the current repository defaults. Do not add a global hard cap to exceptions in P0; record exception count instead.

Diagnostics must include:

```python
{
    "basis_version": "urb_v0",
    "family_names": family_names,
    "num_families": 10,
    "num_paraphrases": 40,
    "tau": 0.1,
    "budget": budget,
    "representative_ids": [...],
    "representative_indices": [...],
    "mass": [...],
    "assignments": [...],
    "residuals": [...],
    "num_exceptions": ...,
    "num_archived": ...,
    "compression_latency_sec": ...,
}
```

### 9.4 MemoryNode JSONL Loader

P0 loader must be narrow. It should not silently convert full benchmark examples into memory nodes.

```python
import json
from pathlib import Path

from code.compression.schema import MemoryNode


ALLOWED_NODE_FIELDS = {
    "node_id",
    "text",
    "timestamp",
    "embedding",
    "entities",
    "events",
    "modality",
    "source",
    "raw_pointer",
}

FORBIDDEN_COMPRESSION_FIELDS = {
    "question",
    "questions",
    "qa",
    "answer",
    "answers",
    "gold",
    "gold_answer",
    "evidence",
    "supporting_facts",
}


def load_memory_nodes_jsonl(path: str, *, allow_extra_fields: bool = False) -> list[MemoryNode]:
    nodes = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        forbidden = sorted(FORBIDDEN_COMPRESSION_FIELDS & set(row))
        if forbidden:
            raise ValueError(f"{path}:{line_no} contains forbidden compression fields: {forbidden}")
        extra = sorted(set(row) - ALLOWED_NODE_FIELDS)
        if extra and not allow_extra_fields:
            raise ValueError(f"{path}:{line_no} contains unexpected fields: {extra}")
        clean = {k: row[k] for k in ALLOWED_NODE_FIELDS if k in row}
        nodes.append(MemoryNode.from_dict(clean))
    return nodes
```

### 9.5 Diagnostics Writer

The JSONL row should stay small; large vectors and arrays go into detailed JSON.

```python
import json
from pathlib import Path
from datetime import datetime, timezone


def write_diagnostics(
    *,
    output_jsonl,
    diagnostics_dir,
    sample_id,
    dataset,
    method,
    budget_ratio,
    compressed,
    basis_meta,
    embedding_model,
    embedding_dim,
):
    diagnostics_dir = Path(diagnostics_dir)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    detail_path = diagnostics_dir / f"{method}_budget{int(budget_ratio * 100)}_seed0.json"

    detail = dict(compressed.diagnostics)
    detail["capsules"] = [c.to_dict() for c in compressed.capsules]
    detail["leakage_audit"] = {
        "compression_reads_qa": False,
        "compression_reads_gold": False,
        "compression_reads_evidence": False,
        "basis_is_fixed": True,
        "basis_conditioned_on_sample": False,
    }
    detail_path.write_text(
        json.dumps(detail, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    row = {
        "sample_id": sample_id,
        "dataset": dataset,
        "method": method,
        "budget_ratio": budget_ratio,
        "budget": compressed.diagnostics.get("budget"),
        "num_nodes_before": compressed.diagnostics.get("num_nodes_before"),
        "num_nodes_after": len(compressed.retained_node_ids),
        "num_representatives": compressed.diagnostics.get("num_representatives"),
        "num_exceptions": compressed.diagnostics.get("num_exceptions", 0),
        "num_archived": len(compressed.archive_node_ids),
        "basis_version": basis_meta.get("basis_version"),
        "basis_hash": basis_meta.get("basis_hash"),
        "num_families": basis_meta.get("num_families"),
        "num_paraphrases": basis_meta.get("num_paraphrases"),
        "embedding_model": embedding_model,
        "embedding_dim": embedding_dim,
        "tau": compressed.diagnostics.get("tau"),
        "representative_ids": compressed.diagnostics.get("representative_ids"),
        "compression_latency_sec": compressed.diagnostics.get("compression_latency_sec"),
        "diagnostics_path": str(detail_path),
        "date": datetime.now(timezone.utc).date().isoformat(),
    }
    with Path(output_jsonl).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
```

## 10. Stability Ablations

Implement these variants after P0 works:

| Variant | Fingerprint dim | Description |
|---|---:|---|
| `urb_centroid` | 10 | Main method. Family centroid over 4 paraphrases. |
| `urb_single_first` | 10 | Use only the first paraphrase from each family. |
| `urb_all_40_no_pool` | 40 | Use all paraphrases as separate axes. |
| `urb_random_text` | 10 or 40 | Random generic texts, same count as comparison variant. |

Required metrics:

```text
representative_overlap_with_urb_centroid
mass_spearman_correlation_with_urb_centroid
residual_distribution_mean
residual_distribution_p90
num_exceptions
num_archived
compression_latency_sec
```

Representative overlap definition:

```python
def representative_overlap(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)
```

Mass rank correlation should use Spearman if scipy is available. If not, compute rank arrays with numpy and use Pearson correlation over ranks.

## 11. Output Schemas

### 11.1 Compression Diagnostics JSONL

Each row must be one method on one sample under one budget:

```json
{
  "sample_id": "locomo_0",
  "dataset": "LoCoMo",
  "method": "recallflow_urb_full",
  "budget_ratio": 0.5,
  "budget": 123,
  "num_nodes_before": 246,
  "num_nodes_after": 123,
  "num_families": 10,
  "num_paraphrases": 40,
  "basis_version": "urb_v0",
  "embedding_model": "text-embedding-v4",
  "embedding_dim": 1024,
  "tau": 0.1,
  "representative_ids": ["..."],
  "num_capsules_after": 123,
  "num_exceptions": 12,
  "num_archived": 111,
  "compression_latency_sec": 1.23,
  "diagnostics_path": "external/.../diagnostics/locomo_0_rf_urb50.json",
  "date": "2026-07-07"
}
```

Large arrays such as full `mass`, `assignments`, and `residuals` may be stored in `diagnostics_path`, but the row must include the path.

### 11.2 Detailed Diagnostics JSON

```json
{
  "sample_id": "locomo_0",
  "method": "recallflow_urb_full",
  "family_names": ["profile_identity", "..."],
  "representative_ids": ["..."],
  "representative_indices": [0, 5, 9],
  "mass": [0.1, 0.2],
  "assignments": [0, 1],
  "residuals": [0.0, 0.4],
  "capsules": [
    {
      "capsule_id": "cap_0000",
      "representative_id": "...",
      "member_node_ids": ["..."],
      "exception_node_ids": ["..."],
      "archive_node_ids": ["..."],
      "summary": "..."
    }
  ]
}
```

### 11.3 Stability JSONL

```json
{
  "sample_id": "locomo_0",
  "dataset": "LoCoMo",
  "budget_ratio": 0.5,
  "reference_method": "urb_centroid",
  "variant": "urb_single_first",
  "representative_overlap": 0.72,
  "mass_spearman": 0.81,
  "num_representatives": 123,
  "num_exceptions": 10,
  "compression_latency_sec": 1.11,
  "date": "2026-07-07"
}
```

## 12. Experiment Commands

The exact commands may change after implementation, but the coding agent should preserve this command shape.

### P0 Diagnostics

```bash
python -m code.evaluation.scripts.run_recallflow_urb_diagnostics \
  --input-memory-nodes external/rf_inputs/locomo_sample0_mem0_nodes.jsonl \
  --method recallflow_urb_full \
  --budget-ratio 0.5 \
  --embedding-model text-embedding-v4 \
  --embedding-dim 1024 \
  --basis-version urb_v0 \
  --tau 0.1 \
  --seed 0 \
  --output results/recallflow_urb_p0_locomo_sample0.jsonl
```

### P0 Baseline Comparison

```bash
for method in embedding_kcenter recallflow_urb_prune_only recallflow_urb_full; do
  python -m code.evaluation.scripts.run_recallflow_urb_diagnostics \
    --input-memory-nodes external/rf_inputs/locomo_sample0_mem0_nodes.jsonl \
    --method "$method" \
    --budget-ratio 0.5 \
    --embedding-model text-embedding-v4 \
    --embedding-dim 1024 \
    --basis-version urb_v0 \
    --tau 0.1 \
    --seed 0 \
    --output results/recallflow_urb_p0_locomo_sample0.jsonl
done
```

### Stability

```bash
for variant in urb_centroid urb_single_first urb_all_40_no_pool urb_random_text; do
  python -m code.evaluation.scripts.run_recallflow_urb_stability \
    --input-memory-nodes external/rf_inputs/locomo_sample0_mem0_nodes.jsonl \
    --variant "$variant" \
    --budget-ratio 0.5 \
    --embedding-model text-embedding-v4 \
    --embedding-dim 1024 \
    --seed 0 \
    --output results/recallflow_urb_stability_locomo_sample0.jsonl
done
```

## 13. Evaluation After Compression

Full QA evaluation is not part of P0. When implemented, it must satisfy:

```text
same dataset
same QA set
same answer model
same judge
same retrieval top_k
same prompt template
different memory store only
```

The only variable should be the compression policy.

Formal comparison table:

| Method | Budget | QA | Evidence R@5 | Memory size | Retrieval latency | Compression time |
|---|---:|---:|---:|---:|---:|---:|
| Mem0 full | 100% | | | | | |
| Embedding k-center | 50% | | | | | |
| MemForest | 50% | | | | | |
| RF-URB prune-only | 50% | | | | | |
| RF-URB full | 50% | | | | | |

## 14. Evidence Recall Definition

Use evidence labels only in evaluation, never compression.

Recommended v0 definition:

```text
For each QA item with evidence references, map each evidence reference to one
or more original Mem0 memory items using raw pointers or source metadata.

Evidence recall@k = fraction of QA items for which at least one mapped evidence
memory item appears in top-k retrieved memories from the compressed store.
```

If direct mapping from QA evidence to Mem0 memory items is not available, use a documented proxy:

```text
Embed gold evidence text or source turn text.
Find nearest original Mem0 memory items before compression.
Treat these nearest memory items as pseudo-evidence.
```

Any proxy must be labeled as proxy in result files:

```json
{
  "evidence_recall_type": "pseudo_evidence_embedding_match"
}
```

## 15. Reviewer-Facing Claims and Non-Claims

Allowed:

```text
RecallFlow uses a predefined Universal Recall Basis to measure memory-item
response patterns along fixed recall-intent dimensions.
```

```text
The basis is fixed before benchmark evaluation and does not use test questions,
gold answers, or evidence labels.
```

```text
Paraphrase pooling reduces sensitivity to individual probe wording.
```

Do not claim:

```text
The URB fully covers all possible future questions.
RecallFlow predicts future user queries.
RecallFlow uses adaptive probes from each sample in the main method.
RecallFlow is the first memory compression method.
```

Recommended paper wording:

```text
RecallFlow uses a predefined Universal Recall Basis, a dataset-agnostic set of
long-term-memory recall-intent families. Each family is represented by a
normalized centroid over multiple paraphrases, producing stable calibration
axes for measuring memory response patterns. The basis is fixed before seeing
any benchmark instances and never uses test questions, gold answers, or
evidence labels.
```

## 16. Implementation Checklist

The coding agent should complete these in order:

| Step | Task | Validation |
|---:|---|---|
| 1 | Add fixed URB bank module | Unit test family count = 10, paraphrase count = 40. |
| 2 | Add centroid computation | Unit test centroid shape `[10, dim]`, L2 norm near 1. |
| 3 | Add centroid cache | Re-run should avoid re-embedding URB texts. |
| 4 | Add URB compression wrapper | Smoke on fixture and Mem0 memory nodes. |
| 5 | Add diagnostics writer | JSONL row + detailed JSON arrays. |
| 6 | Add stability variants | Compare overlap/correlation. |
| 7 | Run P0 LoCoMo sample0 | Pass success criteria. |
| 8 | Only then add QA evaluator | Keep compression/evaluation separation. |

## 17. Completion Criteria for This Protocol

The first implementation is complete when:

```text
1. code can compute URB centroids from the fixed bank
2. code can compress Mem0 memory nodes with recallflow_urb_prune_only
3. code can compress Mem0 memory nodes with recallflow_urb_full
4. output diagnostics contain representative_ids, mass, assignments, residuals
5. no compression path reads QA/gold/evidence
6. embedding_kcenter and RF-URB outputs are both recorded under identical budgets
7. at least one stability row is produced for urb_single_first vs urb_centroid
```

Do not block P0 on full QA evaluation. The first goal is to validate that URB response fingerprints produce a stable, auditable compression plan over real Mem0-generated memories.
