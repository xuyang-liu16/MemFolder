# Composable compression

`RecordFolder` is the formal name of G1S; `ContextFolder` is the formal name of V12.
The standardized release supplies the mainline algorithm and prompts. The new
package separates decisions from content transformation and backend projection.
Original research files remain outside the package and are not imported at runtime.

## Execution boundaries

```text
Native loader → Snapshot → Feature providers → Planner → ActionPlan
                                                      ↓
Original archive + live services → Operator → OperatorResult
                                             ↓
                          Projector → revised Snapshot → next round
```

`assemble(config)` resolves the planner, operator and optional feature providers,
including nested plugins. `CompressionEngine.step()` executes a validated plan;
`run()` projects results, refreshes configured features between rounds and checks
the final node budget. Both methods are asynchronous. Numerical stages and
contributed stages may be synchronous or asynchronous.

The assembler has no benchmark/framework branching. Mem0, MemOS and M3 inputs
share the canonical `Snapshot`. Benchmark question sets, answers and scoring
labels do not enter this compression API. A new benchmark changes its loader,
scope/time/vector declarations and later evaluator, rather than planner logic.

## Mainline replacement points

RecordFolder planning stages are independently configurable:

| Slot | Role | Default | Input → output |
| --- | --- | --- | --- |
| `anchors` | `anchor_selector` | `density-peaks` | local request + K → `AnchorSelection` |
| `assignment` | `group_assigner` | `nearest-anchor-assignment` | request + anchors → `Group` partition |
| `candidates` | `candidate_generator` | `temporal-candidates` | request → `CandidateBatch` |
| `scorer` | `affinity_scorer` | `fused-affinity` | request + candidates → `ScoreBatch` |
| `gate` | `gate_policy` | `anchor-gate` | request + scores → `GateBatch` |
| `matcher` | `matcher` | `chain-matcher` | candidates + scores + gates → `CandidateSelection` |
| `hosting` | `group_router` | `chain-hosting` | initial partition + selected edges → final partition |

The default chain uses density peaks, nearest-anchor assignment, temporal
predecessor candidates, variance-scaled entity/semantic fusion, anchor gain gating,
Hungarian matching and summed cosine chain hosting. Candidate window=50,
top-k=8, density neighbor-k=5 and variance floor=1e-6 match the source.

An anchor selector can serve both a prune planner and the RecordFolder grouping
pipeline. `selection_required(request, component_nodes(request))` exposes the
records protected for the current operation. Merge-protected records remain
singleton groups; drop-protected records remain real retained records. The engine
does not silently lower protection to make a budget feasible. Canonical IDs break
ties; reproducing a historical run also requires its scope IDs, ordering and seed.

ContextFolder uses the same grouping pipeline and also rewrites singleton text
records. Its `contextfolder-writer` has six replaceable slots:

| Slot | Role | Default |
| --- | --- | --- |
| `fact_planner` | `fact_planner` | `fact-planner` |
| `triage` | `triage_policy` | `fact-triage` |
| `compiler` | `compiler` | `context-compiler` |
| `verifier` | `verifier` | `blind-verifier` |
| `feedback` | `feedback_builder` | `repair-feedback` |
| `selector` | `round_selector` | `shortest-clean-round` |

Defaults retain V12's 0.80 target ratio, three rounds, 1.15 budget slack and
importance/inferability triage. The blind answerer receives the encoding and
compression-generated questions; the judge receives the reference facts and
blind answers. The extractor's questions are separate from benchmark QA.
Malformed verdict strings cannot become a positive boolean. Empty/oversized
encodings produce explicit source fallbacks with actual stored token counts.

The ratio is a compiler target, not an enforced final token cap. A clean chosen
round can exceed that target; `required_lost` is recorded for an imperfect chosen
round. A token-budget executor is needed for strict global token constraints.

## Baselines and explicit experimental variants

