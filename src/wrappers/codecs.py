"""Framework-native schemas, without importing framework SDKs."""
from dataclasses import dataclass
from collections import defaultdict
from copy import deepcopy
from hashlib import md5
from uuid import UUID, uuid5, NAMESPACE_URL
from ..core import FrozenMap, to_data, fingerprint
from ..core.values import require
from ..planning.common import spec
from .types import NativePackage


VECTOR_FIELDS = ('embedding', 'embedding_1024', 'embedding_3072', 'embedding_768')


def template(node, archive, framework):
    original = archive.anchor(node)
    return original if original.native.get('framework') == framework else None


def changed(node, original):
    return original is None or node.content_fingerprint != original.content_fingerprint or node.origins != original.origins


def vectors(node, original, space=None):
    selected = [e for e in node.embeddings if space is None or e.space == space]
    if len(selected) == 1 and selected[0].values:
        return [list(selected[0].values)]
    if changed(node, original):
        selected = [e for e in node.embeddings if space is None or e.space == space]
        require(len(selected) == 1 and bool(selected[0].values), 'Changed content requires one explicit refreshed content embedding')
        return [list(selected[0].values)]
    slots = node.native.get('vectors', {})
    nonempty = [values for values in slots.values() if values]
    if nonempty:
        require(len(nonempty) == 1, 'Use a multi-slot codec for multiple native dense vector spaces')
        if space is not None:
            require(all(len(v) == space.dimension for v in nonempty[0]), 'Declared native embedding dimension mismatch')
        return to_data(nonempty[0])
    selected = [e for e in node.embeddings if space is None or e.space == space]
    require(len(selected) == 1 and bool(selected[0].values), 'Native output needs a declared inline content vector')
    return [list(selected[0].values)]


def allocate_ids(snapshot, archive, framework, *, numeric=False):
    result = {}
    used = set()
    for node in snapshot.records:
        original = template(node, archive, framework)
        if original is None:
            continue
        value = str(original.native['id'])
        try:
            valid = int(value) >= 0 if numeric else (framework == 'mem0' and value.isdigit() and int(value) < 2**64) or bool(UUID(value))
        except (ValueError, TypeError):
            valid = False
        if valid and value not in used:
            result[node.node_id] = value
            used.add(value)
    next_id = max((int(v) for v in used), default=-1) + 1 if numeric else 0
    for node in snapshot.records:
        if node.node_id in result:
            continue
        value = str(next_id) if numeric else str(uuid5(NAMESPACE_URL, framework + ':' + fingerprint((node.scope, node.node_id))))
        require(value not in used, 'Native ID collision')
        result[node.node_id] = value
        used.add(value)
        next_id += 1
    return result


def lineage(snapshot, archive):
    return {n.node_id: {'origins': [to_data(o) for o in n.origins],
        'source_node_ids': [r.node_id for r in archive.contributors(n)],
        'content_fingerprint': n.content_fingerprint, 'scope':to_data(n.scope), 'kind':n.kind,
        'time_ranges':to_data(n.time_ranges), 'available_at':to_data(n.available_at),
        'expires_at':to_data(n.expires_at), 'retention':to_data(n.retention)} for n in snapshot.records}


def source_metadata(archive, framework):
    return [to_data(item.get('metadata', {})) for item in
        archive.snapshot.extensions.get('memfolder.import', {}).get('sources', {}).values()
        if item.get('source', {}).get('framework') == framework]


def package(framework, format_id, snapshot, archive, ids, data):
    require(set(ids) == {n.node_id for n in snapshot.records} and len(set(ids.values())) == len(ids), 'Native ID map must be bijective')
    return NativePackage(framework_id=framework, format_id=format_id,
        snapshot_fingerprint=snapshot.fingerprint, node_id_map=FrozenMap(ids),
        data=FrozenMap(data), lineage=FrozenMap(lineage(snapshot, archive)))


