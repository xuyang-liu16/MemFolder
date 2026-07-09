# MemForest/Mem0 Qwen3.6 Time-Fix Smoke — 2026-07-07

## Setup

| Item | Value |
| --- | --- |
| Runner | official `run_experiments.py` / `MemoryADD` / `MemorySearch` path |
| Chat model | DashScope `qwen3.6-27b` |
| Embedding | DashScope `text-embedding-v4` |
| Dataset scope | LoCoMo sample0, session1 |
| Batch size | 2 |
| Store | `locomo_dashscope_qwen36_s0_s1_b2_timefix` |

## Write Check

Extracted memories now use the session timestamp correctly:

| Memory | Timestamp |
| --- | --- |
| Caroline attended a LGBTQ support group on May 7, 2023 | 1:56 pm on 8 May, 2023 |
| Melanie painted a lake sunrise in 2022 | 1:56 pm on 8 May, 2023 |

Bad current-year artifacts: `0` for both `Caroline_0` and `Melanie_0`.

## QA Check

| Question | Gold | Response |
| --- | --- | --- |
| When did Caroline go to the LGBTQ support group? | 7 May 2023 | May 7, 2023 |
| When did Melanie paint a sunrise? | 2022 | 2022 |
| What fields would Caroline be likely to pursue in her educaton? | Psychology, counseling certification | Counseling or mental health |

Conclusion: the timestamp-grounding fix is working on the official Mem0 path.
