# Temporal ToMe for memory records

The default `tome` / `tome-temporal` plugin uses chronological halves and
incremental pair selection. `tome-bsm` retains the alternating-partition BSM
adaptation under a distinct name. Upstream ToMe merges hidden token tensors;
this temporal memory adaptation follows the project's declared contract.

Within each memory scope/owner, sort current records by their effective event
time, then order and node ID. Split eligible mergeable records into an older
floor(N/2) half and a newer ceil(N/2) half. Visit older records in chronological
order. For each one, find the most similar **current** newer record by normalized
cosine, merge those two current texts, and retain the newer record ID/order and
timestamp. The shared feature provider encodes the generated text before the
next match. A destination may absorb many sources through separate two-record
calls. Do not freeze all matches or replace them by an N-way summary.
Destination ties choose the first record in chronological order.

When the older half is exhausted and more reduction is required, re-sort all
remaining records by their effective latest time and split again. Stop as soon
as the resolved node budget is met, including in the middle of a half-pass.
For odd sizes the newer half has the extra record. The public node budget is a
retention ratio: keep0.7 means reduce30%, keep0.5 reduce50%, keep0.3 reduce70%.
Per-scope rounding follows the declared budget (`half_even` by default), and
protected-record checks remain explicit. No merges cross owner/scope boundaries.
If every record lacks parsed time, explicit ordinal `order` is used; mixed
unknown/known times or incomparable clocks fail.

## Compose the common pipeline

`TemporalTomePlanner` selects one current pair per scope per round and maintains
pending halves in versioned state. It consumes the same semantic `FeatureBatch`
contract as other planners. The default recipe uses the common `TextOperator`
and `NativeSummaryWriter`, with the shared MemForest merge prompt.
`ConservativeRecordBuilder` honors the action's destination ID/order and latest
timestamp policy while retaining all source origins and inherited time ranges.
These policies are action parameters rather than ToMe-specific builder logic.

Configure `semantic-encoder` once, with an explicit embedding space and an
`embeddings` service. The engine extracts fresh features from the current
snapshot before every planner call. This includes the first call on raw text
from `history-initializer`; precomputed node vectors are not a prerequisite.
Configure `cached-service` around the encoder to reuse unchanged text across
rounds. Only new text needs a new encoder call, including final materialization.

The full [tome-template.json](../../examples/experiments/tome-template.json)
loads raw LoCoMo history, runs temporal ToMe and evaluates both source and result
with the shared QA/judge protocol. Fill in chat/embedding/judge endpoints,
models, revisions, credentials and the actual embedding dimension as described
in [experiment-config.md](experiment-config.md). It defaults to lexical retrieval
and MemOS output. Use its `run.mode: "repeat"`; the automatic iteration cap grows
with input size, while explicit `max_rounds` still enforces a user-selected cap.

For Python assembly, [tome-text.json](../../examples/recipes/tome-text.json)
is a planner/operator fragment. Supply the common semantic provider, services
and a resolved node budget in the caller's full composition. The `tome-operator`
selector is a compatibility alias of the common text operator, with replaceable
writer, record builder and member resolver.

Planning observations retain pair IDs, similarity, half-pass and input
fingerprints. Common operator observations retain output text hashes; records
retain lineage. `CompressionStep.request.features` retains the semantic batch
and declared space for analysis. An observed service can expose encoder calls
without coupling the planner to a particular encoder.

## Stored vectors and final output

Planner features are not stored node embeddings. Dense retrieval and native
Mem0 vector output require the wrapper's `content-embeddings` provider in the
same declared space, as described in [experiment-config.md](experiment-config.md).
The final changed-text vector must be bound to its content fingerprint; retain
dimension, space and stale-vector validation. Lexical retrieval does not require
final stored vectors.

Existing explicit `tome-pair-writer` and `tome-embedding-builder` plugins remain
available for compatibility. The latter needs initial content-bound vectors
and refreshes each merged node's stored vector. `current-embeddings` is suitable
for that explicitly configured path, where a builder keeps node vectors fresh;
it cannot replace `semantic-encoder` while retaining the default builder, which
clears vectors on changed text. These optional components are not required by
the default raw-text pipeline.

## Context stages and result identities

Context compression after record compression is a separate pipeline stage that
consumes the final record snapshot. See
[record_then_context.py](../../examples/record_then_context.py); declare
`embedding_space` for raw input and inject the selected context services. The
older `tome-with-contextfolder.json` example is explicitly a legacy BSM/group
composition, rather than temporal ToMe followed by a separate context stage.

Libraries produced with a different ToMe variant or merge prompt retain those
identities. New record grouping, text or embeddings require new record banks.
QA/judge-only changes can reuse a verified bank with a new evaluation identity.
All final QA and judge use the
[shared MemForest protocol](../../src/prompt_protocol.py).
