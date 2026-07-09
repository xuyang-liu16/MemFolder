# MemForest sample0 keep70 comparison

Date: 2026-07-08

Task:
- Compare LoCoMo sample0 uncompressed Mem0 baseline against official MemForest compression.

Important note:
- A MemForest keep70 compressed sample0 store and QA/metrics outputs already existed under the MemForest evaluation directory.
- I did not rerun the full merge pass because it would repeat about two hundred LLM merge/embedding calls.
- I verified the existing compressed store and metrics before using them for comparison.

Compressed store:
- `/mnt/disk1/memory-compression-v2/external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/locomo_baseline_qwen36_strictjson_full10_v4_sample0_memforest_keep70`

Compressed QA output:
- `/mnt/disk1/memory-compression-v2/external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample0_memforest_keep70_dashscopechat/locomo_baseline_qwen36_strictjson_full10_v4_sample0_memforest_keep70_mem0_results_top_30_filter_False_graph_False.json`

Compressed metrics:
- `/mnt/disk1/memory-compression-v2/external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/results/sample0_memforest_keep70_dashscopechat/locomo_baseline_qwen36_strictjson_full10_v4_sample0_memforest_keep70_eval_metrics.json`

Validation:
- Baseline exported sample0 memory nodes: 733.
- MemForest keep70 exported sample0 memory nodes: 529.
- Retention: 72.2%.
- Compressed metrics items: 152.
- Category counts: `1=32`, `2=37`, `3=13`, `4=70`.
- Empty responses: 0.
- Missing metric fields: 0.

Comparison summary:
- Baseline overall: accuracy 81.6%, BLEU-1 46.3%, F1 54.1%.
- MemForest keep70 overall: accuracy 75.0%, BLEU-1 41.6%, F1 48.3%.
- Overall delta: accuracy -6.6 pp, BLEU-1 -4.7 pp, F1 -5.8 pp.

Shareable result:
- `results/locomo_sample0_memforest_keep70_comparison.md`
