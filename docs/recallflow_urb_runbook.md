# RecallFlow-URB P0 实验运行手册

> 读者：专门执行实验的 Coding / Experiment Agent  
> 当前目标：准备并运行 RecallFlow-URB P0 压缩诊断实验  
> 工作目录：`/mnt/disk1/memory-compression-v2`  
> 配套方法协议：`docs/recallflow_urb_experiment_protocol.md`

## 1. 一屏结论

本 runbook 不是方法设计文档，而是执行手册。实验 agent 的任务是：

| 顺序 | 任务 | 成功产物 |
|---:|---|---|
| 1 | 确认代码入口是否已经补齐 | `code/compression/urb.py`、`run_recallflow_urb_diagnostics.py`、`test_urb_smoke.py` 存在并可运行 |
| 2 | 准备 LoCoMo sample0 的 Mem0 memory nodes | `external/rf_inputs/locomo_sample0_mem0_nodes.jsonl` |
| 3 | 跑 P0 三个方法 | `embedding_kcenter`、`recallflow_urb_prune_only`、`recallflow_urb_full` |
| 4 | 产出诊断结果 | `results/recallflow_urb_p0_locomo_sample0.jsonl` 和 `external/rf_outputs/diagnostics/locomo_0/*.json` |
| 5 | 做验收与记录 | smoke tests 通过；no-leakage audit 通过；coordination log 更新 |

P0 只做压缩诊断，不跑 QA、不调用 judge、不读取 LoCoMo 的 question / answer / evidence 字段。

## 2. 当前仓库状态判断

先进入工作目录：

```bash
cd /mnt/disk1/memory-compression-v2
```

运行：

```bash
find code/compression code/evaluation/scripts code/tests_run -maxdepth 2 -type f | sort
```

P0 完整运行需要以下文件存在：

| 必需文件 | 作用 |
|---|---|
| `code/compression/urb.py` | 固定 Universal Recall Basis、centroid/cache、variants |
| `code/compression/recallflow.py` | `recallflow_compress_with_urb` 或等价入口 |
| `code/evaluation/scripts/run_recallflow_urb_diagnostics.py` | P0 主运行脚本 |
| `code/evaluation/scripts/run_recallflow_urb_stability.py` | wording stability ablation，P0 后可跑 |
| `code/tests_run/test_urb_smoke.py` | URB smoke tests |

如果缺失，先按 `docs/recallflow_urb_experiment_protocol.md` 的第 9、16、17 节补齐实现。不要用旧的 `run_recallflow_locomo.py` 代替 URB P0，因为旧脚本走的是原 RecallFlow probe pipeline，不是固定 URB。

## 3. 不可违反的实验边界

| 边界 | 要求 |
|---|---|
| 压缩对象 | Mem0 生成的 memory items，不是原始 dialogue turns |
| Probe / basis 来源 | 固定 URB bank；不能从 test questions / gold answers / evidence 生成 |
| `tau` | 固定 `0.1`，P0 不调参 |
| Summary | RecallFlow v0 使用 `simple_capsule_summary`，不调用 LLM summary |
| P0 评测 | 只做压缩诊断，不做 QA score |
| API key | 只通过环境变量注入，不写入 docs/results/log |
| 提交范围 | 不提交 `external/`、datasets、models、`.env`、外部 baseline repo 全量 |

## 4. 环境准备

### 4.1 Python 环境

优先使用已有 MemForest 环境，因为它已经验证过 Mem0、Qdrant、OpenAI-compatible client 可用：

```bash
/root/miniconda/envs/memforest/bin/python -V
/root/miniconda/envs/memforest/bin/python -c "import numpy, qdrant_client, openai; print('ok')"
```

如果只是跑本仓库 smoke tests，也可以用当前 shell 的 Python，但正式实验请在 log 里写清楚使用的是哪个 Python：

```bash
which python
python -V
```

长时间 Mem0/MemForest 运行建议用：

```bash
/root/miniconda/envs/memforest/bin/python -u ...
```

