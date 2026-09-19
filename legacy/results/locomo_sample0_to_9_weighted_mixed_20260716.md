# LoCoMo Sample0-9 Weighted Results

Date: 2026-07-16 JST

Scope:
- Samples: `sample0` to `sample9`
- Metric pooling: weighted by official non-category-5 `n` per sample.
- `sample0`, `sample1`, and `sample2` use the 2026-07-14 full-grid versions, per experiment-control instruction.
- `sample3` to `sample9` use the completed relay/no-thinking result directories available in the MemForest evaluation output.
- `sample7` uses `evaluation_metrics_official_no_cat5_unique.json` because the raw QA file contains duplicate `question_id` values.
- Metrics are read from row-level `evaluation_metrics*.json` files and category 5 rows are filtered before aggregation.

## Weighted Average

Total official `n`: `1540`.

| Method | total n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|
| Full Context | 1540 | 0.7208 | 0.5161 | 0.4323 |
| MemForest keep70 | 1540 | 0.7052 | 0.5008 | 0.4233 |
| MemForest keep50 | 1540 | 0.7065 | 0.4956 | 0.4184 |
| MemForest keep30 | 1540 | 0.6916 | 0.4761 | 0.4009 |
| RecallFlow-NC keep70 | 1540 | 0.7110 | 0.5011 | 0.4242 |
| RecallFlow-NC keep50 | 1540 | 0.7136 | 0.4961 | 0.4169 |
| RecallFlow-NC keep30 | 1540 | 0.6831 | 0.4849 | 0.4079 |

## Per-Sample Results

### sample0

| Method | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|
| Full Context | 152 | 0.7697 | 0.5145 | 0.4344 |
| MemForest keep70 | 152 | 0.7566 | 0.4976 | 0.4298 |
| MemForest keep50 | 152 | 0.7237 | 0.4792 | 0.4173 |
| MemForest keep30 | 152 | 0.6908 | 0.4684 | 0.4046 |
| RecallFlow-NC keep70 | 152 | 0.7500 | 0.4841 | 0.4241 |
| RecallFlow-NC keep50 | 152 | 0.7632 | 0.4821 | 0.4123 |
| RecallFlow-NC keep30 | 152 | 0.6776 | 0.4493 | 0.3864 |

### sample1

| Method | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|
| Full Context | 81 | 0.8025 | 0.5989 | 0.4858 |
| MemForest keep70 | 81 | 0.7901 | 0.5850 | 0.4948 |
| MemForest keep50 | 81 | 0.7407 | 0.5432 | 0.4678 |
| MemForest keep30 | 81 | 0.7160 | 0.5443 | 0.4623 |
| RecallFlow-NC keep70 | 81 | 0.8148 | 0.5816 | 0.4897 |
| RecallFlow-NC keep50 | 81 | 0.7654 | 0.5345 | 0.4523 |
| RecallFlow-NC keep30 | 81 | 0.7531 | 0.5419 | 0.4477 |

### sample2

| Method | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|
| Full Context | 152 | 0.8421 | 0.6472 | 0.5416 |
| MemForest keep70 | 152 | 0.8289 | 0.6341 | 0.5425 |
| MemForest keep50 | 152 | 0.8158 | 0.6059 | 0.5214 |
| MemForest keep30 | 152 | 0.7895 | 0.5588 | 0.4720 |
| RecallFlow-NC keep70 | 152 | 0.8092 | 0.5969 | 0.5061 |
| RecallFlow-NC keep50 | 152 | 0.8026 | 0.5936 | 0.5014 |
| RecallFlow-NC keep30 | 152 | 0.8026 | 0.5773 | 0.4928 |

### sample3

| Method | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|
| Full Context | 199 | 0.6985 | 0.4273 | 0.3674 |
| MemForest keep70 | 199 | 0.7186 | 0.4314 | 0.3691 |
| MemForest keep50 | 199 | 0.7236 | 0.4448 | 0.3778 |
| MemForest keep30 | 199 | 0.7186 | 0.4327 | 0.3696 |
| RecallFlow-NC keep70 | 199 | 0.7085 | 0.4332 | 0.3684 |
| RecallFlow-NC keep50 | 199 | 0.7186 | 0.4353 | 0.3624 |
| RecallFlow-NC keep30 | 199 | 0.6834 | 0.4192 | 0.3555 |

### sample4

