"""Format-neutral DatasetSample JSONL; benchmark-specific formats live in plugins."""
from dataclasses import dataclass
from pathlib import Path

from memfolder.core import ContractError, DatasetSample, PluginSpec, loads
from memfolder.core.values import require
from memfolder.plugins import BuildContext

SPEC = PluginSpec(plugin_id='memfolder.dataset.jsonl.v1', role='data_loader',
                  provides=('benchmark.samples', 'benchmark.memory_evaluation_separation'))


@dataclass(frozen=True, kw_only=True)
class CanonicalDatasetLoader:
    path: Path
    max_samples: int = 1_000_000
    max_file_bytes: int = 2 * 1024**3
    spec = SPEC

    def __post_init__(self):
        for limit in (self.max_samples,self.max_file_bytes):
            require(type(limit) is int and limit > 0, 'Invalid benchmark input limit')

    @property
    def source_paths(self):
        return (self.path,)

    def samples(self):
        require(self.path.is_file() and self.path.stat().st_size <= self.max_file_bytes,
                'Missing/oversized canonical benchmark file')
        total, count = 0, 0
        with self.path.open('rb') as source:
            for line_number, raw in enumerate(source,1):
                total += len(raw)
                require(total <= self.max_file_bytes, 'Benchmark file-size limit exceeded')
                try:
                    text = raw.decode('utf-8-sig' if line_number == 1 else 'utf-8')
                except UnicodeError:
                    raise ContractError('Invalid benchmark UTF-8') from None
                if not text.strip():
                    continue
                require(count < self.max_samples, 'Benchmark sample limit exceeded')
                try:
                    sample = loads(text, expected=DatasetSample)
                except ContractError:
                    raise ContractError('Invalid DatasetSample envelope in benchmark JSONL') from None
                count += 1
                yield sample


def build(parameters, *, context: BuildContext):
    require(set(parameters) <= {'path','max_samples','max_file_bytes'} and 'path' in parameters,
            'Unknown/missing canonical benchmark parameters')
    return CanonicalDatasetLoader(path=context.path(parameters['path']),
        max_samples=parameters.get('max_samples',1_000_000), max_file_bytes=parameters.get('max_file_bytes',2*1024**3))


build.spec = SPEC
