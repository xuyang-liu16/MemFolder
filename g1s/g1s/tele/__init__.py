"""TELE — compact-encoding text compression, as an optional G1S step 5.

G1S decides *which* memories are fused (steps 3-4) and then writes one natural
summary per group (step 5).  That summary is readable English, and readable
English is expensive: measured over all ten LoCoMo samples, the native N-way
summary is *larger* than the memories it replaces (1.07-1.12x the source
tokens).  The unit count halves; the token count does not.

TELE replaces the summary with a compact encoding written for the *reader
model* rather than for a human, under a fixed grammar::

    @YYYY-MM-DD   the fact happened on that date
    A -> B        A changed into / transferred to B
    E: x          entity E has attribute or state x
    ~             negation
    ?             uncertain or rumored

Compression that is free to drop things needs a way to know what it dropped, so
the module is a loop of three roles over each group:

    planner    extract the group's atomic facts, each with a verification
               question, an importance label and an "inferable" flag
    compiler   write the encoding under a soft token budget, told explicitly
               which facts to keep and which to drop first
    verifier   answer the planner's questions from the encoding *alone*, then
               judge which facts survived

Facts that are important and not inferable are *required*: if the blind reader
cannot recover one, the compiler is sent back with a MUST-FIX list.  At most
three rounds; the shortest clean round wins.

The reader at QA time must be told the grammar, or the encoding is just noise
to it -- see :mod:`g1s.tele.legend`, which patches the decode instructions into
the evaluation overlay's answer prompt.

What it buys, and what it costs (all ten samples, ``--target-ratio 0.80``):

===========  ================  ==============  ==========  =======  ======
keep ratio   stored tokens     vs native step 5  LLM acc     BLEU-1   F1
===========  ================  ==============  ==========  =======  ======
0.3          35 384  (0.58x)   -47.9%          -6.4 pts    -0.083   -0.094
0.5          41 937  (0.68x)   -38.9%          -2.0 pts    -0.069   -0.072
0.7          41 406  (0.68x)   -36.8%          -0.7 pts    -0.061   -0.065
===========  ================  ==============  ==========  =======  ======

"stored tokens" is relative to the 61 273 source tokens of the uncompressed
library.  The accuracy column is the honest cost: TELE trades a little answer
quality for a third to a half of the stored text, and the trade gets cheaper
the more memories are kept.  It is opt-in for exactly that reason.

Everything else in the pipeline is untouched: TELE consumes the same plan step
4 produces and writes the same ``final_text`` field step 6 reads.
"""
from __future__ import annotations

from .compress import TeleConfig, compress_group, compress_plan
from .facts import Fact, extract_facts, required_facts
from .legend import patch_overlay

__all__ = [
    "Fact",
    "TeleConfig",
    "compress_group",
    "compress_plan",
    "extract_facts",
    "patch_overlay",
    "required_facts",
]
