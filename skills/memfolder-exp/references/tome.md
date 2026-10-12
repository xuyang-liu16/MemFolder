# Temporal ToMe for memory records

The default `tome` / `tome-temporal` plugin uses chronological halves with
incremental text/vector updates. `tome-bsm` retains the alternating-partition BSM adaptation
under a distinct name. Upstream ToMe merges hidden token tensors; the temporal
memory adaptation is explicitly defined here, not claimed as upstream code.

Within each memory scope/owner, sort current records by their effective event
time, then order and node ID. Split eligible mergeable records into an older
floor(N/2) half and a newer ceil(N/2) half. Visit older records in chronological
order. For each one, find the most similar **current** newer record by normalized
cosine, merge those two current texts, retain the newer record ID/order and
timestamp, immediately embed the generated text, and return it to the newer
half. A destination may absorb many sources through separate two-record calls.
Do not freeze all matches before writing texts; do not replace them by an N-way
summary. Destination ties choose the first record in chronological order.

When the older half is exhausted and more reduction is required, re-sort all
remaining records by their effective (latest) time and split again. Stop as soon
as the resolved node budget is met, including in the middle of a half-pass.
For odd sizes the newer half has the extra record. The public node budget is a
retention ratio: keep0.7 means reduce30%, keep0.5 reduce50%, keep0.3 reduce70%.
Per-scope rounding follows the declared budget (`half_even` by default), and
protected-record checks remain explicit. No merges
cross owner/scope boundaries. If every record lacks parsed time, explicit
ordinal `order` is used; mixed unknown/known times or incomparable clocks fail.

`TemporalTomePlanner` selects pairs and maintains pending halves in versioned
state. `TomePairWriter` generates pair text using the shared MemForest merge
prompt, identical to the other record writers for the same pair. An explicit
external `text_writer` plugin can define a separately recorded research protocol.
`TomeEmbeddingBuilder` retains conservative origin/time-range lineage, records
the effective latest timestamp, and attaches a freshly content-bound embedding.
Its inner `record_builder` and encoder service/space are configurable.
`CurrentEmbeddings` validates current content/vector bindings each step.

## Prepare input embeddings

Use `examples/recipes/tome-text.json`, `mode='repeat'`, an explicit node budget,
and injected `chat` / `embeddings` services. Input vectors must be bound to the
input text. The framework's automatic iteration cap grows with input size;
explicit `max_rounds` still enforces a user-selected cap. Pair selection and
record construction emit separate observation events with IDs, text hashes,
similarity, half-pass, provenance, inherited times and embedding space.

`history-initializer` supplies text nodes without node embeddings.
`semantic-encoder` creates a `FeatureBatch` for planning; it does not add vectors
to `MemoryRecord.embeddings`. Replacing only planner/operator therefore does not
prepare a raw history for temporal ToMe. The final wrapper's embedding refresh
occurs after compression and cannot initialize the first match.

For a bank already containing verified content-bound vectors, configure
`current-embeddings` in their declared space and keep the same encoder service
for the ToMe record builder. Replace the template's `semantic-encoder` feature
instead of appending a second provider named `semantic`.

For raw history, a caller-owned Python initializer can use existing APIs:

```python
from dataclasses import replace
from memfolder.initialization import HistoryInitializer
from memfolder.wrappers.embedding import ChangedTextEmbeddings

async def prepare_tome_input(memory, *, space, context):
    initialized = HistoryInitializer().initialize(memory, context)
    snapshot = await ChangedTextEmbeddings(space=space).refresh(
        initialized.initial_snapshot, context
    )
    return replace(initialized, initial_snapshot=snapshot)
```

`context.services` must contain the configured `embeddings` service; `space`
declares its actual provider, model, revision, dimension and cosine metric.
Use this helper through the Python API or an explicit initializer plugin. It is
not a built-in JSON initializer selector. Each vector is bound to the text's
content fingerprint; retain stale/ambiguous-vector validation.

## Context stages and result identities

Context compression after record compression is a separate pipeline stage that
consumes the final record snapshot. The older `tome-with-contextfolder.json`
example is an explicitly legacy BSM/group-writer composition; it is not the
new temporal ToMe followed by a context stage.

Libraries produced with a different ToMe variant or merge prompt retain those
identities. New record grouping, text or embeddings require new record banks.
QA/judge-only changes can reuse a verified bank with a new evaluation identity.
All final QA and judge use the [shared MemForest protocol](../../../docs/PROMPT_PROTOCOL.md).
