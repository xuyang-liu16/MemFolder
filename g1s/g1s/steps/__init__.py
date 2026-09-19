"""The seven steps of the method, one module each.

Each module holds the algorithm as a pure function over :class:`~g1s.scope.Scope`
/ :class:`~g1s.plan.Plan` objects, plus whatever client it needs.  File layout,
resume logic and ordering live in :mod:`g1s.pipeline`, so that reading a step
tells you what it computes and nothing else.
"""