不要优先用 `conda run -n memforest ...` 跑长任务，因为它会缓冲输出，不利于监控。

### 4.2 API 环境变量

P0 只需要 embedding。设置：

```bash
export DASHSCOPE_API_KEY="<填写百炼/ DashScope embedding key>"
export EMBEDDING_MODEL="text-embedding-v4"
export EMBEDDING_DIM="1024"
```

后续完整 QA 才需要 relay chat model：

```bash
export RELAY_BASE_URL="<relay base url>"
export RELAY_API_KEY="<relay api key>"
export CHAT_MODEL="qwen3.6-plus"
```

不要把真实 key 写进任何 markdown、JSONL、coordination log 或 result summary。

### 4.3 目录准备

```bash
mkdir -p external/rf_inputs
mkdir -p external/rf_outputs/diagnostics/locomo_0
mkdir -p external/cache/urb
mkdir -p results
```

这些 `external/` 路径是本地实验缓存和大文件位置，不提交。

## 5. 输入数据准备

### 5.1 P0 标准输入

标准输入路径：

```text
external/rf_inputs/locomo_sample0_mem0_nodes.jsonl
```

每行一条 `MemoryNode` JSON。最低字段：

```json
{
  "node_id": "locomo_0_memory_000001",
  "text": "Caroline plans to attend the event on May 7, 2023.",
  "timestamp": 1683440000.0,
  "embedding": [0.001, 0.002],
  "entities": [],
  "events": [],
  "modality": "text",
  "source": {
    "dataset": "LoCoMo",
    "sample_id": "locomo_0",
    "point_id": "optional_qdrant_point_id"
  },
  "raw_pointer": "optional"
}
```

禁止字段：

```text
question
questions
qa
answer
answers
gold
gold_answer
evidence
supporting_facts
```

如果输入 JSONL 带有这些字段，P0 loader 必须报错或忽略；推荐默认报错。

### 5.2 从现有 Mem0 store 导出

当前 MemForest/Mem0 代码位于：

```text
external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/
```

已经出现过的可参考 store：

```text
external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/locomo_baseline_qwen36_strictjson_full10_v4/
external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/locomo_s0_3sess_q10_timefix/
```

优先使用 time-fixed 的 Mem0 store。原因：旧的 `locomo_s0_full_add_b64` 曾出现 2026 当前日期污染，不适合作为正式 baseline。

如果导出脚本尚未实现，实验 agent 需要补一个只读导出器，逻辑如下：

1. 打开 Mem0/Qdrant store。
2. 只读取 point id、payload memory text、metadata timestamp、vector embedding。
3. 转成 `MemoryNode` JSONL。
4. 不读取 LoCoMo QA/gold/evidence。

导出后的检查命令：

```bash
test -s external/rf_inputs/locomo_sample0_mem0_nodes.jsonl
wc -l external/rf_inputs/locomo_sample0_mem0_nodes.jsonl
head -n 1 external/rf_inputs/locomo_sample0_mem0_nodes.jsonl
```

### 5.3 输入 sanity check

运行一个轻量检查，确认没有泄漏字段、文本非空、embedding 维度一致：

```bash
python - <<'PY'
import json
from pathlib import Path

path = Path("external/rf_inputs/locomo_sample0_mem0_nodes.jsonl")
bad_fields = {"question", "questions", "qa", "answer", "answers", "gold", "gold_answer", "evidence", "supporting_facts"}
dims = set()
n = 0
for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
    if not line.strip():
        continue
    row = json.loads(line)
    forbidden = bad_fields & set(row)
    if forbidden:
        raise SystemExit(f"forbidden fields at line {line_no}: {sorted(forbidden)}")
    if not row.get("node_id") or not row.get("text"):
        raise SystemExit(f"missing node_id/text at line {line_no}")
    emb = row.get("embedding")
    if emb is not None:
        dims.add(len(emb))
    n += 1
print({"num_nodes": n, "embedding_dims": sorted(dims)})
PY
```

期望：

```text
num_nodes > 0
embedding_dims == [1024]
```