| Method | Planner recipe | Reusable components / provenance |
| --- | --- | --- |
| RandomPrune | `random-prune` | Python seeded sample selector + keep/drop |
| RandomMerge | `random-merge` | global pair grouping; `random-merge-round` is a separate PCG disjoint-round variant |
| KmeansPrune | `kmeans-prune` | KMeans clusters + closest real centroid representative |
| KmeansMerge | `kmeans-merge` | same clusters + replaceable text writer |
| DART | `dart` | archived memory adaptations: `random_anchor_farthest` and `medoid_pivot` |
| ToMe text | `tome` | float32 alternating bipartite matching, repeated text rewrite and re-embedding |
| ToMe M3 | `tome-pooled` | offline feature-mass pooling; no implicit content embedding reuse |
| MemForest text | `memforest` | joint semantic/time clustering, allocation, MST pair router and pair prompt |
| MemForest M3 proxy | `memforest-proxy` | archived average-linkage proxy, explicitly distinct from MST MemForest |
| StreamMeCo | `streammeco` | pinned official graph classification, spherical coverage, importance/diversity ranking |

KMeans uses normalized cosine-space features and Euclidean centroid distance.
Identical embeddings can yield empty clusters; deterministic splitting is emitted
as a diagnostic so the user-approved exact K definition remains satisfied.

DART here is the historical memory adaptation, not token pruning inside a
transformer. M3 pooled variants offer `id_order: source_numeric` to reproduce
numeric native-ID tie rules. No embedding model, missing timestamp or metric is
guessed. `TemporalCandidates(temporal_order='order')` and
`JointClusters(time_order='order')` are explicit alternatives to event time.

MemForest text and ToMe text require request mode `repeat`; each round uses
fresh embeddings of the actual rewritten text. Configured
`semantic-encoder` providers regenerate features; stale stored embeddings are
removed from rewritten records. ContextFolder can replace their native summary
writer through `contextfolder-operator` without replacing the routing algorithm.
For MemForest, configure `event-time-features` with `aggregation: latest`, since
the historical pair merge inherits the newer timestamp. The provided MST recipes
declare that provider. Supply semantic features through the request or another
provider without also supplying a duplicate `temporal` batch.

MemForest's historical budget is **ceil per initial cluster**, which can exceed
ceil per scope. For that variant:

```python
from dataclasses import replace
from memfolder.planning import resolve_memforest_budget, JointClusters

budget = await resolve_memforest_budget(request, context,
    clusterer=JointClusters(), keep_ratio=0.7)
request = replace(request, budgets=(budget,), mode='repeat')
```

Use `memforest-mst-cluster-ceil.json` with this resolved budget and a matching
clusterer/ratio. The default `memforest-mst-capacity.json` instead allocates an
explicit exact scope target; it is a budget adaptation, not the historical ceil
recipe. Initial cluster membership survives subsequent merges via origin identity.

StreamMeCo keeps separate class budgets: no-media text is selected per clip;
media-connected text is ranked per sample. The official recipe therefore may
conflict with a caller's exact scope K. Use no external node budget to follow its
class ratios, or supply a compatible advisory/upper-bound budget. A conflict
raises an error instead of modifying the official selection. This port covers
graph compression; StreamMeCo's temporal retrieval/Reader is a later module.

## Features and live services

The full RecordFolder recipe needs `semantic` vectors and `entities` rows with
entity/relation keys, parsed event times and a common clock.
`GroundingFeatures` reads standardized cached grounding and explicit ID maps;
it does not regenerate the legacy LLM extraction/synonym cache. That generation
can be supplied as an independent feature provider.
The named semantic-only recipe is an ablation and is labelled accordingly.

`StoredEmbeddings(space=...)` accepts embeddings whose declared content and
space match the snapshot. An unknown native model is not treated as verified.
For iterative compression, `SemanticEmbeddingFeatures(space=...)` calls the
injected encoder's `encode(texts)`; it may return vectors or an awaitable.
`EventTimeFeatures` uses event ranges, not future-availability timestamps.
Specify an explicit adapter for unknown times or mixed native vector slots.

Live clients are injected through `ServiceMap`, never serialized in config:

```python
from memfolder.assembly import assemble
from memfolder.compression import DiagnosticCollector, ServiceMap
from memfolder.operators import Cl100kTokenizer

assembly = assemble(config, base_path=configuration_directory)
diagnostics = DiagnosticCollector(callbacks=(my_case_callback,))
run = await assembly.engine.run(request,
    services=ServiceMap({'chat': my_chat_client, 'embeddings': my_encoder,
                         'tokenizer': Cl100kTokenizer()}),
    diagnostics=diagnostics, projector=my_projector)
diagnostics.write_jsonl('new-run/diagnostics.jsonl')
```

