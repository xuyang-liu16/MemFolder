---
name: memfolder-exp
description: Set up, run, compare, and inspect MemFolder memory-compression experiments on LoCoMo, LongMemEval, PersonaMem, and M3 using the repository's loaders and CLI. Use for environment checks, existing memory stores, RecordFolder or ContextFolder evaluation, and baseline comparisons.
---

# MemFolder experiments

Use the existing CLI and plugins. Locate the checkout containing `pyproject.toml`,
`src/__main__.py`, and `examples/experiments/`. All paths below are
relative to that root. An installed skill can live elsewhere. If the checkout
is missing and the user requests a run from `xuyang-liu16/MemFolder`, clone
`https://github.com/xuyang-liu16/MemFolder.git` into a fresh directory and continue.
For an existing local checkout, use the path supplied by the user.

Read `README.md`, set up the environment below, and run `python -m memfolder --help`.
Read [experiment-config.md](references/experiment-config.md) when configuring
model-backed evaluation or an existing memory bank.
Inspect `examples/recipes/` for method variants and use the CLI's `case` command
to inspect a saved question.

For the README's one-line LoCoMo pilot, use `conv-26`, a retained-node ratio
of `0.5`, and the RecordFolder and ContextFolder templates. Reuse the user's
selected memory store and configured model services. Otherwise, start with
`history-initializer` and resolve the missing service settings with the user.
Download the documented LoCoMo input as part of the requested run, prepare both
configurations, and follow the authorization check below before model calls.
Explicit user choices take precedence over these pilot defaults.

## Resolve the experiment

Identify whether the user wants an environment check, a new benchmark run, or
reproduction of a particular paper result. Resolve the following from their
request and existing configuration:

- Dataset version, split, selected sample IDs, and data paths.
- Original memory store or history initializer, framework, and sample mapping.
- Method recipe, retained-record ratio, seed, and `once` or `repeat` mode.
- Chat, grounding, embedding, and judge models, revisions, endpoints, and key
  environment variables. Resolve tokenizer identity separately.
- Retriever, top-k, context builder, answer prompt, scoring metric, and whether
  to evaluate the original memory.
- A fresh output directory, capture policy, and available compute or API budget.

Ask only for missing choices that affect the experiment. Show the planned
configuration and call estimate before paid inference unless already authorized.
Setup alone does not authorize model calls, model-weight downloads, or full
benchmark downloads. Never print credentials or write them into configuration.
The built-in `compatible-http` service reads its configured key environment
variable even for a local endpoint.

There is no `--dry-run`, `--limit`, or `--max-requests` flag on this CLI.
Select a pilot through `dataset.parameters.sample_ids` in a separate config.
Count questions from the selected loader before estimating QA and judge calls.
Grounding, embedding, consolidation, and ContextFolder verification add calls.
A fact-bearing ContextFolder group uses one planning call plus up to three
compile/answer/judge triplets by default. Caching and fallbacks affect actual use.
Do not invent an exact total from question count alone.

## Check installation without model calls

