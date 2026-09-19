# RecallFlow 实现说明

> 更新时间：2026-07-05  
> 目的：给合作者对接 RecallFlow v0 实验，明确要写哪些模块、每一步输入输出、response 分数怎么算、以及最小代码骨架。

## ✅ 一屏结论

RecallFlow v0 的最小闭环是：

| 步骤 | 模块 | 输出 |
|---:|---|---|
| 1 | memory schema | 统一 memory nodes |
| 2 | probe generator | 生成不泄漏测试答案的 probe queries |
| 3 | response scorer | 计算 `A[q, i]` 检索响应矩阵 |
| 4 | response fingerprint | 每个 node 得到 `A[:, i]` |
| 5 | coreset selector | 在 response space 选择代表 nodes |
| 6 | capsule builder | merge / keep exception / archive |
| 7 | evaluator | budget-accuracy、evidence recall、latency |

核心实现目标：

> **不要写成多个 lambda 的 node importance scorer；先实现“压缩前后 retrieval response 尽量一致”。**

## 1. 推荐目录

建议先在 `code/src/compression/` 下实现 RecallFlow v0：

```text
code/src/compression/
├── schema.py          # MemoryNode / MemoryCapsule 数据结构
├── probes.py          # probe query 生成
├── response.py        # response matrix 和 fingerprint
├── coreset.py         # response-space coreset 选择
├── capsule.py         # residual routing 和 capsule 构建
└── recallflow.py      # 主入口：fit_compress / update
```

评测相关：

```text
code/evaluation/
├── adapters/          # LoCoMo / Mem0 / MemEye 数据转 memory nodes
├── scripts/           # 跑实验入口
└── analysis/          # 画 budget-accuracy / bad case 表
```

## 2. 数据结构

### 2.1 MemoryNode

第一版只要求文本可跑通，后面再加多模态字段。

```python
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class MemoryNode:
    node_id: str
    text: str
    timestamp: float
    embedding: Optional[List[float]] = None
    entities: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    modality: str = "text"
    source: Dict[str, Any] = field(default_factory=dict)
    raw_pointer: Optional[str] = None
```

### 2.2 ProbeQuery

```python
@dataclass
class ProbeQuery:
    probe_id: str
    text: str
    probe_type: str  # entity / temporal / event / task / multimodal
    source_node_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### 2.3 MemoryCapsule

```python
@dataclass
class MemoryCapsule:
    capsule_id: str
    representative_id: str
    member_node_ids: List[str]
    exception_node_ids: List[str] = field(default_factory=list)
    summary: str = ""
    timestamp_span: Optional[tuple] = None
    entities: List[str] = field(default_factory=list)
    raw_pointers: List[str] = field(default_factory=list)
```

## 3. Probe queries 怎么生成

Probe queries 是压缩时的“校准问题”，不是评测问题。

### 3.1 不能做什么

| 禁止项 | 原因 |
|---|---|
| 使用测试集 QA question | oracle leakage |
| 根据 gold answer 生成 probe | oracle leakage |
| 每个样本评测前重新用该样本问题生成 probe | 会变成 test-time query-conditioned cheating |

### 3.2 安全来源

| Probe 类型 | 生成来源 | 模板 |
|---|---|---|
| Entity | node.entities | `关于 {entity} 我们知道什么？` |
| Event | node.events 或 LLM 抽取事件短语 | `{event} 是怎么发生的？` |
| Temporal | timestamp / window id | `这段时间发生了什么重要变化？` |
| Preference / state | likes、wants、plans、changes 等模式 | `{entity} 的偏好或状态是什么？` |
| Task | 当前 agent goal / 历史任务分布 | `为了完成 {task}，需要记住什么？` |

### 3.3 v0 规则版生成器

```python
def build_probe_queries(nodes, window_size=8, max_probes=64):
    probes = []
    windows = [nodes[i:i + window_size] for i in range(0, len(nodes), window_size)]

    for w_idx, window in enumerate(windows):
        # 每个窗口至少一个 temporal probe，保证时间线覆盖
        probes.append(ProbeQuery(
            probe_id=f"w{w_idx}_temporal",
            text="这段时间发生了什么重要变化？",
            probe_type="temporal",
            source_node_ids=[n.node_id for n in window],
            metadata={"window_id": w_idx},
        ))

        # entity probes
        entity_counts = {}
        for node in window:
            for ent in node.entities:
                entity_counts[ent] = entity_counts.get(ent, 0) + 1
        top_entities = sorted(entity_counts, key=entity_counts.get, reverse=True)[:3]

        for ent in top_entities:
            probes.append(ProbeQuery(
                probe_id=f"w{w_idx}_entity_{ent}",
                text=f"关于 {ent} 我们知道什么？",
                probe_type="entity",
                source_node_ids=[n.node_id for n in window if ent in n.entities],
                metadata={"entity": ent, "window_id": w_idx},
            ))

        # event probes
        events = []
        for node in window:
            events.extend(node.events[:2])
        for e_idx, event in enumerate(events[:3]):
            probes.append(ProbeQuery(
                probe_id=f"w{w_idx}_event_{e_idx}",
                text=f"{event} 是怎么发生的？",
                probe_type="event",
                source_node_ids=[n.node_id for n in window],
                metadata={"event": event, "window_id": w_idx},
            ))

    return deduplicate_probes(probes)[:max_probes]
