# LoCoMo sample0 MemForest keep70 comparison

Date: 2026-07-08

Baseline:
- Method: Mem0, uncompressed.
- Store: `locomo_baseline_qwen36_strictjson_full10_v4_sample0_qa_snapshot`
- Memory nodes: 733
- QA count: 152 non-category-5 questions
- QA setting: `top_30_filter_False_graph_False`
- Judge: DashScope OpenAI-compatible `qwen3.6-27b`

MemForest compressed:
- Method: official MemForest compression.
- Store: `locomo_baseline_qwen36_strictjson_full10_v4_sample0_memforest_keep70`
- Memory nodes: 529
- Retention vs baseline: 72.2%
- QA count: 152 non-category-5 questions
- QA setting: `top_30_filter_False_graph_False`
- Judge: DashScope OpenAI-compatible `qwen3.6-27b`

| Category | Count | Baseline Acc | MemForest Acc | Delta Acc | Baseline B1 | MemForest B1 | Delta B1 | Baseline F1 | MemForest F1 | Delta F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 32 | 78.1% | 53.1% | -25.0 pp | 46.3% | 40.5% | -5.8 pp | 52.9% | 42.9% | -10.0 pp |
| 2 | 37 | 89.2% | 89.2% | +0.0 pp | 57.6% | 47.5% | -10.1 pp | 65.4% | 59.6% | -5.8 pp |
| 3 | 13 | 61.5% | 69.2% | +7.7 pp | 12.5% | 23.3% | +10.8 pp | 21.0% | 21.9% | +0.9 pp |
| 4 | 70 | 82.9% | 78.6% | -4.3 pp | 46.7% | 42.4% | -4.3 pp | 54.9% | 49.8% | -5.1 pp |
| Overall | 152 | 81.6% | 75.0% | -6.6 pp | 46.3% | 41.6% | -4.7 pp | 54.1% | 48.3% | -5.8 pp |

Interpretation:
- Official MemForest keep70 reduced sample0 memory nodes from 733 to 529.
- Overall LLM-judge accuracy dropped from 81.6% to 75.0%.
- Category 1 was the largest regression, dropping 25.0 pp in judge accuracy.
- Category 3 improved on judge accuracy and BLEU-1, but it has only 13 questions, so this should be treated as a small-sample signal.
- Category 2 preserved judge accuracy exactly, though lexical overlap metrics decreased.
