# Coding Log: RecallFlow-URB Prune Keep70 QA on LoCoMo Sample0

Date: 2026-07-09

## Request

Run a RecallFlow-compressed QA result on LoCoMo sample0 so it can be compared with the existing full Mem0 and MemForest keep70 baselines.

## Actions

1. Copied the full sample0 Mem0 snapshot into a private store:
   `/mnt/disk1/memory-compression-v2/external/11318_MemForest_Efficient_Agen_Supplementary_Material/Mem0/evaluation/locomo_sample0_recallflow_urb_prune_keep70_20260709_qa`
2. Ran `RecallFlow_URB.py` with:
   - `--method recallflow_urb_prune_only`
   - `--keep-ratio 0.7`
   - `--tau 0.1`
   - `--start-idx 0 --end-idx 0`
3. Compression result:
   - sample0 nodes: `733 -> 513`
   - deleted: `220`
   - total `mem0` points after compression: `556`
   - total `mem0_entities` points after compression: `597`
4. Ran official Mem0 `search` QA with `top_k=30`, no graph, no filter.
5. Scored with `code.evaluation.scripts.score_locomo_qa_resumable` on 152 non-category-5 questions.

## Engineering Notes

`recallflow_urb_full --keep-ratio 0.7` was also tested as a compression pass, but it retained `630/733` sample0 nodes because exception keeps were added on top of representatives. That was not used for the main QA comparison because its final retention was around 86%, much higher than MemForest keep70.

QA initially timed out on category-4 question index 122 after 122 answers were saved. The run was resumed from the existing output file. To finish the remaining questions, `CHAT_ANSWER_MAX_TOKENS=256` and `CHAT_ANSWER_ENABLE_THINKING=false` were set. Retrieval and scoring settings were unchanged.

## Result

| split | n | full acc | MemForest acc | RecallFlow acc | RF-MF acc | full F1 | MemForest F1 | RecallFlow F1 | RF-MF F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| overall | 152 | 82.89 | 82.24 | 79.61 | -2.63 | 53.48 | 52.01 | 51.71 | -0.31 |
| 1 | 32 | 78.12 | 78.12 | 81.25 | +3.12 | 51.45 | 46.30 | 47.30 | +1.00 |
| 2 | 37 | 86.49 | 89.19 | 86.49 | -2.70 | 64.63 | 61.45 | 66.13 | +4.68 |
| 3 | 13 | 92.31 | 84.62 | 76.92 | -7.69 | 31.93 | 35.29 | 29.72 | -5.57 |
| 4 | 70 | 81.43 | 80.00 | 75.71 | -4.29 | 52.51 | 52.73 | 50.18 | -2.56 |

Primary result note:
`results/locomo_sample0_recallflow_urb_prune_keep70_vs_baselines_20260709.md`
