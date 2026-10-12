"""Native file/SDK writers. All targets are new directories owned by the wrapper."""
from dataclasses import dataclass
from ..core import to_data
from ..core.values import require
from ..planning.common import spec
from .io import write_json


@dataclass(frozen=True)
class Mem0PointsWriter:
    spec = spec('wrapper.mem0_points', 'native_writer')
    reader_capabilities = ('mem0.points',)
    def write(self, package, directory, context):
        require(package.format_id == 'mem0.points.v1', 'Expected Mem0 points')
        return (write_json(directory, 'mem0.points.json', package.data),)


@dataclass(frozen=True)
class QdrantWriter:
    collection: str = 'mem0'
    dimension: int | None = None
    distance: str = 'cosine'
    batch_size: int = 256
    spec = spec('wrapper.qdrant', 'native_writer')
    reader_capabilities = ('mem0.qdrant.local', 'dense.vector.search', 'payload.filter')

    def write(self, package, directory, context):
        require(package.format_id == 'mem0.points.v1', 'Expected Mem0 points')
        require(self.collection and self.distance in ('cosine','dot','euclid','manhattan')
            and type(self.batch_size) is int and self.batch_size > 0, 'Invalid Qdrant configuration')
        points = to_data(package.data['points'])
        require(all(isinstance(p['vector'], list) and p['vector'] for p in points),
            'Qdrant writer supports unnamed dense vectors; select another writer for named/sparse slots')
        dimensions = {len(p['vector']) for p in points}
        require(len(dimensions) <= 1, 'Mixed Qdrant vector dimensions')
        width = next(iter(dimensions), self.dimension)
        require(type(width) is int and width > 0 and (self.dimension is None or width == self.dimension), 'Missing/mismatched Qdrant dimension')
        from qdrant_client import QdrantClient, models
        root = directory / 'qdrant'; require(not root.exists(), 'Qdrant output exists')
        client = QdrantClient(path=str(root))
        try:
            client.create_collection(self.collection, vectors_config=models.VectorParams(size=width,
                distance={'cosine':models.Distance.COSINE,'dot':models.Distance.DOT,'euclid':models.Distance.EUCLID,'manhattan':models.Distance.MANHATTAN}[self.distance]))
            for index in range(0, len(points), self.batch_size):
                batch = [models.PointStruct(id=int(p['id']) if p['id'].isdigit() else p['id'],
                    vector=p['vector'], payload=p['payload']) for p in points[index:index+self.batch_size]]
                client.upsert(self.collection, points=batch, wait=True)
            require(client.count(self.collection, exact=True).count == len(points), 'Qdrant output count mismatch')
        finally:
            client.close()
        metadata = write_json(directory, 'qdrant.reader.json', {'path':'qdrant','collection':self.collection,
            'dimension':width,'distance':self.distance,'format':'unnamed_dense'})
        return (metadata, *(p.relative_to(directory).as_posix() for p in sorted(root.rglob('*')) if p.is_file()))


@dataclass(frozen=True)
class MemOSWriter:
    spec = spec('wrapper.memos_files', 'native_writer')
    reader_capabilities = ('memos.load.into.configured.memory', 'memos.cube.component.files')

    def write(self, package, directory, context):
        require(package.format_id == 'memos.cube.text.v1', 'Expected MemOS cube')
        data = to_data(package.data); tree = data['backend'] == 'tree_text'
        filename = 'textual_memory.json'
        document = {'nodes':data['nodes'],'edges':data['edges']} if tree else data['nodes']
        files = [write_json(directory, filename, document)]
        components = {'text_mem': {'backend':data['backend'],'config':{'memory_filename':filename}}}
        for item in data['opaque']:
            native = item['native']; component = native.get('component') or native.get('memory_type')
            require(component in ('act_mem','para_mem'), 'Unknown MemOS opaque component')
            refs = item['assets']; require(len(refs) == 1, 'Opaque MemOS component needs one native artifact')
            components[component] = {'backend':native.get('backend','unknown'), 'config':{'memory_filename':refs[0]['path']}}
        files.append(write_json(directory, 'memfolder.memos.components.json', {'cube_id':data['cube_id'], **components,
            'usage':'Load files into an already configured MemOS memory/cube. Supply provider configuration separately.'}))
        return tuple(files)


@dataclass(frozen=True)
class M3JsonWriter:
    spec = spec('wrapper.m3_json', 'native_writer')
    reader_capabilities = ('m3.videograph.json', 'm3.hydrate.native.graph')
    def write(self, package, directory, context):
        require(package.format_id == 'm3.videograph.v1', 'Expected M3 VideoGraph')
        return (write_json(directory, 'videograph.json', package.data),)


@dataclass(frozen=True)
class M3PickleWriter:
    service: str = 'm3.graph_type'
    spec = spec('wrapper.m3_pickle', 'native_writer')
    reader_capabilities = ('m3.videograph.pickle', 'm3.native.text.search', 'm3.native.graph.traversal')
    def write(self, package, directory, context):
        require(package.format_id == 'm3.videograph.v1', 'Expected M3 VideoGraph')
        import pickle
        from .m3_native import hydrate_m3
        graph = hydrate_m3(package.data, context.services.require(self.service))
        with (directory / 'videograph.pkl').open('xb') as stream: pickle.dump(graph, stream, protocol=5)
        return ('videograph.pkl',)
