# Model-backed experiment configuration

Use this reference when adapting the supplied templates or evaluating an existing
bank. Read the actual configuration and source before substituting a component.
The snippets below are sections of a full experiment, not standalone run files.

## Existing memory banks

Map each dataset sample to exactly one selected library using `bank-initializer`.
For a real LoCoMo sample, replace `SAMPLE_ID` in both places and select only its
owners with `options.selectors`, such as `{"user_id": ["Alice_1", "Bob_1"]}`.
Use actual owner IDs from the store. Setting `sample_id` alone does not filter
unrelated conversations.

For the pinned MemForest LoCoMo bank in README, the SQLite file is
`locomo/qdrant/collection/mem0/storage.sqlite`. The first official LoCoMo sample
is `conv-26`, with speakers Caroline and Melanie. MemForest constructs owner IDs
as `<speaker>_<zero-based sample index>`, so this mapping selects `Caroline_0`
and `Melanie_0`. Verify those owners in the actual bank before running.
Set `naive_timezone: "UTC"` for this bank's timezone-free event timestamps,
matching the upstream parser. For other banks, determine their time convention.

```json
{
  "initializer": {
    "plugin": "bank-initializer",
    "parameters": {
      "loaders": {
        "SAMPLE_ID": {
          "plugin": "mem0-sqlite",
          "parameters": {
            "path": "/absolute/path/collection/mem0/storage.sqlite",
            "options": {
              "dataset_id": "locomo",
              "sample_id": "SAMPLE_ID",
              "naive_timezone": "UTC",
              "selectors": {"user_id": ["ACTUAL_OWNER_A", "ACTUAL_OWNER_B"]}
            }
          }
        }
      }
    }
  }
}
```

The loader's dataset/sample IDs must match the benchmark. An owner ID, a video
ID, and a question ID are not interchangeable. LongMemEval uses `question_id`
as sample ID. M3's dataset loader creates cutoff-specific samples from each
video's explicit memory mapping. Do not use a fallback initializer to conceal
a missing benchmark-to-bank mapping.

Imported Mem0 nodes carry node provenance, not automatically the original
LoCoMo `dia_id` evidence mapping. Without that mapping, remove `evidence-recall`
from the evaluator rather than reporting a misleading zero. Keep answer metrics.
Owner partitions remain separate in the loader and default node budgets.
MemForest upstream groups by sample-index suffix across owners. Reusing its
bank or its pair-selection functions therefore does not establish identical
end-to-end clustering or retrieval behavior.

### Import and inspect a bank

Run `python -m memfolder.loading --help` for the supported input formats.
The Python entry points are in `src/memfolder/loading/__init__.py`, with loader
parameters in `src/memfolder/loading/factories.py` and `LoadOptions` in
`src/memfolder/loading/types.py`.

| Input | Loader function | Additional setup |
| --- | --- | --- |
| Mem0 export or Qdrant point JSON/JSONL | `load_mem0` | Owner selectors |
| Archived MemoryNode JSONL | `load_mem0_legacy_nodes` | Source namespace |
| Local Qdrant directory | `load_mem0_qdrant` | Collection name and `.[qdrant]` |
| Offline Qdrant `storage.sqlite` | `load_mem0_sqlite` | No pending WAL/journal |
| MemOS text/tree JSON or cube | `load_memos`, `load_memos_cube` | Cube selection and component assets |
| M3 VideoGraph JSON or pickle | `load_m3` | Video mapping, NumPy for array-bearing pickles |
| Saved MemFolder library | `load_library` | Matching dataset/sample IDs |

An import writes a fresh directory containing `library.json` and `report.json`:

```bash
python -m memfolder.loading mem0-sqlite /path/to/storage.sqlite \
  --options /path/to/load-options.json --output-dir /path/to/new-import
```

Inspect source coverage, filtered counts, parsing issues, record/edge counts,
and source hashes before compression. `unknown` coverage does not establish a
complete bank. Keep MemOS component assets beside the cube and preserve M3 media
paths, clip partitions, and protected media/identity nodes.

