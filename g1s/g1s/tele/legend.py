"""Teach the QA reader the grammar, or the encoding is noise to it.

Step 7 answers questions with the vendored Mem0 harness, whose answer prompt
assumes the retrieved memories are plain English.  Hand it ``@2023-05-08
kiln -> installed; ~fired`` and it will do its best with a string it has never
been told how to read -- which is how a compression method gets blamed for a
prompting bug.

So before the harness runs, one decode legend is inserted into its answer
prompts: the same legend the verifier's blind reader saw during compilation.
The two must stay in step; if the reader at QA time understands less of the
grammar than the reader that signed off on the encoding, the verification was
measuring the wrong thing.

The patch applies to the *overlay* -- the throwaway copy of the vendor tree
that :func:`g1s.steps.s7_evaluate.prepare_overlay` builds inside the run
directory -- so the vendored source itself is never modified.
"""
from __future__ import annotations

from pathlib import Path

from ..steps.s7_evaluate import OVERLAY_NAME

#: Presence of this phrase means the overlay is already patched.
MARKER = "COMPACT ENCODED MEMORIES"

#: Inserted immediately before the harness's own instruction block, so the
#: reader decodes first and then follows the unchanged instructions.  The
#: leading indentation matches the prompt's, which is a triple-quoted string in
#: an indented context.
ANCHOR = "    # INSTRUCTIONS:"

LEGEND = """
    # IMPORTANT - COMPACT ENCODED MEMORIES:
    Some memories are stored in a compact machine-oriented encoding rather than plain
    English. BEFORE answering, silently decode each memory into the facts it encodes.
    Decoding legend: `@YYYY-MM-DD` = the fact happened on that date; `A -> B` = A
    changed into / transferred to B; `E: x` = entity E has attribute or state x;
    `~` = negation; `?` = uncertain or rumored; `;` and newlines separate facts;
    compact wording drops filler words but always preserves entity names, exact
    numbers, dates and relation directions. First expand each encoded line into its
    plain-English facts, then answer strictly from the decoded facts.
"""


def patch_overlay(workdir: Path) -> bool:
    """Add the decode legend to the overlay's answer prompts.

    ``workdir`` is the run directory the overlay lives in, i.e. what was passed
    to ``prepare_overlay``.  Returns True if the file was changed, False if it
    was already patched -- idempotent, because a resumed run reuses the overlay.
    """
    path = Path(workdir) / OVERLAY_NAME / "prompts.py"
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        return False
    if ANCHOR not in text:
        raise RuntimeError(
            f"{path}: no '# INSTRUCTIONS:' block to anchor the decode legend to. "
            "The vendored answer prompt changed shape; re-check where the legend belongs "
            "before running a TELE arm, because an unpatched reader silently scores "
            "encodings as gibberish."
        )
    path.write_text(text.replace(ANCHOR, LEGEND + "\n" + ANCHOR), encoding="utf-8")
    return True
