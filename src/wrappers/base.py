"""A framework wrapper assembled from replaceable boundaries, with per-run state."""
from dataclasses import dataclass, replace
from pathlib import Path
import json
from ..core import (ArtifactRef, MaterializedView, FrozenMap, Snapshot, dumps, loads,
    validate_embedding_refresh, validate_projection, to_data)
from ..core.values import require
from ..planning.common import resolve, emit, spec
from .types import NativeArchive, NativePackage
from .topology import RedirectEdges
from .io import asset_refs, safe_path, file_digest, write_json


@dataclass(frozen=True)
class FrameworkWrapper:
    codec: object
    writer: object
    output_dir: Path
    projector: object = RedirectEdges()
    embedding_provider: object | None = None
    asset_copier: object | None = None
    archive: NativeArchive | None = None
    spec = spec('wrapper.framework', 'wrapper', diagnostics=('memfolder.wrapper.export','memfolder.wrapper.materialized'))

    def bind(self, snapshot):
        """A new run owns its original archive; the reusable plugin stays immutable."""
        return replace(self, archive=NativeArchive(snapshot))

    def for_output(self, directory):
        """Give every benchmark sample a fresh native output directory."""
        return replace(self,output_dir=Path(directory),archive=None)

    def export(self, source, context):
        require(source.initial_snapshot is not None, 'Load a canonical memory bank before compression')
        snapshot = source.initial_snapshot
        require(self.archive is None or self.archive.snapshot == snapshot, 'Bound wrapper belongs to another source')
        emit(context, self.spec.plugin_id, 'memfolder.wrapper.export', nodes=tuple(n.node_id for n in snapshot.records),
            framework=self.codec.framework_id, input_fingerprint=snapshot.fingerprint, records=len(snapshot.records))
        return snapshot

    async def project(self, source, plan, result, context):
        projected = await resolve(self.projector.project(source, plan, result, context))
        validate_projection(source, plan, result, projected)
        return projected

    async def materialize(self, snapshot, context):
        require(self.archive is not None, 'Bind the initial snapshot before native materialization')
        final = await resolve(self.embedding_provider.refresh(snapshot, context)) if self.embedding_provider else snapshot
        validate_embedding_refresh(snapshot, final)
        native = await resolve(self.codec.encode(final, self.archive, context))
        require(type(native) is NativePackage and native.snapshot_fingerprint == final.fingerprint
            and native.framework_id == self.codec.framework_id and set(native.node_id_map) == {n.node_id for n in final.records}, 'Native codec violated package identity')
        require(not asset_refs(final) or self.asset_copier is not None, 'Declare an asset root/copier for native artifacts')
        reserved = {'manifest.json','snapshot.json','source.snapshot.json','native.package.json','failure.json'}
        require(not reserved & {r.path for r in asset_refs(final)}, 'Artifact path collides with wrapper metadata')
        directory = Path(self.output_dir).resolve()
        require(not directory.exists(), 'Output directory already exists; select a new output')
        directory.mkdir(parents=True, exist_ok=False)
        try:
            with (directory / 'source.snapshot.json').open('x', encoding='utf-8') as stream: stream.write(dumps(self.archive.snapshot) + '\n')
            with (directory / 'snapshot.json').open('x', encoding='utf-8') as stream: stream.write(dumps(final) + '\n')
            with (directory / 'native.package.json').open('x', encoding='utf-8') as stream: stream.write(dumps(native) + '\n')
            if self.asset_copier: await resolve(self.asset_copier.copy(final, directory, context))
            names = await resolve(self.writer.write(native, directory, context))
            require(isinstance(names, (tuple,list)) and all(safe_path(directory,n).is_file() for n in names), 'Native writer did not return existing files')
            paths = sorted(p for p in directory.rglob('*') if p.is_file())
            files = {p.relative_to(directory).as_posix():file_digest(safe_path(directory,p.relative_to(directory).as_posix())) for p in paths}
            require('manifest.json' not in files and 'failure.json' not in files, 'Writer used a reserved metadata file')
            write_json(directory, 'manifest.json', {'schema':'memfolder.materialization.v1', 'status':'complete',
                'framework':native.framework_id, 'format':native.format_id, 'snapshot_fingerprint':final.fingerprint,
                'source_fingerprint':self.archive.snapshot.fingerprint, 'node_id_map':native.node_id_map,
                'reader_capabilities':getattr(self.writer,'reader_capabilities',()), 'native_files':names, 'files':files})
        except Exception:
            if not (directory / 'manifest.json').exists() and not (directory / 'failure.json').exists():
                write_json(directory, 'failure.json', {'status':'failed','message':'Materialization incomplete; choose a new output for retry.'})
            raise
        artifact = ArtifactRef(artifact_id='materialized:'+final.fingerprint, path='manifest.json',
            sha256=file_digest(directory / 'manifest.json'), media_type='application/json',
            schema_id='memfolder.materialization.v1', record_count=len(final.records))
        view = MaterializedView(framework_id=native.framework_id, snapshot=final, artifact=artifact,
            node_id_map=native.node_id_map, reader_capabilities=tuple(getattr(self.writer,'reader_capabilities',())))
        emit(context, self.spec.plugin_id, 'memfolder.wrapper.materialized', nodes=tuple(native.node_id_map),
            framework=native.framework_id, format=native.format_id, snapshot_fingerprint=final.fingerprint,
            node_id_map=native.node_id_map, artifact=to_data(artifact), files=len(files))
        return view


def verify_materialization(directory, *, artifact=None):
    """Verify completion and every file before opening a native reader."""
    directory = Path(directory).resolve(); path = directory / 'manifest.json'
    require(path.is_file() and not (directory/'failure.json').exists(), 'Incomplete native materialization')
    if artifact is not None:
        require(artifact.resolve(directory) == path and file_digest(path) == artifact.sha256, 'Manifest checksum mismatch')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    require(manifest.get('schema') == 'memfolder.materialization.v1' and manifest.get('status') == 'complete', 'Invalid materialization manifest')
    for name,digest in manifest['files'].items():
        file = safe_path(directory,name)
        require(file.is_file() and file_digest(file) == digest, 'Native artifact checksum mismatch')
    snapshot = loads((directory/'snapshot.json').read_text(encoding='utf-8'))
    source = loads((directory/'source.snapshot.json').read_text(encoding='utf-8'))
    native = loads((directory/'native.package.json').read_text(encoding='utf-8'))
    require(type(source) is Snapshot and source.fingerprint == manifest['source_fingerprint'] and type(snapshot) is Snapshot and type(native) is NativePackage and snapshot.fingerprint == native.snapshot_fingerprint
        == manifest['snapshot_fingerprint'] and native.framework_id == manifest['framework']
        and to_data(native.node_id_map) == manifest['node_id_map'] and set(native.node_id_map) == {n.node_id for n in snapshot.records}, 'Materialization identity mismatch')
    return snapshot, native