@dataclass(frozen=True)
class Mem0Codec:
    space: object | None = None
    owner_field: str = 'user_id'
    framework_id = 'mem0'
    spec = spec('wrapper.mem0_codec', 'native_codec')

    def encode(self, snapshot, archive, context):
        require(not snapshot.edges, 'Mem0 vector-store codec cannot represent memory graph relations; use a graph-aware codec')
        require(self.owner_field in ('user_id', 'agent_id', 'run_id'), 'Unknown Mem0 owner field')
        ids = allocate_ids(snapshot, archive, 'mem0')
        provenance = lineage(snapshot, archive)
        points = []
        for node in snapshot.records:
            require(bool(node.text) and all(p.modality == 'text' for p in node.parts), 'Mem0 text codec needs a multimodal extension for this record')
            original = template(node, archive, 'mem0')
            raw = to_data(original.native['record']) if original else {}
            payload = deepcopy(raw.get('payload', raw))
            if 'source' in raw and 'node_id' in raw:  # historical node export
                payload = {'data': node.text, 'user_id': raw['source']['user_id'], 'timestamp': raw.get('timestamp')}
            payload.pop('id', None)
            payload.pop('embedding', None)
            for key in ('user_id','agent_id','run_id'):
                if not payload.get(key) and (payload.get('metadata') or {}).get(key):
                    payload[key] = payload['metadata'][key]
            if not any(payload.get(k) or (payload.get('metadata') or {}).get(k) for k in ('user_id', 'agent_id', 'run_id')):
                payload[self.owner_field] = node.scope.sample_id
            if changed(node, original):
                for key in ('data', 'memory', 'text', 'hash', 'text_lemmatized', 'embedding'):
                    payload.pop(key, None)
                payload['data'] = node.text
                payload['hash'] = md5(node.text.encode('utf-8')).hexdigest()
                for key in ('embedding', 'hash', 'text_lemmatized'):
                    if isinstance(payload.get('metadata'), dict): payload['metadata'].pop(key, None)
                payload['memfolder'] = provenance[node.node_id]
            payload['data'] = node.text
            if node.extensions.get('memfolder.timestamp_policy') == 'latest':
                from ..operators.text import timestamp
                payload['timestamp'] = timestamp(node, 'latest')
            for alias in ('memory','text'):payload.pop(alias,None)
            if node.expires_at is not None:
                require(node.expires_at.clock == 'unix_seconds', 'Mem0 expiration requires wall-clock seconds')
                from datetime import datetime, timezone, time
                expires = datetime.fromtimestamp(node.expires_at.value, timezone.utc)
                require(expires.time() == time(0), 'Mem0 date expiration cannot represent sub-day precision; use a TTL-aware codec')
                payload['expiration_date'] = expires.date().isoformat()
            # Sparse slots are retained only for unchanged text. Changed sparse
            # text features must be regenerated by a separately configured codec.
            native_vector = raw.get('vector')
            refreshed = original is None or node.embeddings != original.embeddings
            if not changed(node, original) and not refreshed and isinstance(native_vector, dict):
                value = native_vector
            else:
                require(not isinstance(native_vector, dict), 'Changed named/sparse Mem0 slots need a slot-aware codec; cannot discard native vector slots')
                value = vectors(node, original, self.space)
                require(len(value) == 1, 'Default Mem0 codec expects one vector per memory')
                if self.space is not None:
                    require(len(value[0]) == self.space.dimension, 'Mem0 content/source vector dimensions disagree')
                value = value[0]
            points.append({'id': ids[node.node_id], 'payload': payload, 'vector': value})
        return package('mem0', 'mem0.points.v1', snapshot, archive, ids, {'points': points})


