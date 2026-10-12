"""Wrapper catalog; external codecs/writers use the existing plugin registry."""
from dataclasses import fields
from ..core.values import require
from ..plugins import PluginRequest
from ..method_plugins import Factory
from .base import FrameworkWrapper
from .codecs import Mem0Codec, MemOSCodec, M3Codec
from .lingua_historical import HistoricalLLMLinguaMem0Codec, HistoricalAllTextEmbeddings
from .embedding import ChangedTextEmbeddings
from .topology import RedirectEdges
from .writers import Mem0PointsWriter, QdrantWriter, MemOSWriter, M3JsonWriter, M3PickleWriter
from .io import VerifiedAssetCopier


class WrapperFactory:
    spec = FrameworkWrapper.spec
    def __init__(self, defaults=None): self.defaults = defaults or {}
    def __call__(self, parameters, *, context):
        values = {**self.defaults, **parameters}
        require(set(values) <= {'codec','writer','output_dir','projector','embedding_provider','asset_copier'}
            and {'codec','writer','output_dir'} <= set(values), 'Wrapper needs codec, writer and output_dir')
        for key,role in {'codec':'native_codec','writer':'native_writer','projector':'graph_projector',
            'embedding_provider':'embedding_provider','asset_copier':'asset_copier'}.items():
            if key in values and values[key] is not None:
                values[key] = context.registry.create(PluginRequest.from_mapping(values[key]),role=role,context=context,available=context.available).instance
        values['output_dir'] = context.path(values['output_dir'])
        return FrameworkWrapper(**values)


class AssetFactory:
    spec = VerifiedAssetCopier.spec
    def __call__(self, parameters, *, context):
        require(set(parameters) == {'root'}, 'Asset copier needs root')
        return VerifiedAssetCopier(context.path(parameters['root']))


def register_wrappers(registry):
    registry.register('framework-wrapper', WrapperFactory())
    for framework,codec,writer in (('mem0','mem0-codec','mem0-points-writer'),('memos','memos-codec','memos-writer'),('m3','m3-codec','m3-json-writer')):
        registry.register(framework+'-wrapper', WrapperFactory({'codec':{'plugin':codec},'writer':{'plugin':writer}}))
    for name,cls in {'mem0-codec':Mem0Codec,'memos-codec':MemOSCodec,'m3-codec':M3Codec,
        'llmlingua2-historical-mem0-codec':HistoricalLLMLinguaMem0Codec,
        'llmlingua2-historical-all-embeddings':HistoricalAllTextEmbeddings,
        'content-embeddings':ChangedTextEmbeddings,'redirect-edges':RedirectEdges,'mem0-points-writer':Mem0PointsWriter,
        'qdrant-writer':QdrantWriter,'memos-writer':MemOSWriter,'m3-json-writer':M3JsonWriter,'m3-pickle-writer':M3PickleWriter}.items():
        registry.register(name, Factory(cls))
    registry.register('verified-assets', AssetFactory())