Use Python 3.11+ in an isolated environment. The commands below use Bash;
on Windows, use the equivalent PowerShell activation command.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m memfolder --help
```

Install only the extras needed for the selected workflow:

```bash
python -m pip install -e ".[algorithms,contextfolder,evaluation]"
```

`algorithms` provides NumPy, SciPy, and scikit-learn. `contextfolder` provides
tiktoken. `evaluation` provides NLTK. Local Qdrant access additionally needs
`.[qdrant]`. `.[llmlingua2]` is optional and can require model weights.
Do not substitute greedy matching for missing SciPy or character counts for
the configured tokenizer.

## Prepare data and configuration

Start with README's **Download data** section. Resolve two separate inputs:
benchmark conversations/questions and the memory bank to compress. The checkout
does not include full benchmark data or the paper's frozen banks.

- LoCoMo: use the pinned `data/locomo/locomo10.json` download in README. Set
  `utc_offset_minutes: 0` for the documented UTC interpretation and
  `evidence_policy: "preserve_unknown"` for its unresolved evidence IDs.
  This keeps questions and marks their evidence recall `not_run`.
  Select `conv-26` for the documented pilot, or `[]` for all ten conversations.
- LongMemEval: the native loader expects `question_id`, `haystack_sessions`,
  `haystack_session_ids` and `haystack_dates`. Record the selected release/split.
- PersonaMem v1: download both `questions_32k.csv` and
  `shared_contexts_32k.jsonl`, and set `contexts_path`.
- M3: annotations require an explicit video-to-memory mapping. Preserve media
  paths and `before_clip` limits. Downloading annotations alone is insufficient.

MemForest_data provides original Mem0 banks and already compressed `keep*`
banks. Use the originals as controlled-comparison inputs. Its LongMemEval and
PersonaMem question files use a converted LoCoMo-style schema, not the native
loaders' schemas. Do not relabel these converted files as native benchmark runs.
If reusing them, inspect conversion/category semantics and provide a matching
adapter and scoring protocol. A public bank is not proof that its hash matches
the paper's frozen bank.

Full experiment templates are in `examples/experiments/`. Files in
`examples/recipes/` configure compression only and cannot be passed directly
to `python -m memfolder run`.

Copy a template to a user-owned config, preserving the distributed example.
Paths resolve from the config's directory, not the shell's working directory.
When moving a config, resolve dataset, prompt-source, cache, and output paths
again. Replace every `REPLACE_*` value and `api.example.invalid` endpoint.
Inspect the supplied templates before treating their defaults as an experiment:

- `history-initializer` creates records from turns. It does not run Mem0's or
  MemOS's extraction/update pipeline. For an existing bank, use
  `bank-initializer` with one explicitly selected store per benchmark sample.
- `retrieval-reader` defaults to lexical top-10 retrieval. Semantic features
  used for grouping do not automatically enable dense retrieval.
- The templates select `memforest-judge`. LoCoMo F1 is an optional separate metric.
- The LoCoMo starter templates write MemOS-format output. Select the intended
  framework and native retriever explicitly when that matters.

For LoCoMo paper comparisons, use the following retrieval limits consistently
for FullContext and all compressed arms:

- Mem0: top-30 per owner (up to 60 recalled records for two owners).
- MemOS: top-20 per owner, retaining the native reranking flow.

FullContext leaves the memory bank uncompressed but still uses these limits.
Configure each owner's limit in the native search. The generic
`reader.parameters.retriever.parameters.top_k` caps the returned hit list:
for `sdk-retriever`, set it to `60` (Mem0) or `40` (MemOS) when the search
service combines two owners before returning results. The built-in
`qdrant-retriever` uses a global limit; setting it to `30` alone does not
implement top-30 per owner. See `src/evaluation/retrieval.py`.

Use the import instructions in [experiment-config.md](references/experiment-config.md)
and `python -m memfolder.loading --help`. Verify source completeness, owner-to-sample
mapping, clocks, and vector model identity before compression. For Mem0 SQLite,
use the collection's `storage.sqlite`, not the operation history `history.db`,
and require an offline store without pending WAL/journal writes.
Preserve originals and write imports and native outputs to new directories.

## Preserve budgets and evidence

- `run.budgets[].ratio` is the fraction retained. A 70% record reduction is
  `ratio: 0.3`. Node budgets count eligible records and use per-scope,
  half-even rounding by default. Report realized counts after rounding.
- RecordFolder needs current semantic vectors, entity features, and a declared
  time/order policy. The LoCoMo template uses `event-time-features`; PersonaMem
  and M3 templates use ordinal ordering. Start from the matching benchmark
  template instead of changing only the dataset in a LoCoMo config. Keep
  sample/scope boundaries and protected records.
- ContextFolder's `target_ratio`, default `0.8`, guides text generation.
  Its default `max_rounds: 3` and `budget_slack: 1.15` are writer settings,
  separate from `run.max_rounds`. The selector or fallback can miss the target.
  Report `final_tokens`, required-fact losses, and fallback reasons. The driver
  enforces node budgets, not a strict global token cap.
- Use `memforest-qa-prompt` and `memforest-judge` across comparison arms.
  Final QA uses no AGPR or method-specific decoding legend. Compression fact
  checks use source memory, never benchmark QA or gold answers.
- LongMemEval query time, PersonaMem's per-question history prefix, and M3's
  `before_clip` cutoff constrain available memory. Never expose future records
  to make a sample pass.
- Use one original memory snapshot, sample selection, retrieval budget, answerer,
  and scoring protocol across a controlled comparison. Keep independent reruns
  separately identified. Do not replace a figure baseline with a table value.

## Select methods

Use the supplied RecordFolder and ContextFolder experiment templates as starting
points. The latter groups original records and encodes the source members.

For ContextFolder after another completed record compressor, use
`examples/recipes/contextfolder-post-record.json` and the composition pattern
in `examples/record_and_context_compression.py`. This separate pass rewrites each current
record once without regrouping or reapplying the record reduction. It is distinct
from encoding original group members. Do not claim these input modes are identical.

For comparisons, inspect the selected JSON in `examples/recipes/` and its
registration in `src/catalog.py`:

- Text ToMe and MST MemForest require repeated execution and embedding refresh.
  The current `tome` plugin uses chronological halves. `tome-bsm` names the
  alternating-partition variant. Start temporal ToMe from
  `examples/experiments/tome-template.json`; configure `semantic-encoder` once
  with the declared embedding space. Stored vectors are not required.
- MemForest's scope-budget and per-cluster ceiling variants resolve budgets
  differently. Preserve the selected variant and its budget resolver. The full
  experiment CLI has no dynamic budget-resolver field. Use the Python API's
  `resolve_memforest_budget` for per-cluster ceilings rather than passing
  that recipe with a scope-level ratio and claiming upstream parity.
- LLMLingua-2 operates on final current records, with default rate `0.55`.
  `llmlingua2-service` passes a rate; `llmlingua2-token-budget-service` computes
  an explicit token budget. Declare which service is used; they are distinct
  compression configurations. Refresh output embeddings before dense retrieval.
- M3 MemForest proxy and DART memory adaptations are explicitly named variants.
  StreamMeCo's compression plugin does not supply its upstream temporal reader.

The generic text-chat template does not reproduce the full M3 multimodal
controller. Native storage and retrieval are separate from multimodal answering.
Check the selected reader, answerer, and judge before making that comparison.

## Run, verify, and inspect

```bash
python -m memfolder run /path/to/experiment.json
python -m memfolder verify /path/to/output
python -m memfolder run /path/to/experiment.json --resume
```

`--resume` validates and reuses a completed run with matching inputs,
configuration, components, and runtime. It does not continue partially completed
samples. After a failure, keep its files and use a new output directory for a
retry. Do not edit receipts or predictions to bypass validation.

For a method/seed sweep, follow `examples/experiments/matrix-template.json`.
The number of runs is the product of axis lengths and seed count, bounded by
`max_runs`. Each run has an isolated directory.

The CLI emits only an exception type on failure. Inspect the failed-stage entry
in `run.manifest.json` and use the Python API locally for the original exception.
Stop paid expansion on authentication, quota, schema, data, or persistent service
errors. The built-in HTTP service has no automatic retry loop.

Read `result.json` for `aggregate.compressed`, `aggregate.uncompressed`, and
per-sample statistics. Metrics include version, `test_only`, measured, failed,
and not-run counts. Token measurements include the tokenizer identity.
`provider_token_usage` may be null. Call counts are not a billing total.

Use `sources.json`, `run.manifest.json`, `completion.json`, per-sample
`source.json`, `final.json`, `evaluation.json`, and `baseline_evaluation.json`
to trace a comparison. Export a question with `python -m memfolder case`.
`capture.text_policy: "omit"` redacts public trace views, not all private run
files. Review snapshots, reader context, predictions, and answers before sharing.

Report the configuration, completed/expected sample and question counts,
original/final record and token counts, metric names/versions, score coverage,
fallbacks, and output paths. Distinguish a tested pipeline from reproduced paper
results. Reproduction requires the matching bank, models, prompts, retrieval,
metric, method version, and seed, not just a successful exit code.
