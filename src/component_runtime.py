"""Shared plugin metadata, awaitable calls and diagnostic events."""

from __future__ import annotations
import inspect
from .core import DiagnosticLinks, DiagnosticRecord, FrozenMap, PluginSpec


async def resolve(value):
    """Both synchronous numerical stages and asynchronous contributed stages."""
    return await value if inspect.isawaitable(value) else value


def spec(name, role, *, actions=(), modes=('once', 'repeat'), diagnostics=()):
    return PluginSpec(plugin_id='memfolder.' + name, role=role, action_kinds=actions,
                      execution_modes=modes, diagnostic_schemas=diagnostics)


def emit(context, component, schema, *, nodes=(), candidates=(), actions=(), questions=(), **data):
    if context.diagnostics.enabled(schema):
        context.diagnostics.emit(DiagnosticRecord(schema=schema, version=1,
            component_id=component, links=DiagnosticLinks(node_ids=tuple(nodes),
                candidate_ids=tuple(candidates), action_ids=tuple(actions),question_ids=tuple(questions)), data=FrozenMap(data)))


def install_module_aliases(package, aliases):
    """Preserve old import paths without keeping duplicate implementation files."""
    import sys
    for name, module in aliases.items():
        sys.modules[package.__name__ + '.' + name] = module
        setattr(package, name, module)
