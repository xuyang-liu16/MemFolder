"""Compose benchmark loaders without teaching the runner any dataset names."""
from dataclasses import dataclass
from ..planning.common import spec,resolve


@dataclass(frozen=True)
class CompositeDatasetLoader:
    loaders: tuple
    spec=spec('dataset.composite','data_loader')
    @property
    def source_paths(self):return tuple(p for loader in self.loaders for p in getattr(loader,'source_paths',()))
    async def samples(self):
        for loader in self.loaders:
            source=await resolve(loader.samples())
            try:
                if hasattr(source,'__aiter__'):
                    async for sample in source:yield sample
                else:
                    for sample in source:yield sample
            finally:
                if callable(getattr(source,'aclose',None)):await source.aclose()
                elif callable(getattr(source,'close',None)):source.close()
