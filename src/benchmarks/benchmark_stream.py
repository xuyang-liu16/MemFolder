"""Validated benchmark streams; downstream code receives public contracts only."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from ..core import API_VERSION, DatasetSample, MemoryInput, PluginBinding, PluginSpec, to_data
from ..core.values import require
from ..plugins import BuildContext, PluginRegistry, PluginRequest, read_plugin_request


@dataclass(frozen=True, kw_only=True)
class BenchmarkReport:
    binding: PluginBinding
    samples: int
    history_events: int
    memory_records: int
    questions: int

    def to_dict(self):
        return {'binding':to_data(self.binding), 'samples':self.samples, 'history_events':self.history_events,
                'memory_records':self.memory_records, 'questions':self.questions, 'status':'completed'}


class BenchmarkObserver(Protocol):
    """Memory-only observations; labels never pass through these callbacks."""
    def on_memory(self, memory: MemoryInput) -> None: ...
    def on_report(self, report: BenchmarkReport) -> None: ...


@dataclass(frozen=True, kw_only=True)
class BenchmarkStream:
    loader: object
    binding: PluginBinding
    observer: BenchmarkObserver | None = None
    allow_empty: bool = False

    def __post_init__(self):
        require(type(self.allow_empty) is bool, 'allow_empty must be boolean')
        spec = getattr(self.loader, 'spec', None)
        require(type(spec) is PluginSpec and spec.role == 'data_loader' and spec.api_version == API_VERSION,
                'Expected a v1 benchmark DataLoader')
        require(callable(getattr(self.loader, 'samples', None)), 'Benchmark loader lacks samples()')
        require((spec.plugin_id,spec.role,spec.api_version) ==
                (self.binding.plugin_id,self.binding.role,self.binding.api_version), 'Benchmark binding mismatch')

    def samples(self):
        # Keep only identities/counts in the driver; do not materialize the corpus.
        source = self.loader.samples()
        try:
            iterator = iter(source)
        except TypeError:
            from ..core import ContractError
            raise ContractError('This benchmark driver requires a synchronous sample iterator') from None
        seen, history, records, questions = set(), 0, 0, 0
        try:
            for sample in iterator:
                require(type(sample) is DatasetSample, 'Benchmark plugin must yield DatasetSample')
                require(sample.memory.sample.identity not in seen, 'Duplicate benchmark sample identity')
                seen.add(sample.memory.sample.identity)
                history += len(sample.memory.history)
                records += len(sample.memory.initial_snapshot.records) if sample.memory.initial_snapshot else 0
                questions += len(sample.evaluation.cases)
                if self.observer:
                    self.observer.on_memory(sample.memory)
                yield sample
            require(bool(seen) or self.allow_empty, 'Benchmark selected no samples')
            if self.observer:
                self.observer.on_report(BenchmarkReport(binding=self.binding, samples=len(seen),
                    history_events=history, memory_records=records, questions=questions))
        finally:
            close = getattr(iterator, 'close', None)
            if callable(close):
                close()


def load_benchmark(request: PluginRequest, *, registry: PluginRegistry | None = None,
                   context: BuildContext | None = None, observer=None, allow_empty=False) -> BenchmarkStream:
    if registry is None:
        from ..catalog import default_registry
        registry = default_registry()
    built = registry.create(request, role='data_loader', context=context)
    return BenchmarkStream(loader=built.instance, binding=built.binding, observer=observer, allow_empty=allow_empty)


def load_benchmark_config(path: str | Path, *, registry=None, observer=None, allow_empty=False) -> BenchmarkStream:
    request, context = read_plugin_request(path)
    return load_benchmark(request, registry=registry, context=context, observer=observer, allow_empty=allow_empty)