如果 `embedding_dims` 为空，说明输入没有 embedding。P0 runner 可以补 embedding，但补完后必须另存：

```text
external/rf_inputs/locomo_sample0_mem0_nodes.embedded.text-embedding-v4.jsonl
```

## 6. Smoke Tests

先跑已有基础测试：

```bash
python -m pytest code/tests_run/test_compression_smoke.py
python -m pytest code/tests_run/test_baselines_smoke.py
```

实现 URB 后必须跑：

```bash
python -m pytest code/tests_run/test_urb_smoke.py
```

`test_urb_smoke.py` 至少应覆盖：

| 测试 | 期望 |
|---|---|
| URB bank count | family 数 = 10，总 paraphrase 数 = 40 |
| basis hash | 同一 bank 多次 hash 完全一致 |
| centroid shape | `[10, 1024]` |
| centroid norm | 每行 L2 norm 接近 1 |
| response shape | `A.shape == [10, num_nodes]` |
| prune-only budget | retained 数严格等于 budget |
| determinism | 同 seed representative IDs 一致 |

## 7. 运行 P0 压缩诊断

### 7.1 主命令

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

如果输入缺 embedding，并且 runner 支持自动补 embedding，使用：

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
  --fill-missing-embeddings \
  --embedded-output external/rf_inputs/locomo_sample0_mem0_nodes.embedded.text-embedding-v4.jsonl \
  --output results/recallflow_urb_p0_locomo_sample0.jsonl \
  --diagnostics-dir external/rf_outputs/diagnostics/locomo_0
```

### 7.2 输出文件

成功后应该看到：

```bash
ls -lh results/recallflow_urb_p0_locomo_sample0.jsonl
ls -lh external/rf_outputs/diagnostics/locomo_0/
ls -lh external/cache/urb/
```

期望至少包含：

```text
results/recallflow_urb_p0_locomo_sample0.jsonl
external/rf_outputs/diagnostics/locomo_0/embedding_kcenter_budget50_seed0.json
external/rf_outputs/diagnostics/locomo_0/recallflow_urb_prune_only_budget50_seed0.json
external/rf_outputs/diagnostics/locomo_0/recallflow_urb_full_budget50_seed0.json
external/cache/urb/urb_v0_text-embedding-v4_1024.npy
external/cache/urb/urb_v0_text-embedding-v4_1024.meta.json
```

## 8. P0 结果验收

### 8.1 JSONL 行数和方法

```bash
python - <<'PY'
import json
from pathlib import Path

path = Path("results/recallflow_urb_p0_locomo_sample0.jsonl")
rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
print("num_rows", len(rows))
for r in rows:
    print(r["method"], {
        "budget": r.get("budget"),
        "before": r.get("num_nodes_before"),
        "after": r.get("num_nodes_after"),
        "diag": r.get("diagnostics_path"),
    })
PY
```

期望至少有 3 行：

```text
embedding_kcenter
recallflow_urb_prune_only
recallflow_urb_full
```

### 8.2 预算检查

```bash
python - <<'PY'
import json
from pathlib import Path