```

### 3.4 Probe 去重

v0 可以先用 embedding cosine 去重：

```python
def deduplicate_probes(probes, embed_fn=None, threshold=0.9):
    if embed_fn is None:
        seen = set()
        unique = []
        for p in probes:
            key = p.text.strip()
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique

    # 后续可加 embedding-based dedup
    return probes
```

## 4. Response 分数怎么算

### 4.1 原始检索分数

对每个 probe `q` 和 memory node `m_i`：

```text
S[q, i] = cosine(embed(q), embed(m_i))
```

如果底层 memory system 有自己的 retriever，则直接用它的 score：

```text
S[q, i] = R(q, m_i)
```

### 4.2 Query-wise softmax

不同 query 的相似度尺度可能不同，所以建议按 query 做归一化：

```text
A[q, :] = softmax(S[q, :] / tau)
```

`A[q, i]` 表示在 probe `q` 下，node `i` 的相对响应强度。

v0 固定：

```text
tau = 0.1
```

后续做敏感性分析即可，不要把它写成需要精调的核心超参。

### 4.3 Response fingerprint

每个 node 的 response fingerprint 是 response matrix 的一列：

```text
f_i = A[:, i]
```

同时计算 response mass：

```text
mass_i = sum_q A[q, i]
```

含义：

| 量 | 意义 |
|---|---|
| `f_i` | node 在不同 probe 下的响应模式 |
| `mass_i` | node 总体被 probe 需要的程度 |

### 4.4 最小代码

```python
import numpy as np

def l2_normalize(x, axis=-1, eps=1e-12):
    norm = np.linalg.norm(x, axis=axis, keepdims=True)
    return x / np.maximum(norm, eps)

def softmax(x, axis=-1):
    x = x - np.max(x, axis=axis, keepdims=True)
    exp_x = np.exp(x)
    return exp_x / np.sum(exp_x, axis=axis, keepdims=True)

def compute_response_fingerprints(query_embs, node_embs, tau=0.1):
    query_embs = l2_normalize(np.asarray(query_embs), axis=1)
    node_embs = l2_normalize(np.asarray(node_embs), axis=1)

    # S: [num_queries, num_nodes]
    scores = query_embs @ node_embs.T

    # A: [num_queries, num_nodes]
    response = softmax(scores / tau, axis=1)

    # F: [num_nodes, num_queries]
    fingerprints = response.T
    mass = fingerprints.sum(axis=1)

    return response, fingerprints, mass
```

## 5. Response 差异和 residual 怎么算

### 5.1 两个 node 的 response 距离

v0 推荐 cosine distance：

```text
d(i, j) = 1 - cosine(f_i, f_j)
```

代码：

```python
def cosine_distance_matrix(x):
    x = l2_normalize(np.asarray(x), axis=1)
    sim = x @ x.T
    return 1.0 - sim
```

### 5.2 Node 到代表点的 residual

选出代表 node 后，每个 node 分配给最近代表点：

```text
assign(i) = argmin_c d(f_i, f_c)
residual_i = min_c d(f_i, f_c)
```

代码：

```python
def assign_to_representatives(fingerprints, representative_indices):
    f = l2_normalize(np.asarray(fingerprints), axis=1)
    reps = f[representative_indices]
    distances = 1.0 - (f @ reps.T)
    assignments = np.argmin(distances, axis=1)
    residuals = np.min(distances, axis=1)
    return assignments, residuals
