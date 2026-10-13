"""Composable framework adaptation and native artifact publication."""
from .contracts import NativePackage, NativeArchive, NativeCodec, NativeWriter, AssetCopier
from .framework_wrapper import FrameworkWrapper, verify_materialization, WrappedRun, run_wrapped
from .framework_io import (
    Mem0Codec,
    MemOSCodec,
    M3Codec,
    Mem0PointsWriter,
    QdrantWriter,
    MemOSWriter,
    M3JsonWriter,
    M3PickleWriter,
    hydrate_m3,
    open_qdrant_view,
    load_memos_view,
    load_m3_view,
)
from .postprocessing import RedirectEdges, ChangedTextEmbeddings
from ..artifacts import VerifiedAssetCopier

__all__ = ['NativePackage','NativeArchive','NativeCodec','NativeWriter','AssetCopier','FrameworkWrapper',
    'verify_materialization','Mem0Codec','MemOSCodec','M3Codec','RedirectEdges','ChangedTextEmbeddings',
    'Mem0PointsWriter','QdrantWriter','MemOSWriter','M3JsonWriter','M3PickleWriter','VerifiedAssetCopier',
    'hydrate_m3','WrappedRun','run_wrapped','open_qdrant_view','load_memos_view','load_m3_view']

from .. import artifacts as _compat_artifacts
from . import contracts as _compat_contracts
from . import framework_io as _compat_framework_io
from . import framework_wrapper as _compat_framework_wrapper
from . import postprocessing as _compat_postprocessing
from . import wrapper_registry as _compat_wrapper_registry
from ..component_runtime import install_module_aliases as _install_aliases
import sys as _sys
_install_aliases(_sys.modules[__name__], {
    'types': _compat_contracts,
    'codecs': _compat_framework_io,
    'writers': _compat_framework_io,
    'm3_native': _compat_framework_io,
    'readers': _compat_framework_io,
    'base': _compat_framework_wrapper,
    'runtime': _compat_framework_wrapper,
    'embedding': _compat_postprocessing,
    'topology': _compat_postprocessing,
    'io': _compat_artifacts,
    'factories': _compat_wrapper_registry,
})