| Method | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|
| Full Context | 178 | 0.6798 | 0.5143 | 0.4215 |
| MemForest keep70 | 178 | 0.6629 | 0.5101 | 0.4234 |
| MemForest keep50 | 178 | 0.6910 | 0.5148 | 0.4191 |
| MemForest keep30 | 178 | 0.6742 | 0.4966 | 0.4128 |
| RecallFlow-NC keep70 | 178 | 0.6910 | 0.5268 | 0.4387 |
| RecallFlow-NC keep50 | 178 | 0.6742 | 0.5140 | 0.4236 |
| RecallFlow-NC keep30 | 178 | 0.6966 | 0.5122 | 0.4245 |

### sample5

| Method | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|
| Full Context | 123 | 0.3496 | 0.2825 | 0.2263 |
| MemForest keep70 | 123 | 0.3415 | 0.2684 | 0.2151 |
| MemForest keep50 | 123 | 0.3171 | 0.2590 | 0.2082 |
| MemForest keep30 | 123 | 0.3252 | 0.2516 | 0.1977 |
| RecallFlow-NC keep70 | 123 | 0.3333 | 0.2664 | 0.2137 |
| RecallFlow-NC keep50 | 123 | 0.3496 | 0.2834 | 0.2371 |
| RecallFlow-NC keep30 | 123 | 0.3496 | 0.2691 | 0.2182 |

### sample6

| Method | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|
| Full Context | 150 | 0.7933 | 0.6010 | 0.5126 |
| MemForest keep70 | 150 | 0.7133 | 0.5479 | 0.4657 |
| MemForest keep50 | 150 | 0.7133 | 0.5489 | 0.4665 |
| MemForest keep30 | 150 | 0.7267 | 0.5497 | 0.4657 |
| RecallFlow-NC keep70 | 150 | 0.7267 | 0.5497 | 0.4661 |
| RecallFlow-NC keep50 | 150 | 0.7267 | 0.5466 | 0.4675 |
| RecallFlow-NC keep30 | 150 | 0.7200 | 0.5452 | 0.4602 |

### sample7

| Method | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|
| Full Context | 191 | 0.7435 | 0.5414 | 0.4453 |
| MemForest keep70 | 191 | 0.7330 | 0.5165 | 0.4258 |
| MemForest keep50 | 191 | 0.7435 | 0.5252 | 0.4354 |
| MemForest keep30 | 191 | 0.7120 | 0.4775 | 0.3887 |
| RecallFlow-NC keep70 | 191 | 0.7435 | 0.5226 | 0.4283 |
| RecallFlow-NC keep50 | 191 | 0.7592 | 0.5461 | 0.4458 |
| RecallFlow-NC keep30 | 191 | 0.7016 | 0.5267 | 0.4310 |

### sample8

| Method | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|
| Full Context | 156 | 0.7051 | 0.5216 | 0.4447 |
| MemForest keep70 | 156 | 0.6987 | 0.5137 | 0.4394 |
| MemForest keep50 | 156 | 0.7692 | 0.5251 | 0.4400 |
| MemForest keep30 | 156 | 0.7308 | 0.5064 | 0.4313 |
| RecallFlow-NC keep70 | 156 | 0.7244 | 0.5317 | 0.4552 |
| RecallFlow-NC keep50 | 156 | 0.7564 | 0.5167 | 0.4363 |
| RecallFlow-NC keep30 | 156 | 0.6859 | 0.5101 | 0.4340 |

### sample9

| Method | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|
| Full Context | 158 | 0.7975 | 0.5282 | 0.4481 |
| MemForest keep70 | 158 | 0.7722 | 0.5138 | 0.4364 |
| MemForest keep50 | 158 | 0.7532 | 0.4919 | 0.4215 |
| MemForest keep30 | 158 | 0.7595 | 0.4735 | 0.4054 |
| RecallFlow-NC keep70 | 158 | 0.7785 | 0.5207 | 0.4540 |
| RecallFlow-NC keep50 | 158 | 0.7658 | 0.4893 | 0.4204 |
| RecallFlow-NC keep30 | 158 | 0.7215 | 0.4880 | 0.4180 |

## Source Directories

