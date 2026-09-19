# Memory Compression — G1S

Entity-grounded trajectory chaining for conversational memory compression,
evaluated on LoCoMo.

**The method lives in [`g1s/`](./g1s). That directory is the project.**

Halving a memory store means choosing which memories to fuse. The obvious
answer — fuse the ones that look alike — is wrong for conversation, because the
memories a question actually needs are usually spread across sessions. G1S
therefore groups by *narrative continuation* rather than by similarity: density
peaks pick K anchors and a similarity-only baseline partition π₀, then chains
built from entity overlap and time re-assign membership among those same K
groups, and each group is merged in a single N-way call.

Read [`g1s/README.md`](./g1s/README.md) for the method in one page, the layout
of the seven steps, and how to run it.

```bash
cd g1s
pip install -r requirements.txt
cp config.example.json ~/.g1s.json      # then fill in real endpoints and keys
python -m g1s run --config ~/.g1s.json
python -m pytest tests -q
```

## Repository layout

```
g1s/        the method: seven steps, plus tests and a README
legacy/     the pre-G1S exploration (RecallFlow / MemForest, Jul 2026), frozen
.cursor/    shared editor rules and skills
```

Nothing outside `g1s/` is on the main line. See
[`legacy/README.md`](./legacy/README.md) for what the archive contains and why
it was kept.

## Status

The G1S main line is locked as of 2026-09-15:
`--affinity full --gating anchor --matching hungarian`, keep ratios 0.3 / 0.5 /
0.7 over all ten LoCoMo samples. The implementation in `g1s/` reproduces those
frozen plans exactly — 20 451 / 20 451 identical memory→anchor assignments.

No credential is stored in this repository. `g1s/config.example.json` contains
placeholders only; keep the real config outside version control.