`chat.complete(ChatRequest)` returns text or an awaitable. Inject the intended
model/settings through the client. Native summary needs `chat`; ContextFolder
needs its configured chat services and a tokenizer with `measurement_id` and
`count(text)`. Tokenizers remain synchronous. Models/providers are not hardcoded.

## Writing a contribution

Implement a structural protocol in `planning.protocols` or `operators.protocols`
and give it a `PluginSpec`. Builtin stages have the same interfaces. Use an
installed `memfolder.plugins` entry point or an explicit `module:factory`:

```json
{
  "planner": {
    "plugin": "recordfolder",
    "parameters": {
      "anchors": {"plugin": "example.recency"},
      "scorer": {"plugin": "my_method:build_scorer", "parameters": {"temperature": 0.2}}
    }
  },
  "operator": {"plugin": "contextfolder-operator"}
}
```

The [independently packaged recency selector](../examples/plugins/recency/recency_plugin.py)
works as both a prune selector and a merge anchor selector. Its implementation
does not edit or register anything in the builtin catalog. Recipes in
[examples/recipes](../examples/recipes) show baseline variants and crossed modules.
An entirely new planner can bypass the RecordFolder stages and return a validated
`ActionPlan`. Four actions (`keep`, `drop`, `merge`, `rewrite`) cover these methods;
an extra action requires its declared validator and operator.

Typed `Group`, `AnchorSelection`, `TextWriteResult` and `EncodingRound` values are
immutable in-process stage values. Existing wire contracts carry the public
plan, result and diagnostics across process boundaries. Snapshot fingerprints,
exact partition membership, scope boundaries, chain degrees, accepted candidate
membership and final lineage are checked at the relevant interfaces.

## Case analysis and projection

`DiagnosticCollector` sends detached immutable `DiagnosticRecord` values to
callbacks and writes contract JSONL. Enable selected schemas to limit collection.
Events include anchors, assignments, candidate endpoints, fusion terms, gate
reasons, selected matching, hosted chains, KMeans labels/centers, MST pairs,
StreamMeCo ranking, plans, operator outcomes, fact triage, repair rounds and final
selection. Node/candidate/action links join these events to source and output.

Model-call metering records the calls actually performed, prompt/response hashes,
statuses and roles. ContextFolder defaults to hashes and aggregate counts;
`capture_text` and `capture_prompts` opt into detailed fact/encoding/model content.
The assembler returns plugin bindings, config fingerprint and current source
hashes for each run. Callbacks cannot replace results. They are trusted in-process
extensions, not isolated processes; an exception in a callback fails the run.

`NodeProjection` handles node-only snapshots. `PruneGraphProjection` removes edges
incident to dropped nodes while retaining assets and surviving edge identities.
`RedirectEdges` supports graph merge projection through configurable edge reduction.
Composable wrappers now own native indexes, identity maps, actual content embeddings,
new-bank writing and native reader bridges. See [WRAPPERS.md](WRAPPERS.md) for supported
Mem0/MemOS/M3 formats and SDK integration boundaries.

The diagnostic collector and persistent observer/case runtime are operational.
Raw benchmark parsers, readers, metrics and offline matrix execution are implemented;
see [EXPERIMENTS.md](EXPERIMENTS.md). Real model quality and complete online SDK
lifecycles require separate validation.

## Verification and local usage

Install optional numerical dependencies only when needed:

```powershell
python -m pip install -e ".[algorithms,contextfolder]"
python tools/check_contracts.py
python examples/compression_demo.py
```

The offline example is synthetic grouping plus concatenation, with zero model
calls. Tests characterize mainline grouping, routing and pure selection routines
against archived/pinned source, and exercise protection, budgets, async plugins,
fallbacks, immutable observation and repeated feature refresh. Scripted model
responses verify behavior, not LLM fidelity, QA accuracy or reproduced paper
scores. Method origins and deliberate adaptations are listed in
[METHOD_PROVENANCE.json](METHOD_PROVENANCE.json) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