rows = [json.loads(x) for x in Path("results/recallflow_urb_p0_locomo_sample0.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
for r in rows:
    method = r["method"]
    budget = r["budget"]
    nrep = r.get("num_representatives")
    after = r.get("num_nodes_after")
    if method in {"embedding_kcenter", "recallflow_urb_prune_only"} and after != budget:
        raise SystemExit(f"{method}: num_nodes_after={after} != budget={budget}")
    if method == "recallflow_urb_full" and nrep != budget:
        raise SystemExit(f"{method}: num_representatives={nrep} != budget={budget}")
print("budget checks passed")
PY
```

解释：

| 方法 | 预算要求 |
|---|---|
| `embedding_kcenter` | `num_nodes_after == budget` |
| `recallflow_urb_prune_only` | `num_nodes_after == budget` |
| `recallflow_urb_full` | `num_representatives == budget`；`num_nodes_after` 可因 exceptions 大于 budget |

### 8.3 URB response 检查

检查 detailed diagnostics：

```bash
python - <<'PY'
import json
from pathlib import Path

detail = Path("external/rf_outputs/diagnostics/locomo_0/recallflow_urb_prune_only_budget50_seed0.json")
d = json.loads(detail.read_text(encoding="utf-8"))
print({
    "response_shape": d.get("response_shape"),
    "fingerprint_shape": d.get("fingerprint_shape"),
    "num_mass": len(d.get("mass", [])),
    "num_assignments": len(d.get("assignments", [])),
    "num_residuals": len(d.get("residuals", [])),
    "num_reps": len(d.get("representative_ids", [])),
    "leakage_audit": d.get("leakage_audit"),
})
PY
```

期望：

```text
response_shape[0] == 10
fingerprint_shape[1] == 10
mass / assignments / residuals 长度等于 num_nodes_before
leakage_audit 中 compression_reads_qa/gold/evidence 均为 false
```

### 8.4 确定性检查

用同样 seed 再跑一次到临时输出：

```bash
python -m code.evaluation.scripts.run_recallflow_urb_diagnostics \
  --input-memory-nodes external/rf_inputs/locomo_sample0_mem0_nodes.jsonl \
  --methods recallflow_urb_prune_only \
  --budget-ratio 0.5 \
  --embedding-model text-embedding-v4 \
  --embedding-dim 1024 \
  --basis-version urb_v0 \
  --tau 0.1 \
  --seed 0 \
  --output /tmp/recallflow_urb_determinism_check.jsonl \
  --diagnostics-dir /tmp/recallflow_urb_determinism_diag
```

对比 representative IDs：

```bash
python - <<'PY'
import json
from pathlib import Path

a = json.loads(Path("external/rf_outputs/diagnostics/locomo_0/recallflow_urb_prune_only_budget50_seed0.json").read_text())
b = json.loads(Path("/tmp/recallflow_urb_determinism_diag/recallflow_urb_prune_only_budget50_seed0.json").read_text())
assert a["representative_ids"] == b["representative_ids"]
print("determinism passed")
PY
```

### 8.5 与 embedding k-center 的差异

P0 不要求 sample0 必须不同，但要记录：

```bash
python - <<'PY'
import json
from pathlib import Path

base = Path("external/rf_outputs/diagnostics/locomo_0")
a = json.loads((base / "embedding_kcenter_budget50_seed0.json").read_text())
b = json.loads((base / "recallflow_urb_prune_only_budget50_seed0.json").read_text())
sa, sb = set(a["representative_ids"]), set(b["representative_ids"])
jaccard = len(sa & sb) / len(sa | sb) if sa or sb else 1.0
print({"representative_jaccard": round(jaccard, 4), "same_set": sa == sb})
PY
```

如果 `same_set=true`，不要改算法强行制造差异；在 log 中记录，并在更多样本上复查。

## 9. 可选：URB wording stability

P0 主流程通过后，跑 wording ablation：

```bash
for variant in urb_centroid urb_single_first urb_all_40_no_pool urb_random_text; do
  python -m code.evaluation.scripts.run_recallflow_urb_stability \
    --input-memory-nodes external/rf_inputs/locomo_sample0_mem0_nodes.jsonl \
    --variant "$variant" \
    --budget-ratio 0.5 \
    --embedding-model text-embedding-v4 \
    --embedding-dim 1024 \
    --seed 0 \
    --output results/recallflow_urb_stability_locomo_sample0.jsonl \
    --diagnostics-dir external/rf_outputs/diagnostics/locomo_0/stability
done
```

结果检查：

```bash
python - <<'PY'
import json
from pathlib import Path
path = Path("results/recallflow_urb_stability_locomo_sample0.jsonl")
for line in path.read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    print(r["variant"], {
        "overlap": r.get("representative_overlap"),
        "mass_spearman": r.get("mass_spearman"),
        "latency": r.get("compression_latency_sec"),
    })
PY
```

## 10. 可选：后续 P1/P2/P3 顺序

不要跳过 P0 直接跑完整 QA。推荐顺序：

| 阶段 | 输入 | 输出 | 是否读取 QA/evidence |
|---|---|---|---|
| P0 | LoCoMo sample0 Mem0 nodes | 压缩诊断 | 否 |
| P1 | LoCoMo sample0/full Mem0 store | compressed store / plan | 否 |
| P2 | P1 compressed plan + evidence labels | evidence recall proxy | 只在压缩后评估时读取 |
| P3 | materialized compressed stores | full QA result | 只在压缩后评估时读取 |

P2/P3 的原则：同一 QA 集、同一 answer model、同一 judge、同一 retrieval top-k、同一 prompt，唯一变量是 memory compression policy。

## 11. 结果记录模板

实验结束后，在对应 coordination log 追加：

```text
## 2026-07-08 HH:MM CST — RecallFlow-URB P0 LoCoMo sample0

- Code commit/status:
- Python/env:
- Input nodes:
- Embedding model/dim:
- Command:
- Output JSONL:
- Diagnostics dir:
- Smoke tests:
- Methods:
  - embedding_kcenter: before=?, after=?, latency=?
  - recallflow_urb_prune_only: before=?, after=?, latency=?
  - recallflow_urb_full: before=?, after=?, representatives=?, retained_after_exceptions=?, exceptions=?, latency=?
- No-leakage audit:
- Determinism check:
- Representative overlap with embedding_kcenter:
- Issues / TODO:
```

可分享的小结写到：

```text
results/recallflow_urb_p0_locomo_sample0_summary_YYYY-MM-DD.md
```

不要把 API key、完整 dataset、完整 Qdrant store、`external/` 大文件写进 `results/`。

## 12. 常见问题

| 问题 | 可能原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError: code.compression` | 没在仓库根目录运行，或 Python path 不对 | `cd /mnt/disk1/memory-compression-v2` 后重跑 |
| 找不到 `run_recallflow_urb_diagnostics.py` | URB P0 入口尚未实现 | 先按 protocol 实现，不要用旧 LoCoMo runner 替代 |
| embedding dim 不是 1024 | 用错 embedding model 或旧 store vector | P0 固定 `text-embedding-v4` + 1024；必要时重新补 embedding |
| DashScope embedding 失败 | key 未导出、网络/API 限流、模型名写错 | 检查 `DASHSCOPE_API_KEY`、重试、小批量 |
| `tau` 被传成非 0.1 | 命令或默认值错误 | P0 直接报错，保持 `tau=0.1` |
| full 方法 after > budget | exception keep 导致 | 这是允许的；记录 `num_representatives` 和 `num_retained_after_exceptions` |
| JSONL 中出现 QA/evidence 字段 | 输入导出器读了 benchmark example 而不是 memory item | 停止实验，修正导出器 |
| `conda run` 长时间无输出 | 输出缓冲 | 改用 `/root/miniconda/envs/memforest/bin/python -u` |

## 13. 最终交付物

P0 完成时，至少交付：

| 类型 | 路径 |
|---|---|
| 小结果 JSONL | `results/recallflow_urb_p0_locomo_sample0.jsonl` |
| 小结果 summary | `results/recallflow_urb_p0_locomo_sample0_summary_YYYY-MM-DD.md` |
| 详细诊断 | `external/rf_outputs/diagnostics/locomo_0/*.json` |
| URB cache | `external/cache/urb/urb_v0_text-embedding-v4_1024.*` |
| 输入 nodes | `external/rf_inputs/locomo_sample0_mem0_nodes.jsonl` |
| coordination log | `coordination/experiments/work_log_experiments_<tool>.md` |

最终回复用户时，报告：

```text
1. 使用了哪个 input store / nodes 文件
2. 三个方法是否都跑通
3. 每个方法 before/after/budget/latency
4. no-leakage audit 是否通过
5. smoke tests 是否通过
6. 结果文件路径
7. 任何影响解释的 caveat
```