Declare `embedding_spaces` only when the source model, revision, dimension, and
slot are known. Native vectors with unknown provenance are not a substitute for
declared semantic features. Set `naive_timezone`, `numeric_timestamp_clock`, and
`visibility_field` from the source format. `order_by: "time_id"` requires
comparable parsed times. Never infer availability from event time alone.

## Dense retrieval and embeddings

The templates compute semantic features for grouping but default to lexical
retrieval. For a dense experiment, configure both the reader and the wrapper's
content embedding provider with the same embedding space. Keep the template's
existing reader answerer and wrapper codec/writer settings.

Under `reader.parameters`, add:

```json
{
  "retriever": {
    "plugin": "dense-retriever",
    "parameters": {
      "top_k": 10,
      "space": {
        "provider": "YOUR_PROVIDER",
        "model": "YOUR_EMBEDDING_MODEL",
        "revision": "YOUR_MODEL_REVISION",
        "dimension": 1536
      }
    }
  }
}
```

Under `compression.wrapper.parameters`, add:

```json
{
  "embedding_provider": {
    "plugin": "content-embeddings",
    "parameters": {
      "space": {
        "provider": "YOUR_PROVIDER",
        "model": "YOUR_EMBEDDING_MODEL",
        "revision": "YOUR_MODEL_REVISION",
        "dimension": 1536
      }
    }
  }
}
```

Use the actual dimension and matching declarations in the semantic feature
provider and `services.embeddings` too. The default embedding service name is
`embeddings`. Rewritten text needs fresh content-bound embeddings.
`top_k: 10` is an example, not a claim about the paper's setting.
For framework-native retrieval, inspect `src/memfolder/evaluation/native.py`
and the selected wrapper in `src/memfolder/wrappers/`.

The Mem0 Qdrant writer requires one unnamed dense-vector space. MemOS tree output
uses `backend: "tree_text"` even when no edges remain. Native M3 pickle output
uses `m3-pickle-writer` with a supplied `m3.graph_type` service. Output readback
helpers are `open_qdrant_view`, `load_memos_view`, and `load_m3_view` in
`memfolder.wrappers`. Close Qdrant clients after use and supply a configured
empty MemOS instance or matching M3 graph class.

Keep rewritten text and its embeddings synchronized. Direct wrapper calls need
a new `output_dir`; the full runner isolates outputs by run and sample.
`python -m memfolder verify RUN_DIRECTORY` checks referenced native outputs too.

## ContextFolder writer settings

Under `compression.operator`, the writer parameters are explicit:

```json
{
  "plugin": "contextfolder-operator",
  "parameters": {
    "writer": {
      "plugin": "contextfolder-writer",
      "parameters": {
        "target_ratio": 0.8,
        "max_rounds": 3,
        "budget_slack": 1.15
      }
    }
  }
}
```

The target is based on the sum of the input members' token counts. It guides the
loop but is not an exact output size. Keep a tokenizer with a declared
`measurement_id`, such as the configured `tiktoken-counter`.
The blind answerer sees encoding, questions, and the decoding legend. The judge
compares recovered answers with the planner's facts. Neither is the downstream
benchmark judge.

For a post-record pass, use `current-record-rewrite` and `current-record-builder`
as in `examples/recipes/contextfolder-post-record.json`. Reset the compression
state, features, rounds, and node budget for this separate `mode: "once"` pass.
`examples/record_then_context.py` demonstrates that composition in Python.
There is no arbitrary multi-stage list in the full experiment JSON schema.

## Shared benchmark QA and scoring

Use the same final QA and judge for LoCoMo, LongMemEval, PersonaMem and M3,
regardless of memory framework or compressor. Under the reader's answerer:

```json
{
  "plugin": "chat-answerer",
  "parameters": {"prompt_builder": {"plugin": "memforest-qa-prompt"}}
}
```

Under `evaluator`, use:

```json
{
  "plugin": "metric-evaluator",
  "parameters": {
    "metrics": [{"plugin": "memforest-judge", "parameters": {"service": "judge"}}]
  }
}
```

