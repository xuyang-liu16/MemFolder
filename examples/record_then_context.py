"""Compose two independent stages on the final Record snapshot.

Call from a program that supplies a PlanningRequest and chat/embedding/LLMLingua
services. This example does not load a dataset, download weights or call an API
on import. Context compression has its own configuration and source budget.
"""
from dataclasses import replace
from pathlib import Path
import json
from memfolder.assembly import assemble
from memfolder.lingua_historical import HistoricalLLMLingua2Service

RECIPES = Path(__file__).parent / 'recipes'


async def record_then_context(request, *, services, context_method='llmlingua2'):
    configurations = {'llmlingua2': 'llmlingua2-post-record.json',
                      'contextfolder': 'contextfolder-post-record.json'}
    if context_method not in configurations:
        raise ValueError('Choose llmlingua2 or contextfolder')
    record_config = json.loads((RECIPES / 'tome-text.json').read_text(encoding='utf-8'))
    context_config = json.loads((RECIPES / configurations[context_method]).read_text(encoding='utf-8'))
    record = await assemble(record_config).engine.run(replace(request, mode='repeat'), services=services)
    # This new stage deliberately has no Record node budget or previous planner
    # state. It rewrites each final current record once and does not regroup it.
    context_request = replace(request, snapshot=record.snapshot, mode='once',
                              budgets=(), state=None, features=(), round_index=0)
    context = await assemble(context_config).engine.run(context_request, services=services)
    return record, context


def local_lingua_service():
    """Optional service for caller-provided ServiceMap; loading is lazy."""
    return HistoricalLLMLingua2Service()