```

### 5.3 residual 小 / 大怎么判

避免手写绝对阈值，使用分位数：

| 条件 | v0 动作 |
|---|---|
| `mass_i` 很低 | archive / prune |
| `residual_i` 位于本簇最低 60%-70% | merge 到 capsule |
| `residual_i` 位于本簇最高 10%-20% 且 mass 高 | keep as exception |
| 中间区域 | 根据预算保留或 merge |

代码骨架：

```python
def route_cluster_members(member_indices, residuals, mass, low_mass_quantile=0.2, exception_quantile=0.8):
    member_res = residuals[member_indices]
    member_mass = mass[member_indices]

    low_mass_bar = np.quantile(mass, low_mass_quantile)
    exception_bar = np.quantile(member_res, exception_quantile)

    merge_ids, exception_ids, archive_ids = [], [], []

    for idx in member_indices:
        if mass[idx] <= low_mass_bar:
            archive_ids.append(idx)
        elif residuals[idx] >= exception_bar:
            exception_ids.append(idx)
        else:
            merge_ids.append(idx)

    return merge_ids, exception_ids, archive_ids
```

## 6. Coverage coreset 怎么选

### 6.1 v0 简单版：farthest-first k-center

比 k-medoids 更容易无依赖实现。

直觉：

1. 先选 response mass 最大的 node；
2. 每次选择离当前代表集合最远、且有一定 mass 的 node；
3. 直到达到预算。

```python
def select_representatives(fingerprints, mass, budget):
    f = l2_normalize(np.asarray(fingerprints), axis=1)
    n = f.shape[0]
    budget = min(budget, n)

    selected = [int(np.argmax(mass))]
    min_dist = 1.0 - (f @ f[selected[0]])

    while len(selected) < budget:
        # 兼顾 coverage gap 和 response mass
        score = min_dist * np.log1p(mass)
        score[selected] = -1.0
        next_idx = int(np.argmax(score))
        selected.append(next_idx)

        dist_to_new = 1.0 - (f @ f[next_idx])
        min_dist = np.minimum(min_dist, dist_to_new)

    return selected
```

这个实现不需要多个 lambda。`min_dist` 保多样性，`mass` 保检索需求，两者来自 response matrix 自身。

### 6.2 后续增强：facility-location greedy

如果 v0 有信号，再实现：

```text
maximize sum_i max_{c in C} sim(f_i, f_c) * mass_i
s.t. |C| <= budget
```

这更像 coverage objective，但第一版先用 k-center 足够。

## 7. Capsule builder

最小逻辑：

```python
def build_capsules(nodes, representative_indices, assignments, residuals, mass):
    capsules = []

    for local_rep_id, rep_idx in enumerate(representative_indices):
        member_indices = np.where(assignments == local_rep_id)[0].tolist()
        if rep_idx not in member_indices:
            member_indices.append(rep_idx)

        merge_ids, exception_ids, archive_ids = route_cluster_members(
            member_indices=member_indices,
            residuals=residuals,
            mass=mass,
        )

        # representative 必须保留，不进入 archive
        archive_ids = [i for i in archive_ids if i != rep_idx]
        exception_ids = [i for i in exception_ids if i != rep_idx]
        merge_ids = [i for i in merge_ids if i != rep_idx]

        capsules.append({
            "capsule_id": f"cap_{local_rep_id:04d}",
            "representative_id": nodes[rep_idx].node_id,
            "member_node_ids": [nodes[i].node_id for i in member_indices],
            "merge_node_ids": [nodes[i].node_id for i in merge_ids],
            "exception_node_ids": [nodes[i].node_id for i in exception_ids],
            "archive_node_ids": [nodes[i].node_id for i in archive_ids],
            "timestamp_span": [
                min(nodes[i].timestamp for i in member_indices),
                max(nodes[i].timestamp for i in member_indices),
            ],
            "entities": sorted({e for i in member_indices for e in nodes[i].entities}),
            "raw_pointers": [
                nodes[i].raw_pointer for i in member_indices
                if getattr(nodes[i], "raw_pointer", None)
            ],
        })

    return capsules
```

summary 可以先不做 LLM，总结为拼接字段：

```python
def simple_capsule_summary(nodes, merge_indices, max_items=5):
    texts = [nodes[i].text for i in merge_indices[:max_items]]
    return " / ".join(texts)
