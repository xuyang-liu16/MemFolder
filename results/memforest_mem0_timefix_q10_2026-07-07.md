# MemForest / Mem0 LoCoMo Time-Fix Check — 2026-07-07

Local-only MemForest runner was patched to ground Mem0 extraction against the LoCoMo session timestamp.

| Run | Store | Scope | F1 | BLEU1 | Containment |
| --- | --- | --- | ---: | ---: | ---: |
| original | `locomo_s0_full_add_b64` | sample0 q1-q10 | 0.1448 | 0.0977 | 1/10 |
| prompt-only answer rerun | `locomo_s0_full_add_b64` | sample0 q1-q10 | 0.1552 | 0.1044 | 1/10 |
| answer conflict-date masking | `locomo_s0_full_add_b64` | sample0 q1-q10 | 0.2284 | 0.1569 | 1/10 |
| time-fixed add prompt | `locomo_s0_3sess_timefix` | sample0 sessions 1-3, q1-q10 | 0.6288 | 0.4624 | 4/10 |

Conclusion: old full store is contaminated by Mem0 write-time current-date artifacts and should not be used as the formal baseline. Formal baseline stores should be rebuilt with timestamp-grounded `memory.add(..., prompt=...)`.

Environment caveat: current run is semantic-only Mem0 because `spacy` and `fastembed` are not installed.
