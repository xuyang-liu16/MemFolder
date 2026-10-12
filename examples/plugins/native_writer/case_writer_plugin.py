"""An independently installable writer adds case analysis without core edits."""
from dataclasses import dataclass
from memfolder.core import PluginSpec, to_data
from memfolder.core.values import require
from memfolder.plugins import PluginRequest
from memfolder.planning.common import resolve
from memfolder.wrappers.io import write_json

SPEC=PluginSpec(plugin_id='example.case_writer',role='native_writer')

@dataclass(frozen=True)
class CaseWriter:
    base_writer: object
    spec=SPEC
    @property
    def reader_capabilities(self):return (*getattr(self.base_writer,'reader_capabilities',()),'case.lineage.json')
    async def write(self, package, directory, context):
        files=await resolve(self.base_writer.write(package,directory,context))
        file=write_json(directory,'cases.json',{'snapshot_fingerprint':package.snapshot_fingerprint,
            'node_id_map':package.node_id_map,'lineage':package.lineage,
            'source_snapshot':'source.snapshot.json','final_snapshot':'snapshot.json'})
        return (*files,file)

def build(parameters, *, context):
    require(set(parameters)<={'base_writer'},'Unknown case writer parameter')
    request=PluginRequest.from_mapping(parameters.get('base_writer',{'plugin':'mem0-points-writer'}))
    writer=context.registry.create(request,role='native_writer',context=context,available=context.available).instance
    return CaseWriter(writer)
build.spec=SPEC
