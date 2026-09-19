"""G1S — entity-grounded trajectory chaining for conversational memory compression.

The pipeline is a straight line.  Each step is one module under ``g1s.steps``
and each step's only contract with the next is a JSON *plan* file (see
``g1s.plan``):

    step 1  grounding      raw memories        -> per-node entity sets      (LLM)
    step 2  synonyms       entity sets         -> merged entity vocabulary  (embeddings)
    step 3  anchors        embeddings          -> anchors + baseline partition pi0
    step 4  chaining       pi0 + entities      -> regrouped partition       (the method)
    step 5  merge          regrouped partition -> one text per group        (LLM)
    step 6  materialize    texts               -> a compressed vector store
    step 7  evaluate       vector store        -> retrieval QA + judge scores

Steps 1-5 are pure method.  Steps 6-7 are the evaluation harness and are the
only place where the vendored Mem0 evaluation code is touched.
"""

__version__ = "1.0.0"
