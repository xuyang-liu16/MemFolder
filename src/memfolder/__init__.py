"""MemFolder public package. Core contracts have no backend/model dependencies."""
__version__ = "0.1.0.dev0"

# Lazy application APIs keep importing the core free of optional SDKs/providers.
def __getattr__(name):
    if name=='assemble_experiment':
        from .experiment import assemble_experiment
        return assemble_experiment
    if name=='FileRunReader':
        from .analysis import FileRunReader
        return FileRunReader
    raise AttributeError(name)
