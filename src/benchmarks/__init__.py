"""Configurable benchmark streams, separate from native memory-store readers."""
from .benchmark_stream import (
    BenchmarkObserver,
    BenchmarkReport,
    BenchmarkStream,
    load_benchmark,
    load_benchmark_config,
)
from .dataset_loaders import CanonicalDatasetLoader

__all__ = ['BenchmarkObserver','BenchmarkReport','BenchmarkStream','load_benchmark','load_benchmark_config',
           'CanonicalDatasetLoader']

from . import benchmark_stream as _compat_benchmark_stream
from . import dataset_loaders as _compat_dataset_loaders
from ..component_runtime import install_module_aliases as _install_aliases
import sys as _sys
_install_aliases(_sys.modules[__name__], {
    'raw': _compat_dataset_loaders,
    'm3': _compat_dataset_loaders,
    'canonical': _compat_dataset_loaders,
    'composite': _compat_dataset_loaders,
    'loader': _compat_benchmark_stream,
})