Bind `services.chat` and `services.judge` to the declared model and revision.
The online templates already select both shared components; configure the judge
endpoint and credentials alongside chat/grounding/embeddings. The template
copies the chat settings for judge, so keep both synchronized or explicitly
record a different judge model consistently across every comparison arm.

The single source is `src/memfolder/prompt_templates.py`.
The [prompt protocol](../../../docs/PROMPT_PROTOCOL.md) records source/template
hashes, message roles and JSON output. The judge accepts only
`{"label":"CORRECT"}` or `{"label":"WRONG"}`; invalid labels fail evaluation.
`chat-judge` selects that same implementation. All final QA aliases are identical
and append no method-specific decoder legend or AGPR.

LoCoMo F1, exact match, evidence recall and PersonaMem deterministic option
accuracy remain optional metrics with their own identities. PersonaMem's
reference option content and public choices are passed to the shared judge.
The MemForest scoring protocol differs from native benchmark scoring; benchmark
source records document those upstream sources without switching the run's judge.

## Benchmark time and reader scope

| Benchmark | Available information | Configuration requirement |
| --- | --- | --- |
| LoCoMo | Session dates, speakers and dialogue evidence | Declare timezone for naive dates; select the matching bank owners. |
| LongMemEval | Session dates and query time | Preserve query-time visibility and use the matching original or converted schema. |
| PersonaMem v1 | Role-tagged turn order and a per-question prefix | The default loader does not invent event dates. Use an explicitly declared order/time adapter or a matching bank with real event times. |
| M3 robot/web | Clip visibility, native graph order and protected media/identity nodes | Clip `available_at` is not an event timestamp. Choose a method-compatible order/time adapter and preserve `before_clip` truncation. |

The RecordFolder/ContextFolder LoCoMo templates use `event-time-features`.
PersonaMem and M3 fixtures without `time_ranges` fail that feature's contract.
Setting an epoch timestamp or copying availability into event time hides the
missing semantics. Supply a separate feature provider, or use a documented
order-based method variant; keep its clock and variant identity explicit.
The temporal ToMe planner supports all-ordinal input when parsed times are absent.
It consumes shared semantic features in a declared cosine space; the common
`semantic-encoder` obtains them from current text before each match. No stored
node vectors are required by this composition. Mixed or incomparable clocks fail.

The generic answerer consumes text. Loading media and writing a native graph
does not execute M3's multimodal controller. A controller-backed reader remains
an explicit plugin; its retrieval and scoring scope must be recorded.

## Inspect the implementation

| Decision | Source |
| --- | --- |
| CLI arguments and config-relative paths | `src/memfolder/__main__.py` |
| Assembly, output isolation, verification, resume | `src/memfolder/experiment.py` |
| Matrix axes, seeds, and limits | `src/memfolder/matrix.py` |
| Registered parameters and plugin names | `src/memfolder/experiment_plugins.py`, `src/memfolder/method_plugins.py` |
| History records versus imported banks | `src/memfolder/initialization.py` |
| Anchor selection, affinity, temporal matching | `src/memfolder/planning/recordfolder.py` |
| Fact planning, blind checks, fallback selection | `src/memfolder/operators/contextfolder.py` |
| Node budgets and enforcement | `src/memfolder/core/budgets.py`, `src/memfolder/compression.py` |
| Reader defaults and content limits | `src/memfolder/evaluation/reader.py`, `src/memfolder/evaluation/retrieval.py` |
| Metric and judge protocols | `src/memfolder/evaluation/metrics.py`, `src/memfolder/evaluation/official.py` |
| HTTP payloads, cache identity, token counting | `src/memfolder/services.py` |
| Post-rewrite embeddings | `src/memfolder/wrappers/embedding.py` |

The built-in context builder limits characters, not tokens. Record that setting
when comparing reader budgets. The supplied chat answerer consumes text.
Do not claim multimodal inference solely because a loader preserves media parts.
