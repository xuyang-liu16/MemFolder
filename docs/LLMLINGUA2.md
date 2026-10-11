# LLMLingua-2 after Record compression

[Documentation](README.md) · [Compression methods](COMPRESSION.md)

## Recovered LongMemEval recipe

For the recovered LongMemEval compression recipe, use the
`llmlingua2-historical-service` plugin. The service configuration is supplied in
[llmlingua2-historical-services.json](../examples/recipes/llmlingua2-historical-services.json).
Keep the existing current-Record planner/writer recipe, with writer rate 0.55.
The two service plugins implement the same writer contract; the rate-only
adapter described below remains available as an explicitly different variant.

The historical service strips the final merged Record text, counts tokens with
`cl100k_base`, and calls `compress_prompt` with
`target_token=max(6, round(rate * source_tokens))` and
`force_reserve_digit=True`. It adds `force_tokens=["\n"]` only if the stripped
input contains a newline. It loads the pinned checkpoint using the original
constructor defaults, without a dtype or internal batch-size override. Both
the normalized input and the original writer input have recorded hashes; cache
identities distinguish this profile from the rate-only adapter. Empty output
is an explicit source-preserving fallback; other model failures propagate.

For historical Mem0 export, configure the wrapper's codec as
`{"plugin": "llmlingua2-historical-mem0-codec"}`. Supply the original native
source archive: each output inherits its latest original contributor's point
ID and payload; tied timestamps use the original point ID. Text embeddings
must be refreshed before retrieval. This does not alter other framework codecs.

Matching compression calls is only one part of reproducing Figure 3. The
Record parent store, grouping/merged text, native metadata, retrieval, QA,
judge, and repeated-run protocol also need recorded provenance. At present,
historical parent stores and the complete historical runtime are not verified.
Do not interpret this plugin as a guarantee of the paper's numerical score or
adjust its rate, retrieval, or judge based on the resulting accuracy.

The local LongMemEval seed-7 check on the current Record parents completed
500 questions and scored 259/500 (51.8%). It is a current-parent result, not a
claim that Figure 3's three-run result has been reproduced.

## Rate-only variant

The `llmlingua2-writer` plugin targets **rate 0.55** by default. Rate is the
retained text proportion, distinct from Record `keep_ratio: 0.5`. The official
classifier may produce a slightly different measured token proportion. This
setting does not change ContextFolder's independent default rate of 0.8.

Use [llmlingua2-post-record.json](../examples/recipes/llmlingua2-post-record.json)
with `mode: "once"` on the **final current Record snapshot**. The planner emits
one current-text rewrite per eligible record and keeps protected records. It
does not reconstruct original source texts or perform additional Record merges.
The output retains Record IDs, order, origins, inherited event times and the
effective latest timestamp; its content embeddings require refresh before
retrieval, as supplied by the configured framework wrapper.

```json
{
  "planner": {"plugin": "current-record-rewrite"},
  "operator": {
    "plugin": "llmlingua2-operator",
    "parameters": {
      "writer": {"plugin": "llmlingua2-writer", "parameters": {"rate": 0.55}}
    }
  }
}
```

Rate is configurable. Invalid rates (including booleans, NaN and infinity)
fail before classifier inference. The writer checks the service's declared
rate and input text hash, and records them in diagnostics and record metadata.
Configuration and request fingerprints distinguish rate 0.55 from 0.8 and
distinguish changed input text. Empty classifier output is an explicit
`empty_classifier_output` fallback retaining the source; inference errors fail.

Install the optional official implementation when needed:

```bash
pip install -e ".[llmlingua2]"
```

In a full experiment's `services` section, configure:

```json
{
  "llmlingua2": {
    "plugin": "llmlingua2-service",
    "parameters": {
      "model_name": "microsoft/llmlingua-2-xlm-roberta-large-meetingbank",
      "revision": "ebaba9b0e874dadd3003ffcff828e4397e568089",
      "device_map": "cuda",
      "dtype": "float16",
      "max_batch_size": 16
    }
  }
}
```

This adapter uses `llmlingua==0.2.2`, initializes `use_llmlingua2=True`, and
passes `rate` explicitly with `use_context_level_filter=False`. It does not
supply a `target_token` override. Loading happens on the first compression
call; assembling a configuration does not load weights. A local checkpoint
path can replace `model_name`. For CPU execution declare `device_map: "cpu"`
and `dtype: "float32"`. Another service can implement `compress(text, rate=...)`
and return the same result contract.

[record_then_context.py](../examples/record_then_context.py) demonstrates
temporal ToMe followed by LLMLingua-2 or ContextFolder as independent stages.
Callers inject `chat`, `embeddings`, and the selected context services. Record
pairing uses fresh merged-text embeddings before choosing the next pair;
context compression runs only after Record compression finishes. QA remains a
later reader/evaluator stage, with its own retrieval and evaluation protocol.

Historical results using another rate or the old ToMe recipe retain their
original identities. A corrected configuration requires new context/QA
artifacts; it does not relabel historical scores.