```

后续再换 LLM summarizer，并严格记录 summary token cost。

## 8. RecallFlow v0 主流程

```python
def recallflow_compress(nodes, probe_queries, embed_fn, budget, tau=0.1):
    node_embs = [n.embedding if n.embedding is not None else embed_fn(n.text) for n in nodes]
    query_embs = [embed_fn(q.text) for q in probe_queries]

    response, fingerprints, mass = compute_response_fingerprints(
        query_embs=query_embs,
        node_embs=node_embs,
        tau=tau,
    )

    representative_indices = select_representatives(
        fingerprints=fingerprints,
        mass=mass,
        budget=budget,
    )

    assignments, residuals = assign_to_representatives(
        fingerprints=fingerprints,
        representative_indices=representative_indices,
    )

    capsules = build_capsules(
        nodes=nodes,
        representative_indices=representative_indices,
        assignments=assignments,
        residuals=residuals,
        mass=mass,
    )

    diagnostics = {
        "response": response,
        "fingerprints": fingerprints,
        "mass": mass,
        "representative_indices": representative_indices,
        "assignments": assignments,
        "residuals": residuals,
    }

    return capsules, diagnostics
```

## 9. 实验脚本建议

### 9.1 最小命令形态

```bash
python code/evaluation/scripts/run_recallflow_locomo.py \
  --input data/locomo_subset.jsonl \
  --budget-ratio 0.5 \
  --max-probes 64 \
  --window-size 8 \
  --output results/recallflow_locomo_v0.jsonl
```

### 9.2 必须记录的字段

| 字段 | 说明 |
|---|---|
| `sample_id` | dialogue / session id |
| `budget_ratio` | retained memory budget |
| `num_nodes_before` | 压缩前 node 数 |
| `num_capsules_after` | 压缩后 capsule 数 |
| `num_exceptions` | exception nodes 数 |
| `num_archived` | archive / prune 数 |
| `num_probes` | probe queries 数 |
| `compression_latency_sec` | 压缩耗时 |
| `retrieval_latency_sec` | 检索耗时 |
| `qa_score` | QA 分数 |
| `evidence_recall_at_k` | 关键证据召回 |

## 10. Baseline 对照

第一轮至少做：

| 方法 | 说明 |
|---|---|
| no compression | 上界 |
| random | 随机保留同预算 nodes |
| recency | 保留最近 nodes |
| embedding k-center | 用 node embedding 选代表 |
| similarity pruning | StreamMeCo-like proxy |
| similarity merging | MemForest-like proxy |
| RecallFlow prune-only | 只保 representatives，不建 capsule |
| RecallFlow full | representatives + capsule + exception |

最关键对比：

> **RecallFlow full vs embedding k-center**  
> 如果赢，说明 response fingerprint 比普通语义相似度更贴近长期记忆 QA。

## 11. 风险和检查项

| 风险 | 检查方式 |
|---|---|
| probe 泄漏测试问题 | 保存 probe 文件，检查不含 test question / answer |
| probe 过多导致成本高 | 报告 `num_probes` 和 compression latency |
| response softmax 温度敏感 | 跑 `tau = 0.05 / 0.1 / 0.2` |
| capsule summary 引入额外信息 | v0 先不用 LLM summary，或固定 summary token cost |
| exception 太多导致预算失控 | 记录 exception 数，并强制总预算约束 |
| 多模态只是 caption 压缩 | MemEye 阶段必须保留 raw frame / image pointer |

## 12. 给合作者的最短实现路线

1. 写 `MemoryNode` / `ProbeQuery` / `MemoryCapsule` dataclass。
2. 从 LoCoMo 或 Mem0 输出统一 `memory_nodes.jsonl`。
3. 写规则版 `build_probe_queries()`。
4. 用同一个 embedding model 计算 node / probe embeddings。
5. 实现 `compute_response_fingerprints()`。
6. 实现 `select_representatives()`。
7. 实现 `build_capsules()`。
8. 跑 50% budget，对比 recency 和 embedding k-center。
9. 输出 budget-accuracy 曲线和 bad case。

第一版只要回答一个问题：

> **在同样节点预算下，response fingerprint 压缩是否比 embedding 相似度压缩更能保住 QA evidence？**
