# G1S

Entity-grounded trajectory chaining for conversational memory compression,
evaluated on LoCoMo.

This package is the main line of the experiment and nothing else. It replaces a
pile of dated one-off scripts with seven steps that can be read in order, and it
reproduces the frozen results exactly: **on all 10 LoCoMo samples, at keep
ratios 0.3, 0.5 and 0.7, it assigns all 6 817 memories to the same anchors as
the locked 2026-09-15 plans — 20 451 / 20 451 identical assignments.**

---

## The idea in one page

Halving a memory store means choosing which memories to fuse. The obvious
answer — fuse the ones that look alike — is wrong for conversation, because the
memories a question actually needs are usually spread across sessions: "when did
Melanie finish the kiln she bought?" needs the purchase in May and the firing in
August, and those two sentences do not look alike at all.

So G1S groups by *narrative continuation* instead of by similarity.

**Step 3 picks the anchors.** Density peaks over the embedding geometry give
K = ⌈keep·N⌉ well-separated representatives, and every other memory provisionally
joins its nearest anchor. Call that partition π₀; it is the similarity-only
baseline, and the rest of the method only ever *moves* memories between these
same K groups.

**Step 4 rewrites the membership — this is the method.** Four ideas:

1. *Fused affinity with no tuned constant.* Each candidate pair scores both a
   semantic similarity (cosine) and an entity similarity (IDF-weighted overlap
   of the entities step 1 extracted). They are combined as
   `α·s_ent + (1−α)·cos` with `α = m·σ_s² / (m·σ_s² + σ_e²)`, where `m` is the
   shared entity mass of that pair and the two variances are measured over all
   candidates. Pairs that share a lot of rare entities lean on the entity
   signal; pairs that share nothing fall back to pure cosine. Nothing here is
   fitted.

2. *Anchor gating.* A pair is only worth considering if it beats what π₀
   already offers: `gain = affinity − cos(successor, its π₀ anchor)`. Edges with
   no positive gain are dropped, so chaining can only ever improve on the
   similarity baseline.

3. *Matching, so that chains are chains.* Candidate edges run forward in time
   within a 50-memory window, top-8 per successor. A maximum-weight bipartite
   matching then allows each memory at most one predecessor and one successor,
   which is what makes the result a set of disjoint paths rather than a
   hairball. Greedy is available as an ablation and is measurably worse.

4. *Whole-chain hosting.* Each chain is assigned to the anchor closest to it as
   a unit, so a narrative thread is never split across two merged memories.

**Step 5 merges each group in a single N-way call** — all members with their
timestamps in one prompt, which both costs `n−1` fewer calls than the pairwise
fold it replaces and stops the model from summarising its own summaries.

Steps 6–7 write the compressed store and measure it with the vendored Mem0
harness. They are evaluation, not method.

---

## Layout

```
g1s/
  g1s/
    __init__.py       the pipeline in a docstring
    settings.py       paths and endpoints; no credential lives in this package
    scope.py          the node universe of one sample; fixes the canonical order
    entities.py       grounding records -> IDF-weighted entity sets
    plan.py           THE artifact; every step reads and writes this one JSON
    llm.py            chat/embedding clients, prompt cache, embedding cache
    store.py          qdrant access (the only module that knows the layout)
    pipeline.py       file layout, ordering, resume -- no algorithm
    cli.py            python -m g1s
    judge.py          the official scorer, as its own process
    steps/
      s1_grounding.py    text            -> entities and relations   (LLM)
      s2_synonyms.py     labels          -> merged labels            (embeddings)
      s3_anchors.py      embeddings      -> anchors + pi0
      s4_chaining.py     pi0 + entities  -> regrouped partition      <-- the method
      s5_merge.py        each group      -> one memory               (LLM)
      s6_materialize.py  the plan        -> a compressed vector store
      s7_evaluate.py     that store      -> retrieval QA + scores
    tele/                  optional step 5: a compact encoding instead of prose
      facts.py             group text      -> checkable facts + triage  (LLM)
      compress.py          the compile / verify loop
      legend.py            teaches the QA reader the grammar
      prompts.py           the five frozen prompts
  tests/test_method.py   24 tests, no network, no store, no API key
  tests/test_tele.py     17 more, same rules
```

Every step reads and writes one plan JSON, so any step can be inspected,
diffed, or rerun on its own. Steps 1–5 import nothing from the vendored Mem0
tree; the vendor is touched only by step 7, behind a subprocess.

## Running it

```bash
pip install -r requirements.txt
cp config.example.json ~/.g1s.json     # then fill in real endpoints and keys

python -m g1s run --config ~/.g1s.json                  # the main line, 10 samples
python -m g1s run --config ~/.g1s.json --keep 0.3
python -m g1s run --until chaining                      # stop before spending merge tokens
python -m g1s run --tele                                # compact encodings instead of summaries
python -m g1s inspect --sample 0                        # what a finished plan looks like
python -m g1s compare --keeps 0.3 0.5 0.7               # finished arms, side by side
python -m pytest tests -q
```

Reuse the frozen grounding instead of re-running steps 1–2 (they depend only on
the sample, not on the arm):

```bash
python -m g1s run --grounding-dir results/locomo_fulluploaded_entity_grounding_v2rm_xhub15_20260914
```

Every artifact is resumable on its own: a finished step is detected and skipped,
so an interrupted run costs no repeated API calls.

### Ablations

The three switches that define the main line are also the ablation axes:

| flag | main line | alternatives |
|---|---|---|
| `--affinity` | `full` | `no_entity` (cosine only), `no_semantic` (entities only) |
| `--gating` | `anchor` | `none` (chain without checking against π₀) |
| `--matching` | `hungarian` | `greedy` |

Each combination writes to its own directory (`g1s_keep50_full_anchor_hungarian`),
so arms never overwrite one another.

## TELE — compact encodings instead of summaries (optional)

G1S halves the number of memories, but not the number of tokens. Measured over
all ten samples, step 5's natural-language summary comes out **larger than the
memories it replaces** — 1.07–1.12× the source tokens. The store holds fewer,
longer entries.

`--tele` swaps step 5 for a different writer. Instead of readable English, each
group is compiled into a compact encoding aimed at the reader *model*:

```
@2023-05-08 Melanie bought kiln -> installed in garage; ~fired yet
```

Dropping things is the point, so the module has to know what it dropped. Three
roles run over each group:

- **planner** — extract the group's atomic facts, each with a verification
  question, an `importance` label and an `inferable` flag.
- **compiler** — write the encoding under a soft token budget, given the facts
  and told which to protect and which to drop first.
- **verifier** — answer the planner's questions from the encoding *alone*
  (never the source), then judge which facts survived.

Facts that are important and not inferable are **required**. If the blind
reader cannot recover one, the compiler is sent back with a MUST-FIX list. At
most three rounds; the shortest clean round wins. A group whose best encoding is
no smaller than its source keeps its source text.

```bash
python -m g1s run --tele                          # keep 0.5, budget 0.80
python -m g1s run --tele --keep 0.3 --tele-target-ratio 0.80
```

TELE arms get their own directory (`g1s_keep50_..._hungarian_tele_t080`), so a
native arm and its TELE counterpart never share a plan or a store.

### What it costs

All ten samples, `--tele-target-ratio 0.80`, against the 61 273 source tokens of
the uncompressed library:

| keep | native step 5 | TELE | tokens saved | Δ accuracy | Δ BLEU-1 | Δ F1 |
|---|---|---|---|---|---|---|
| 0.3 | 67 914 (1.11×) | 35 384 (0.58×) | −47.9% | −6.4 pts | −0.083 | −0.094 |
| 0.5 | 68 660 (1.12×) | 41 937 (0.68×) | −38.9% | −2.0 pts | −0.069 | −0.072 |
| 0.7 | 65 482 (1.07×) | 41 406 (0.68×) | −36.8% | −0.7 pts | −0.061 | −0.065 |

It is a real trade, not a free win, which is why it is off by default: TELE buys
a third to a half of the stored text with some answer quality, and the trade
gets cheaper the more memories are kept.

Two things are worth knowing before running an arm:

- **The QA reader must be told the grammar.** `g1s.tele.legend` patches the
  decode legend into the evaluation overlay's answer prompt before step 7 runs.
  Without it the reader sees an encoding it has never been taught to read and
  scores it as noise — the method gets blamed for a prompting bug.
- **Singletons are compressed too**, unlike the native step 5, which passes
  one-member groups through untouched. A single memory is where the grammar pays
  best, and at keep 0.5 about half of all groups have one member.

These numbers come from the standalone `babel_runner.py` compiles of 2026-09-16,
whose algorithm this module reproduces. Two details differ and are worth
recording: those runs carried two different design tags for the same recipe
(`babel_grammar_v7_...` at keep 0.5, `babel_grammar_v11_...` at keep 0.3 and
0.7 — the tag was edited between runs and neither matched the code), and they
ordered a group's memories by raw timestamp string where this module uses the
same chronological order as step 5. Re-measure before quoting the table as this
package's own result.

## Configuration

Resolved in this order: explicit argument → environment variable → `--config`
JSON → repository-relative default. See `g1s/settings.py` for the full list and
`config.example.json` for the shape.

**No credential is stored in this package, and none should ever be added to it.**
`config.example.json` contains placeholders only. Keep the real file outside
version control.

## Reproducing the frozen results

```python
from pathlib import Path
from g1s import pipeline as p
from g1s.settings import Settings

s = Settings.load()
c = p.RunConfig(keep_ratio=0.5, grounding_dir=Path("results/locomo_..._v2rm_..._20260914"))
layout = p.Layout(s, c).make()
scope = p.load_scope(s.store_root, 0)
plan = p.step_chaining(p.step_anchors(scope, layout, c), scope, layout, c)
```

The resulting `final_plans/sample_000.json` has the same anchors and the same
group membership as
`results/eptraj_g1s_full_r2_keep50_20260915_kimi/tgdpc_bellman_global_temporal/final_plans/sample_000.json`.

Determinism is deliberate and load-bearing: exact ties are broken by node id,
float comparisons use `atol=1e-12`, entity masses are summed in sorted order,
and every group is emitted in node order. The plan carries a `plan_hash` and a
`final_plan_hash` so two runs can be compared without reading them.

## What is not here

Deliberately excluded, because none of it is on the main line:

- ~15 ablation arms that were run and rejected (k-means anchors, random anchors,
  min-max anchors, agglomerative assignment, Bellman route schedules, the
  `-log(affinity)` geometry variant, sparse-control arms)
- the pairwise left-fold merge schedule that the one-shot N-way merge replaced
- the `strict` judge prompt and the `existing` question-id mode
- the alias-retrieval branch, which was dead

The original scripts remain untouched where they were; nothing in this
refactor modifies or deletes them.
