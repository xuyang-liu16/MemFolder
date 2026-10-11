# Shared MemForest prompt protocol

Record merge, benchmark QA and benchmark judge use `memforest.shared.v1`.
The single template source is `src/memfolder/prompt_templates.py`; rendering
and the protocol manifest live in `src/memfolder/prompt_protocol.py`.
Templates are literal copies of the archived MemForest supplement, with
source-file and prompt SHA-256 hashes recorded beside them.

| Stage | Shared behavior |
| --- | --- |
| Record merge | MemForest summary instructions; user message, temperature 0 |
| Benchmark QA | MemForest `ANSWER_PROMPT`; system message, temperature 0 |
| Benchmark judge | MemForest `ACCURACY_PROMPT`; user message, temperature 0, JSON response |

`NativeSummaryWriter`, `MemForestPairWriter` and `TomePairWriter` send identical
requests for identical pairs. ToMe still chooses chronological pairs and
refreshes the destination embedding after each merge. RecordFolder still
selects groups. An N-way group uses one call with the same instructions:
only the count and numbered memory/timestamp slots change. Singletons kept
by record compression remain unchanged.

All context methods and the uncompressed control use the same benchmark QA
and judge. `contextfolder-qa-prompt` is a compatibility alias for the shared
QA. It adds no decoder legend. `qa-prompt` / `memforest-qa-prompt` and
`chat-judge` / `memforest-judge` are equivalent aliases. A built-in QA prompt
rejects method-specific instruction or legend parameters.

Public multiple-choice options and query time remain input data in the
question slot. Memory adapters preserve timestamps and speaker attribution.
For a single speaker the second slot is empty; for more than two speakers,
additional speakers remain explicitly attributed in the second slot.
These adapters apply independently of the compression method.

ContextFolder's fact extraction, encoding, blind fact recovery, and repair
prompts are part of the compression operator. They are distinct from the
benchmark QA/judge and remain independently replaceable. Its no-facts summary
fallback now uses the shared MemForest summary instructions. LLMLingua2 is a
token classifier and has no LLM compression prompt. BabelTele compression
plugins retain their method-specific encoding instructions; their benchmark
QA and judge still use the shared MemForest templates.

## Configure the comparison

```json
{
  "reader": {
    "plugin": "retrieval-reader",
    "parameters": {
      "answerer": {
        "plugin": "chat-answerer",
        "parameters": {"prompt_builder": {"plugin": "memforest-qa-prompt"}}
      }
    }
  },
  "evaluator": {
    "plugin": "metric-evaluator",
    "parameters": {"metrics": [{"plugin": "memforest-judge"}]}
  }
}
```

Bind `services.chat` and `services.judge` to the declared model/revision.
Use the same retrieval configuration, model and budgets across comparison
arms. Planners, operators, writers, builders and services retain their plugin
interfaces. A separate research protocol can be contributed as an explicit
external plugin and recorded separately; benchmark selection never implicitly
changes the comparison prompt.

Requests carry the prompt identity, message role and response format.
Provider payloads honor these fields. Cache keys include all three as well
as rendered content, temperature, limits and provider identity. Run manifests
record the default protocol and template hashes; component bindings identify
any explicit external plugins.

Existing results and compression banks keep their original identities.
Changed merge prompts require new banks and content embeddings for a fresh
comparison. A change only to QA or judge can reuse the same verified bank
under a new evaluation identity. Existing frozen result files are preserved.

The offline tests verify literal hashes, pair parity, N-way input coverage,
speaker attribution, absence of method-specific QA legends, strict JSON
labels, provider envelopes and cache isolation. They make no paid model calls.