@dataclass(frozen=True)
class MemOSCodec:
    cube_id: str | None = None
    backend: str = 'auto'
    require_vectors: bool = False
    space: object | None = None
    framework_id = 'memos'
    spec = spec('wrapper.memos_codec', 'native_codec')

    def encode(self, snapshot, archive, context):
        require(self.backend in ('auto', 'naive_text', 'tree_text'), 'Unknown MemOS text backend')
        ids = allocate_ids(snapshot, archive, 'memos')
        provenance = lineage(snapshot, archive)
        metadata = source_metadata(archive, 'memos')
        source_components = {str(v.get('cube_config', {}).get('component', 'text_mem')) for v in metadata}
        require(not {'pref_mem'} & source_components, 'Use a preference-aware codec to preserve a combined text/preference cube')
        cubes = {n.native.get('namespace', '').removeprefix('cube:').split(':')[0] for n in archive.snapshot.records
            if n.native.get('framework') == 'memos'}
        cubes.discard('')
        require(len(cubes) <= 1 or self.cube_id is not None, 'Materialize MemOS cubes separately or declare target cube identity')
        cube = self.cube_id or next(iter(cubes), snapshot.records[0].scope.sample_id if snapshot.records else 'empty')
        nodes, opaque = [], []
        for node in snapshot.records:
            original = template(node, archive, 'memos')
            if not node.text:
                require(not node.eligible and original is not None, 'Unknown opaque MemOS record')
                opaque.append({'node_id': node.node_id, 'native': to_data(original.native['record']),
                    'assets': [to_data(p.artifact) for p in node.parts if p.artifact]})
                continue
            require(all(p.modality == 'text' for p in node.parts), 'Use a multimodal MemOS codec for mixed content')
            row = to_data(original.native['record']) if original else {}
            meta = deepcopy(row.get('metadata', {}))
            # Official TextualMemoryItem forbids extra top-level fields.
            for key in VECTOR_FIELDS:
                if key in row and key not in meta:
                    meta[key] = row[key]
            meta['cube_id'] = cube
            refreshed = original is None or node.embeddings != original.embeddings
            if changed(node, original) or refreshed:
                slots = [key for key in VECTOR_FIELDS if meta.get(key)]
                require(len(slots) <= 1, 'Multiple MemOS vector slots require a slot-aware codec for changed content/embeddings')
            if changed(node, original):
                for key in VECTOR_FIELDS:
                    meta.pop(key, None)
                meta.pop('embedding_model', None)
                meta['memfolder'] = provenance[node.node_id]
                # Only an explicitly selected native time profile updates its
                # native clock. Other backend timestamp behavior is unchanged.
                source=original.extensions.get('memfolder.temporal_source',{}) if original else {}
                policy=node.extensions.get('memfolder.timestamp_policy')
                if source and policy in ('earliest','latest'):
                    from ..operators.text import timestamp
                    from ..loading.common import field_value
                    value=timestamp(node,policy)
                    selected=source.get('selected_field')
                    raw=field_value(original.native['record'],selected) if selected else None
                    if raw is None and selected:
                        raw=field_value(original.native['record'].get('metadata',{}),selected)
                    if type(raw) in (int,float) and node.time_ranges:
                        choose=max if policy=='latest' else min
                        value=choose(r.start.value for r in node.time_ranges)
                    meta['timestamp']=value
                    if selected:
                        keys=selected.removeprefix('metadata.').split('.')
                        target=meta
                        for key in keys[:-1]:
                            target=target.setdefault(key,{})
                            require(type(target) is dict,'Native time field conflicts with metadata structure')
                        target[keys[-1]]=value
                if self.require_vectors or node.embeddings:
                    value = vectors(node, original, self.space)
                    require(len(value) == 1, 'MemOS text codec requires one refreshed vector')
                    meta['embedding'] = value[0]
            elif self.require_vectors:
                vectors(node, original, self.space)
            if refreshed and any(e.values and (self.space is None or e.space == self.space) for e in node.embeddings):
                for key in VECTOR_FIELDS: meta.pop(key, None)
                meta['embedding'] = vectors(node, original, self.space)[0]
            nodes.append({'id': ids[node.node_id], 'memory': node.text, 'metadata': meta})
        text_ids = {row['id'] for row in nodes}
        edges = []
        for edge in snapshot.edges:
            require(ids[edge.source_id] in text_ids and ids[edge.target_id] in text_ids, 'Text MemOS graph cannot attach an opaque artifact node')
            edges.append({'source': ids[edge.source_id], 'target': ids[edge.target_id], 'type': edge.relation,
                'weight': edge.weight, 'directed': edge.directed})
        # Preserve known metadata pointers, redirect absorbed IDs, remove dropped
        # IDs. Unknown reference schemas require a contributor-owned codec.
        remap = {}
        for node in snapshot.records:
            for original in archive.contributors(node):
                if original.native.get('framework') == 'memos':
                    remap[str(original.native['id'])] = ids[node.node_id]
        for row in nodes:
            for key in ('parent_id', 'following_id', 'preceding_id'):
                if key in row['metadata']:
                    mapped = remap.get(str(row['metadata'][key]))
                    row['metadata'][key] = mapped if mapped != row['id'] else None
            for key in ('children_ids', 'summary_ids', 'related_ids'):
                if key in row['metadata']:
                    row['metadata'][key] = list(dict.fromkeys(remap[str(i)] for i in row['metadata'][key] if str(i) in remap and remap[str(i)] != row['id']))
        source_tree = bool(archive.snapshot.edges) or any(v.get('cube_config', {}).get('backend') == 'tree_text' for v in metadata)
        backend = ('tree_text' if edges or source_tree else 'naive_text') if self.backend == 'auto' else self.backend
        require(backend != 'naive_text' or not edges, 'Naive MemOS cannot represent tree edges')
        return package('memos', 'memos.cube.text.v1', snapshot, archive, ids,
            {'cube_id': cube, 'backend': backend, 'nodes': nodes, 'edges': edges, 'opaque': opaque})


