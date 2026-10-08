"""Ported from the user-designated standard release; see docs/METHOD_PROVENANCE.json."""
FACT_EXTRACT = """From the memory entries below, extract the KEY facts as a numbered list, and for each fact write a short verification question with its expected answer. A reader should be able to answer the question IF AND ONLY IF the fact is recoverable from a compressed encoding.

Scale the fact count to the input size: about 1 atomic fact per 10 source tokens (min 2, max 12), one question per atomic fact. A short single memory deserves only 2-4 questions about its ONE core fact (e.g. who/what/when), not a decomposition into trivia. For each fact also provide:
- "importance": "high" for key events, final states, exact dates/numbers/names, entity bindings, negations; "med" for preferences, plans, relation directions, quantities; "low" for reasons, modifiers, emotional framing, superseded older states
- "inferable": true if a reader could infer this fact from the OTHER extracted facts or from common knowledge, else false
Do NOT include meta information such as the memory entries' own timestamps as facts. Keep each fact atomic.

Memories:
{lines}

Answer with JSON only: {{"facts": [{{"fact": "...", "question": "...", "answer": "...", "importance": "high|med|low", "inferable": true|false}}]}}"""

COMPRESS = """You are a memory compressor writing for another equally intelligent LLM, not for humans. Compress the {n} memory entries below into a compact token sequence that another LLM can decode WITHOUT any external codebook.

Fixed grammar (one fact per line):
- `@YYYY-MM-DD` ONLY when a fact itself contains time information; NEVER attach entry timestamps to timeless facts
- `A -> B` for state changes; `E: state` for attributes; `~` negation; `?` uncertain
- Exact entity full names; exact numbers/dates verbatim
- NEVER add `User:`/`She:` prefixes unless the source itself names the subject
- cl100k discipline: dotted fragments like `M.son.acc` are EXPENSIVE, never use them; common whole words are cheap
- Short single memories must come out strictly shorter than the source: keep verb + object, drop titles' authors, reasons, feelings. E.g. "Loved 'Becoming Nicole' by Amy Ellis Nutt" -> `loved 'Becoming Nicole'`

SOFT TOKEN BUDGET: about {target} tokens (source: {src}).

TRIAGE THE FACTS BEFORE ENCODING. The key facts are listed below with labels:
- MUST KEEP: [high] facts that are NOT inferable — key events, final states, exact names/dates/numbers, negations. These must survive verbatim-recoverable.
- DROP FIRST: facts marked [inferable] — the reader can re-derive them from the facts you keep or from common knowledge. Do not spend a single token on them.
- DROP IF TIGHT: [low] facts — reasons, modifiers, emotional framing, superseded older states.
- [med] facts: keep only while you are within budget.
Omitting a fact is allowed and expected; distorting or inventing one is not.

Key facts to triage:
{facts_list}

Output ONLY the encoding.

Memories:
{lines}"""

FEEDBACK = """

VERIFIER FEEDBACK on your previous attempt ({prev_tokens} tokens, budget {target}):
---
{prev}
---
{issues}
Re-encode by EDITING the previous encoding. Restore ONLY the facts listed as MUST-FIX; do not spend tokens on optional facts unless you are well under budget; if over budget, tighten wording or drop optional facts. Output ONLY the new encoding."""

ANSWER = """You see ONLY a compact memory encoding and a list of questions. The encoding uses this grammar: `@YYYY-MM-DD` = the fact happened on that date; `A -> B` = A changed into / transferred to B; `E: x` = entity E has attribute/state x; `~` = negation; `?` = uncertain/rumored; `;` and newlines separate facts; filler words are dropped but entity names, numbers, dates and relation directions are preserved. First silently decode each line into plain facts, then answer each question using ONLY what can be inferred from the decoded facts. If a question cannot be answered from the encoding, answer exactly "UNKNOWN". Do not guess.

Encoding:
{enc}

Questions:
{questions}

Answer with JSON only: {{"answers": ["...", "..."]}} with exactly {k} entries."""

JUDGE = """Reference key facts with expected answers:
{facts}

A blind reader who saw only the compressed encoding answered the verification questions as follows:
{answers}

For each item, decide whether the fact is recoverable from the encoding. Be LENIENT: accept semantically close or partial answers, accept answers that are reasonably inferable from the encoding even if wording differs; only exact numbers/dates/names must match. Mark false only when the answer is missing, "UNKNOWN", or contradicts the fact.
Answer with JSON only: {{"ok": [true, false, ...]}} with exactly {k} entries."""

ONESHOT = """
You are an intelligent memory summarization assistant. Please extract the core information from the following {n} memory entries and their timestamps, and generate a concise and coherent summary paragraph. If the memories contain relative time expressions, convert them into specific dates based on the corresponding timestamps. The summary length should be kept within the combined length of the original memories as much as possible. Output only the final summarized result, without any explanations.
{lines}
"""
