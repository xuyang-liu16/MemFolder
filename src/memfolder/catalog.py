"""Application catalog. Core contracts and the registry have no builtin names."""
from .plugins import PluginRegistry


def default_registry(*, discover: bool = True) -> PluginRegistry:
    from .loading.factories import register_memory_loaders
    from .benchmarks.canonical import build
    registry = PluginRegistry()
    register_memory_loaders(registry)
    registry.register('dataset-jsonl', build)
    from .method_plugins import register_method_plugins
    register_method_plugins(registry)
    from .wrappers.factories import register_wrappers
    register_wrappers(registry)
    from .experiment_plugins import register_experiment_plugins
    register_experiment_plugins(registry)
    if discover:
        registry.discover()
    return registry