@dataclass(frozen=True)
class M3Codec:
    video_id: str | None = None
    space: object | None = None
    framework_id = 'm3'
    spec = spec('wrapper.m3_codec', 'native_codec')

    def encode(self, snapshot, archive, context):
        ids = allocate_ids(snapshot, archive, 'm3', numeric=True)
        provenance = lineage(snapshot, archive)
        metadata = source_metadata(archive, 'm3')
        require(len(metadata) <= 1, 'An M3 output must represent one video graph')
        data = deepcopy(metadata[0]) if metadata else {}
        videos = {n.native.get('namespace', '').removeprefix('video:') for n in archive.snapshot.records if n.native.get('framework') == 'm3'}
        video = self.video_id or next(iter(videos), snapshot.records[0].scope.sample_id if snapshot.records else 'empty')
        require(len(videos) <= 1, 'M3 wrapper cannot combine video namespaces')
        nodes = []
        for node in snapshot.records:
            original = template(node, archive, 'm3')
            row = deepcopy(to_data(original.native['record'])) if original else {}
            row['id'] = int(ids[node.node_id])
            if changed(node, original):
                require(bool(node.text) and all(p.modality == 'text' for p in node.parts), 'Changed M3 media needs a multimodal codec')
                row['type'] = node.kind if node.kind in ('episodic', 'semantic') else row.get('type', 'episodic')
                meta = deepcopy(row.get('metadata', {}))
                require(node.scope.partition_id.startswith('clip:'), 'M3 text output needs an explicit clip scope')
                clip = int(node.scope.partition_id.removeprefix('clip:'))
                require(clip >= 0, 'Invalid M3 clip')
                meta.update(contents=[node.text], timestamp=clip,
                    memfolder=provenance[node.node_id])
                row['metadata'] = meta
                row['embeddings'] = vectors(node, original, self.space)
                row.pop('embeddings_storage', None)
            elif node.text and node.embeddings != original.embeddings and any(e.values and (self.space is None or e.space == self.space) for e in node.embeddings):
                row['embeddings'] = vectors(node, original, self.space)
                row.pop('embeddings_storage', None)
            require(row.get('type') in ('episodic', 'semantic', 'img', 'voice'), 'M3 native node type requires an explicit codec extension')
            nodes.append(row)
        nodes.sort(key=lambda row: row['id'])
        data.update(video_id=video, nodes=nodes)
        edges = []
        seen = set()
        for edge in snapshot.edges:
            a, b = int(ids[edge.source_id]), int(ids[edge.target_id])
            require((a, b) not in seen and edge.relation == 'm3.connection', 'M3 edge dictionary cannot represent parallel relation types')
            seen.add((a, b))
            edges.append({'source': a, 'target': b, 'weight': edge.weight})
            if not edge.directed and (b, a) not in seen:
                edges.append({'source': b, 'target': a, 'weight': edge.weight}); seen.add((b, a))
        data['edges'] = edges
        text = [n for n in nodes if n['type'] in ('episodic', 'semantic')]
        by_clip, events = defaultdict(list), defaultdict(list)
        for node in text:
            clip = str(node['metadata']['timestamp'])
            by_clip[clip].append(node['id'])
            if node['type'] == 'episodic':
                events[clip].append(node['id'])
        data.update(text_nodes=[n['id'] for n in text], text_nodes_by_clip=dict(by_clip),
            event_sequence_by_clip=dict(events), next_node_id=max((n['id'] for n in nodes), default=-1) + 1)
        # Character IDs are reader-visible. Preserve their names and membership;
        # never recompute equivalence from new compressed text or from an LLM.
        for field in ('character_mappings', 'reverse_character_mappings'):
            if field in data:
                tags = [tag for group in data[field].values() for tag in group] if field == 'character_mappings' else data[field].keys()
                media_ids = {str(n['id']):n['type'] for n in nodes if n['type'] in ('img', 'voice')}
                require(all(tag.split('_', 1)[-1] in media_ids and media_ids[tag.split('_', 1)[-1]] == {'face':'img','voice':'voice'}.get(tag.split('_',1)[0]) for tag in tags), 'M3 character mapping escaped protected identities')
        return package('m3', 'm3.videograph.v1', snapshot, archive, ids, data)
