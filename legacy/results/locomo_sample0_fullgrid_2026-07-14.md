# LoCoMo Sample0 Full-Grid Results

Date: 2026-07-14

Scope:
- Dataset: `dataset/locomo10.json`
- Sample: `sample0`
- Evaluation source: 2026-07-14 full-grid run.
- Official comparison scope: category 5 filtered out, `n=152`.

## Evaluation

| Method | Budget | n | LLM Acc | F1 | BLEU1 |
|---|---:|---:|---:|---:|---:|
| Full Context | - | 152 | 0.7697 | 0.5145 | 0.4344 |
| MemForest | keep70 | 152 | 0.7566 | 0.4976 | 0.4298 |
| MemForest | keep50 | 152 | 0.7237 | 0.4792 | 0.4173 |
| MemForest | keep30 | 152 | 0.6908 | 0.4684 | 0.4046 |
| RecallFlow-NC | keep70 | 152 | 0.7500 | 0.4841 | 0.4241 |
| RecallFlow-NC | keep50 | 152 | 0.7632 | 0.4821 | 0.4123 |
| RecallFlow-NC | keep30 | 152 | 0.6776 | 0.4493 | 0.3864 |

## Source

This table is the sample0 slice used by `results/locomo_sample0_to_9_weighted_mixed_20260716.md`.
Per experiment-control instruction, sample0 uses the 2026-07-14 full-grid version rather than later reruns.
