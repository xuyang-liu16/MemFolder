"""Opt-in latest-contributor materialization for historical LLMLingua Mem0 QA."""
from dataclasses import dataclass, replace
from copy import deepcopy
import re

from ..core import to_data, validate_embedding_refresh
from ..core.values import require
from ..planning.common import spec
from .codecs import allocate_ids, package, vectors
from .embedding import ChangedTextEmbeddings
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
    sample_index: int | None = None
    framework_id = 'mem0'
    spec = spec('wrapper.llmlingua2_historical_mem0', 'native_codec')

    def __post_init__(self):
        require(self.sample_index is None or
                (type(self.sample_index) is int and self.sample_index >= 0),
                'Declare a nonnegative historical LongMemEval sample index')

    def owner_id(self, raw):
        """Explicit common.py owner projection; no canonical scope is changed."""
        require(type(raw) is str and bool(raw), 'Supply a native owner ID')
        if self.sample_index is None:
            return raw
        if raw in (f'User_{self.sample_index}', f'Assistant_{self.sample_index}'):
            return raw
        match = re.match(r'^(user|assistant)_(.+)_(\d+)$', raw)
        require(match is not None, 'Owner does not match the recovered LongMemEval schema')
        return f"{'User' if match.group(1) == 'user' else 'Assistant'}_{self.sample_index}"

    def owner_ids(self, owners):
        """Apply the same projection to retrieval filters and QA speaker IDs."""
        require(type(owners) in (tuple, list) and bool(owners), 'Supply ordered QA owner IDs')
        mapped = tuple(self.owner_id(owner) for owner in owners)
        require(len(set(mapped)) == len(mapped), 'Historical QA owner projection is ambiguous')
        return mapped

    def encode(self, snapshot, archive, context):
        require(not snapshot.edges, 'Historical Mem0 projection requires a text vector store')
        latest = LatestContributorArchive(archive.snapshot)
        ids = allocate_ids(snapshot, latest, 'mem0')
        points=[]
        for node in snapshot.records:
            original=latest.anchor(node)
            require(original.native.get('framework')=='mem0', 'Supply original native Mem0 sources')
            raw=to_data(original.native.get('record',{}))
            require(isinstance(raw.get('payload'),dict), 'Historical codec requires original point payloads')
            require(bool(node.text) and node.text==node.text.strip() and
                    all(p.modality=='text' for p in node.parts), 'Supply normalized final Record text')
            payload=deepcopy(raw['payload'])
            payload['data']=node.text
            if self.sample_index is not None:
                payload['user_id']=self.owner_id(payload.get('user_id'))
            # Preserve source timestamps, owners, hashes and native payload
            # fields. Only explicitly declared historical owner conversion
            # differs; generic export normalizations belong to its codec.
            value=vectors(node,original,self.space)
            require(len(value)==1, 'Historical materialization needs one dense vector')
            points.append({'id':ids[node.node_id],'payload':payload,'vector':value[0]})
        # Original plan-specific compression_* annotations are not reconstructed
        # from canonical data; canonical lineage lives in the package sidecar.
        return package('mem0','mem0.points.v1',snapshot,latest,ids,{'points':points})


@dataclass(frozen=True)
class HistoricalAllTextEmbeddings:
    """Encode every final text through the declared provider, including unchanged text."""
    space: object
    service: str = 'embeddings'
    spec = spec('wrapper.llmlingua2_historical_all_embeddings', 'embedding_provider')

    async def refresh(self, snapshot, context):
        require(all(n.text and all(p.modality=='text' for p in n.parts)
                    for n in snapshot.records), 'Historical LLMLingua materialization requires text records')
        cleared=replace(snapshot,records=tuple(replace(n,embeddings=tuple(
            e for e in n.embeddings if e.space!=self.space)) for n in snapshot.records))
        after=await ChangedTextEmbeddings(space=self.space,service=self.service).refresh(cleared,context)
        validate_embedding_refresh(snapshot,after)
        return after
