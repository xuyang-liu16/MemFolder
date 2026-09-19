# LoCoMo sample0 baseline metrics run

Date: 2026-07-08

Goal:
- Score the already-generated Mem0 baseline QA output for LoCoMo sample0.
- Use the sample0 snapshot QA output and avoid touching the live Qdrant store.

Input QA:
- `/mnt/disk1/memory-compression-v2/external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample0_eval_snapshot_dashscopechat/locomo_baseline_qwen36_strictjson_full10_v4_sample0_qa_snapshot_mem0_results_top_30_filter_False_graph_False.json`
- Non-category-5 QA count: 152
- Category counts: `1=32`, `2=37`, `3=13`, `4=70`

Dependency notes:
- Official `evals.py` imports `metrics.utils`, which calls `nltk.download("punkt")` and `nltk.download("wordnet")` at import time.
- `punkt` and `punkt_tab` were already present under `/root/nltk_data`.
- `wordnet` was downloaded manually as `wordnet.zip`, installed under `/root/nltk_data/corpora`, and verified with `nltk.data.find("corpora/wordnet")`.
- Even after local installation, direct `nltk.download("wordnet")` can still hang while checking the remote downloader index. A wrapper was added at `code/evaluation/scripts/run_memforest_evals_with_local_deps.py` to use local NLTK resources without modifying the MemForest source.
- `sentence-transformers/all-MiniLM-L6-v2` is attempted at import time by `metrics.utils`, but it is not used for the LoCoMo BLEU/F1/LLM-judge path. With offline mode it fails fast and the official helper sets `sentence_model=None`.

Official eval attempt:
- Relay/qwen3.6-plus judge failed with HTTP 503.
- DashScope/qwen3.6-27b judge reached the API, but the official `metrics/llm_judge.py` JSON parsing path is not compatible with this backend response shape and raised `TypeError: string indices must be integers, not 'str'`.

Completed scoring path:
- Used `code/evaluation/scripts/score_locomo_qa_resumable.py`.
- This keeps the MemForest LoCoMo metric set: BLEU-1, token F1, and LLM judge accuracy.
- Judge backend: DashScope OpenAI-compatible chat.
- Judge model: `qwen3.6-27b`.
- Output metrics JSON: `results/locomo_sample0_mem0_baseline_metrics_dashscope_qwen36_resumable.json`
- Output summary JSON: `results/locomo_sample0_mem0_baseline_metrics_dashscope_qwen36_summary.json`
- Completed: 152 / 152.

Results:

| Category | Count | LLM accuracy | BLEU-1 | F1 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 32 | 78.1% | 46.3% | 52.9% |
| 2 | 37 | 89.2% | 57.6% | 65.4% |
| 3 | 13 | 61.5% | 12.5% | 21.0% |
| 4 | 70 | 82.9% | 46.7% | 54.9% |
| Overall | 152 | 81.6% | 46.3% | 54.1% |

Next:
- For strict official-script reproducibility, patch or wrap `metrics/llm_judge.py` JSON parsing so DashScope-compatible JSON strings are handled, while preserving the judge prompt and labels.
- For RecallFlow comparison, build compressed-memory QA outputs for sample0 and score them with the same judge backend and script.
