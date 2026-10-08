"""MemoryInput -> assembled engine -> native view; benchmark labels stay outside."""
from dataclasses import dataclass
from ..core import AlgorithmContext, BudgetRequest, PlanningRequest, NullDiagnostics, resolve_budget
from ..core.values import require
from ..compression import ServiceMap
from ..planning.common import resolve


@dataclass(frozen=True)
class WrappedRun:
    compression: object
    materialized: object
    @property
    def snapshot(self): return self.materialized.snapshot


async def run_wrapped(engine, wrapper, source, *, budgets=(), run_id='compression', features=(),
    mode='once', seed=0, services=None, diagnostics=None, max_rounds=256):
    services = services or ServiceMap(); diagnostics = diagnostics or NullDiagnostics()
    context = AlgorithmContext(services=services, diagnostics=diagnostics)
    snapshot = await resolve(wrapper.export(source, context))
    require(snapshot == source.initial_snapshot, 'Wrapper export must preserve the loaded source snapshot')
    session = wrapper.bind(snapshot) if callable(getattr(wrapper,'bind',None)) else wrapper
    resolved = tuple(resolve_budget(snapshot,b) if isinstance(b,BudgetRequest) else b for b in budgets)
    request = PlanningRequest(run_id=run_id, snapshot=snapshot, budgets=resolved,
        features=tuple(features), mode=mode, seed=seed)
    compression = await engine.run(request, services=services, diagnostics=diagnostics,
        projector=session, max_rounds=max_rounds)
    materialized = await resolve(session.materialize(compression.snapshot, context))
    require(materialized.framework_id and {n.node_id for n in materialized.snapshot.records} == {n.node_id for n in compression.snapshot.records}, 'Wrapper materialization changed record membership')
    from ..core import validate_embedding_refresh
    validate_embedding_refresh(compression.snapshot, materialized.snapshot)
    return WrappedRun(compression, materialized)
