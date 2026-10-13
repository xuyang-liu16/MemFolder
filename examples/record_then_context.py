"""Compose two independent stages on the final Record snapshot.

Call from a program that supplies a PlanningRequest and chat/embedding/LLMLingua
services. This example does not load a dataset, download weights or call an API
on import. Context compression has its own configuration and source budget.
"""
from dataclasses import replace
from pathlib import Path
import json
from memfolder.assembly import assemble
from memfolder.core import to_data
from memfolder.core.values import require
from memfolder.services import TokenBudgetLLMLingua2Service

RECIPES = Path(__file__).parent / 'recipes'


async def record_then_context(request, *, services, context_method='llmlingua2', embedding_space=None):
    configurations = {'llmlingua2': 'llmlingua2-post-record.json',
                      'contextfolder': 'contextfolder-post-record.json'}
    if context_method not in configurations:
        raise ValueError('Choose llmlingua2 or contextfolder')
    record_config = json.loads((RECIPES / 'tome-text.json').read_text(encoding='utf-8'))
    if embedding_space is None:
        # Select declared metadata, never infer a model from vector dimensions.
        batches=[batch for batch in request.features if batch.name=='semantic']
        require(len(batches)<=1,'Declare an unambiguous semantic feature space')
        spaces=({batches[0].space} if batches and batches[0].space is not None else
                {e.space for node in request.snapshot.records for e in node.embeddings
                 if e.source_fingerprint==node.content_fingerprint})
        require(len(spaces)==1,'Supply embedding_space for raw text input')
        embedding_space=next(iter(spaces))
    record_config['features']=[{'plugin':'semantic-encoder',
        'parameters':{'space':to_data(embedding_space)}}]
    context_config = json.loads((RECIPES / configurations[context_method]).read_text(encoding='utf-8'))
    record_request=replace(request,mode='repeat',
        features=tuple(batch for batch in request.features if batch.name!='semantic'))
    record = await assemble(record_config).engine.run(record_request, services=services)
    # This new stage deliberately has no Record node budget or previous planner
    # state. It rewrites each final current record once and does not regroup it.
    context_request = replace(request, snapshot=record.snapshot, mode='once',
                              budgets=(), state=None, features=(), round_index=0)
    context = await assemble(context_config).engine.run(context_request, services=services)
    return record, context


def local_lingua_service():
    """Optional service for caller-provided ServiceMap; loading is lazy."""
    return TokenBudgetLLMLingua2Service()
