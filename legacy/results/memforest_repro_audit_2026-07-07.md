# MemForest Reproducibility Audit — 2026-07-07

## Conclusion

The previous bad temporal answers were not only caused by the custom diagnostic runner. Using the official `MemoryADD` path with `batch_size=2` and with `spacy`/`fastembed` enabled still produced current-year artifacts such as `July 6, 2026` for a LoCoMo session timestamped `8 May, 2023`.

Root cause: Mem0 2.0.3 stores `metadata.timestamp` in Qdrant, but its extraction prompt does not pass that timestamp as `Observation Date`; it defaults to the system date.

## Paper Alignment

From the uploaded MemForest paper:

| Item | Paper setting | Current server setting |
| --- | --- | --- |
| Mem0 LoCoMo baseline | All = 60.2 | not reproduced yet |
| Answer/eval model | GPT-4o-mini | Qwen3.6-plus relay |
| Embedding | text-embedding-3-small | Bailian text-embedding-v4 |
| Results | 3-run average | pending |

So our run can be a MemForest-style framework baseline, but it cannot be expected to numerically match the paper unless we switch to the same models.

## Code Audit

Formal runner should remain:

```bash
run_experiments.py -> src/memzero/add.py -> src/memzero/search.py
```

Do not use `run_mem0_dataset_subset.py` for final paper-aligned baseline; it is diagnostic.

Local patches are:

| File | Patch type | Rationale |
| --- | --- | --- |
| `run_experiments.py` | CLI params only | dataset/store/slice controls; defaults preserve official batch size |
| `src/memzero/local_memory.py` | API/store config | split relay chat from Bailian embedding; local store isolation |
| `src/memzero/add.py` | correctness/reliability | timestamp grounding; retry empty extractions; propagate speaker-thread failures |

## Environment

Installed and verified:

- `fastembed`
- `spacy`
- `en_core_web_sm`
- `Qdrant/bm25` cached via `HF_ENDPOINT=https://hf-mirror.com`

Run commands should unset offline flags:

```bash
env -u TRANSFORMERS_OFFLINE -u HF_HUB_OFFLINE HF_ENDPOINT=https://hf-mirror.com ...
```

## Current Blocker

Relay LLM returned repeated `503 Service Temporarily Unavailable`, so the post-fix smoke could not finish. Full baseline should wait until relay health is restored.
