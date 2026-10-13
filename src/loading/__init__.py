"""Memory-library loading. No SDKs, models, or database connections on import."""
from .contracts import (
    FormatAdapter,
    ImportIssue,
    ImportObserver,
    LoadedLibrary,
    LoadOptions,
    LoadReport,
    MemoryLibraryLoader,
    NativeEdge,
    NativeLibrary,
    NativeRecord,
    SourceInfo,
)
from .source_readers import SourceDocument, read_json, read_local_qdrant, read_qdrant, read_qdrant_sqlite
from .memory_adapters import M3Adapter, Mem0Adapter, Mem0LegacyNodesAdapter, MemOSAdapter
from .memory_libraries import (
    Importer,
    NativeVectorSet,
    attach_evaluation,
    native_vector_sets,
    normalize,
    JsonMemoryLoader,
    M3GraphLoader,
    MemOSCubeLoader,
    load_library,
    load_m3,
    load_mem0,
    load_mem0_client,
    load_mem0_legacy_nodes,
    load_mem0_qdrant,
    load_mem0_sqlite,
    load_memos,
    load_memos_cube,
    save_library,
)
from types import ModuleType as _ModuleType
__all__ = [name for name, value in globals().items() if not name.startswith('_') and not isinstance(value, _ModuleType)]

from . import contracts as _compat_contracts
from . import loader_registry as _compat_loader_registry
from . import memory_adapters as _compat_memory_adapters
from . import memory_libraries as _compat_memory_libraries
from . import source_readers as _compat_source_readers
from . import validation as _compat_validation
from ..component_runtime import install_module_aliases as _install_aliases
import sys as _sys
_install_aliases(_sys.modules[__name__], {
    'types': _compat_contracts,
    'common': _compat_validation,
    'readers': _compat_source_readers,
    'qdrant_sqlite': _compat_source_readers,
    'm3_pickle': _compat_source_readers,
    'adapters': _compat_memory_adapters,
    'importer': _compat_memory_libraries,
    'loaders': _compat_memory_libraries,
    'factories': _compat_loader_registry,
})