| Sample | Method | Directory | Metrics file | n |
|---:|---|---|---|---:|
| 0 | Full Context | `sample0_full_context_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 0 | MemForest keep70 | `sample0_memforest_keep70_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 0 | MemForest keep50 | `sample0_memforest_keep50_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 0 | MemForest keep30 | `sample0_memforest_keep30_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 0 | RecallFlow-NC keep70 | `sample0_recallflow_nc_response_merge_keep70_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 0 | RecallFlow-NC keep50 | `sample0_recallflow_nc_response_merge_keep50_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 0 | RecallFlow-NC keep30 | `sample0_recallflow_nc_response_merge_keep30_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 1 | Full Context | `sample1_full_context_fullgrid_20260714` | `evaluation_metrics.json` | 81 |
| 1 | MemForest keep70 | `sample1_memforest_keep70_fullgrid_20260714` | `evaluation_metrics.json` | 81 |
| 1 | MemForest keep50 | `sample1_memforest_keep50_fullgrid_20260714` | `evaluation_metrics.json` | 81 |
| 1 | MemForest keep30 | `sample1_memforest_keep30_fullgrid_20260714` | `evaluation_metrics.json` | 81 |
| 1 | RecallFlow-NC keep70 | `sample1_recallflow_nc_response_merge_keep70_fullgrid_20260714` | `evaluation_metrics.json` | 81 |
| 1 | RecallFlow-NC keep50 | `sample1_recallflow_nc_response_merge_keep50_fullgrid_20260714` | `evaluation_metrics.json` | 81 |
| 1 | RecallFlow-NC keep30 | `sample1_recallflow_nc_response_merge_keep30_fullgrid_20260714` | `evaluation_metrics.json` | 81 |
| 2 | Full Context | `sample2_full_context_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 2 | MemForest keep70 | `sample2_memforest_keep70_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 2 | MemForest keep50 | `sample2_memforest_keep50_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 2 | MemForest keep30 | `sample2_memforest_keep30_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 2 | RecallFlow-NC keep70 | `sample2_recallflow_nc_response_merge_keep70_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 2 | RecallFlow-NC keep50 | `sample2_recallflow_nc_response_merge_keep50_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 2 | RecallFlow-NC keep30 | `sample2_recallflow_nc_response_merge_keep30_fullgrid_20260714` | `evaluation_metrics.json` | 152 |
| 3 | Full Context | `sample3_full_context_relay_nothink_20260715` | `evaluation_metrics_official_no_cat5.json` | 199 |
| 3 | MemForest keep70 | `sample3_memforest_keep70_relay_nothink_20260714` | `evaluation_metrics_official_no_cat5.json` | 199 |
| 3 | MemForest keep50 | `sample3_memforest_keep50_relay_nothink_20260714` | `evaluation_metrics_official_no_cat5.json` | 199 |
| 3 | MemForest keep30 | `sample3_memforest_keep30_relay_nothink_20260714` | `evaluation_metrics_official_no_cat5.json` | 199 |
| 3 | RecallFlow-NC keep70 | `sample3_recallflow_nc_response_merge_keep70_relay_nothink_20260714` | `evaluation_metrics_official_no_cat5.json` | 199 |
| 3 | RecallFlow-NC keep50 | `sample3_recallflow_nc_response_merge_keep50_relay_nothink_r2_20260715` | `evaluation_metrics_official_no_cat5.json` | 199 |
| 3 | RecallFlow-NC keep30 | `sample3_recallflow_nc_response_merge_keep30_relay_nothink_r2_20260715` | `evaluation_metrics_official_no_cat5.json` | 199 |
| 4 | Full Context | `sample4_full_context_relay_nothink_20260715` | `evaluation_metrics_official_no_cat5.json` | 178 |
| 4 | MemForest keep70 | `sample4_memforest_keep70_relay_nothink_20260715` | `evaluation_metrics_official_no_cat5.json` | 178 |
| 4 | MemForest keep50 | `sample4_memforest_keep50_relay_nothink_20260715` | `evaluation_metrics_official_no_cat5.json` | 178 |
| 4 | MemForest keep30 | `sample4_memforest_keep30_relay_nothink_20260715` | `evaluation_metrics_official_no_cat5.json` | 178 |
| 4 | RecallFlow-NC keep70 | `sample4_recallflow_nc_response_merge_keep70_relay_nothink_20260715` | `evaluation_metrics_official_no_cat5.json` | 178 |
| 4 | RecallFlow-NC keep50 | `sample4_recallflow_nc_response_merge_keep50_relay_nothink_20260715` | `evaluation_metrics_official_no_cat5.json` | 178 |
| 4 | RecallFlow-NC keep30 | `sample4_recallflow_nc_response_merge_keep30_relay_nothink_20260715` | `evaluation_metrics_official_no_cat5.json` | 178 |
| 5 | Full Context | `sample5_full_context_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_relay_approved.json` | 123 |
| 5 | MemForest keep70 | `sample5_memforest_keep70_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_relay_approved.json` | 123 |
| 5 | MemForest keep50 | `sample5_memforest_keep50_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_relay_approved.json` | 123 |
| 5 | MemForest keep30 | `sample5_memforest_keep30_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_relay_approved.json` | 123 |
| 5 | RecallFlow-NC keep70 | `sample5_recallflow_nc_response_merge_keep70_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_relay_approved.json` | 123 |
| 5 | RecallFlow-NC keep50 | `sample5_recallflow_nc_response_merge_keep50_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_relay_approved.json` | 123 |
| 5 | RecallFlow-NC keep30 | `sample5_recallflow_nc_response_merge_keep30_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_relay_approved.json` | 123 |
| 6 | Full Context | `sample6_full_context_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 150 |
| 6 | MemForest keep70 | `sample6_memforest_keep70_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 150 |
| 6 | MemForest keep50 | `sample6_memforest_keep50_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 150 |
| 6 | MemForest keep30 | `sample6_memforest_keep30_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 150 |
| 6 | RecallFlow-NC keep70 | `sample6_recallflow_nc_response_merge_keep70_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 150 |
| 6 | RecallFlow-NC keep50 | `sample6_recallflow_nc_response_merge_keep50_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 150 |
| 6 | RecallFlow-NC keep30 | `sample6_recallflow_nc_response_merge_keep30_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 150 |
| 7 | Full Context | `sample7_full_context_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_unique.json` | 191 |
| 7 | MemForest keep70 | `sample7_memforest_keep70_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_unique.json` | 191 |
| 7 | MemForest keep50 | `sample7_memforest_keep50_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_unique.json` | 191 |
| 7 | MemForest keep30 | `sample7_memforest_keep30_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_unique.json` | 191 |
| 7 | RecallFlow-NC keep70 | `sample7_recallflow_nc_response_merge_keep70_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_unique.json` | 191 |
| 7 | RecallFlow-NC keep50 | `sample7_recallflow_nc_response_merge_keep50_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_unique.json` | 191 |
| 7 | RecallFlow-NC keep30 | `sample7_recallflow_nc_response_merge_keep30_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5_unique.json` | 191 |
| 8 | Full Context | `sample8_full_context_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 156 |
| 8 | MemForest keep70 | `sample8_memforest_keep70_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 156 |
| 8 | MemForest keep50 | `sample8_memforest_keep50_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 156 |
| 8 | MemForest keep30 | `sample8_memforest_keep30_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 156 |
| 8 | RecallFlow-NC keep70 | `sample8_recallflow_nc_response_merge_keep70_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 156 |
| 8 | RecallFlow-NC keep50 | `sample8_recallflow_nc_response_merge_keep50_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 156 |
| 8 | RecallFlow-NC keep30 | `sample8_recallflow_nc_response_merge_keep30_relay_nothink_side_20260715` | `evaluation_metrics_official_no_cat5.json` | 156 |
| 9 | Full Context | `sample9_full_context_relay_nothink_side_20260716` | `evaluation_metrics_official_no_cat5.json` | 158 |
| 9 | MemForest keep70 | `sample9_memforest_keep70_relay_nothink_side_20260716` | `evaluation_metrics_official_no_cat5.json` | 158 |
| 9 | MemForest keep50 | `sample9_memforest_keep50_relay_nothink_side_20260716` | `evaluation_metrics_official_no_cat5.json` | 158 |
| 9 | MemForest keep30 | `sample9_memforest_keep30_relay_nothink_side_20260716` | `evaluation_metrics_official_no_cat5.json` | 158 |
| 9 | RecallFlow-NC keep70 | `sample9_recallflow_nc_response_merge_keep70_relay_nothink_side_20260716` | `evaluation_metrics_official_no_cat5.json` | 158 |
| 9 | RecallFlow-NC keep50 | `sample9_recallflow_nc_response_merge_keep50_relay_nothink_side_20260716` | `evaluation_metrics_official_no_cat5.json` | 158 |
| 9 | RecallFlow-NC keep30 | `sample9_recallflow_nc_response_merge_keep30_relay_nothink_side_20260716` | `evaluation_metrics_official_no_cat5.json` | 158 |
