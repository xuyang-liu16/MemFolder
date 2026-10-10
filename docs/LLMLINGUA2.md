# LLMLingua-2 after Record compression

[Documentation](README.md) · [Compression methods](COMPRESSION.md)

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
