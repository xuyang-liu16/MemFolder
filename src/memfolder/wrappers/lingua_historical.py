"""Opt-in latest-contributor materialization for historical LLMLingua Mem0 QA."""
from dataclasses import dataclass

from ..core.values import require
from ..planning.common import spec
from .codecs import Mem0Codec
from .types import NativeArchive


class LatestContributorArchive(NativeArchive):
    def anchor(self, node):
        members = self.contributors(node)
        require(bool(members) and all(member.time_ranges for member in members),
                'Historical LLMLingua materialization requires source event times')
        require({r.start.clock for member in members for r in member.time_ranges}
                == {'unix_seconds'}, 'Historical Mem0 times must use unix_seconds')

        def key(member):
            raw_id = member.native.get('record', {}).get('id', member.native.get('id'))
            require(raw_id is not None, 'Historical Mem0 source point ID is missing')
            return max(r.start.value for r in member.time_ranges), str(raw_id)

        return max(members, key=key)


@dataclass(frozen=True)
class HistoricalLLMLinguaMem0Codec:
    space: object = None
    owner_field: str = 'user_id'
    framework_id = 'mem0'
    spec = spec('wrapper.llmlingua2_historical_mem0', 'native_codec')

    def encode(self, snapshot, archive, context):
        return Mem0Codec(space=self.space, owner_field=self.owner_field).encode(
            snapshot, LatestContributorArchive(archive.snapshot), context)
