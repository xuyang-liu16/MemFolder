"""Convert framework-native memory formats to the public data contracts."""

from __future__ import annotations
from collections import defaultdict
from dataclasses import replace
import re
from .contracts import LoadOptions, NativeEdge, NativeLibrary, NativeRecord
from ..core import ContentPart, FrozenMap, RetentionPolicy, TimePoint, to_data
from ..core.values import fingerprint, require
from .validation import (
    array_value,
    check_coverage,
    dense_vectors,
    issue,
    lineage_temporal_projection,
    metadata,
    native_id,
    object_value,
    parse_time,
    temporal_projection,
    text_value,
)


class Mem0Adapter:
    framework = 'mem0'
    format_id = 'mem0.export.v1'

    def decode(self, data, *, options: LoadOptions, source_id: str) -> NativeLibrary:
        issues = []
        extra = {}
        coverage = 'unknown'
        if type(data) is dict:
            if 'results' in data:
                rows = array_value(data['results'], source_id + '.results')
                extra = {k: v for k, v in data.items() if k != 'results'}
                if data.get('next') is not None or data.get('next_page_offset') is not None:
                    coverage = 'partial'
                if data.get('relations'):
                    issues.append(issue('entity_relations_preserved', source_id, 'relations',
                        'Entity relations retained as native metadata; these are not edges between memory IDs.'))
            elif 'points' in data:
                rows = array_value(data['points'], source_id + '.points')
                extra = {k: v for k, v in data.items() if k != 'points'}
                if data.get('next_page_offset') is not None:
                    coverage = 'partial'
            elif type(data.get('result')) is dict and 'points' in data['result']:
                result = data['result']
                rows = array_value(result['points'], source_id + '.result.points')
                extra = {k: v for k, v in result.items() if k != 'points'}
                if result.get('next_page_offset') is not None:
                    coverage = 'partial'
            else:
                require(False, f'{source_id}: not a Mem0 export or Qdrant scroll document')
        else:
            rows = array_value(data, source_id)
        records = []
        for index, row in enumerate(rows):
            location = f'rows[{index}]'
            row = object_value(row, location)
            nid = native_id(row.get('id'), location)
            is_point = 'payload' in row
            payload = object_value(row['payload'], location + '.payload') if is_point else row
            meta = metadata(payload, location)
            content_key = next((k for k in ('data', 'memory', 'text') if k in payload), None)
            require(content_key is not None, f'{location}: missing memory content')
            text = text_value(payload[content_key], location + '.' + content_key)
            identifiers = {}
            for key in ('user_id', 'agent_id', 'run_id'):
                top, nested = payload.get(key), meta.get(key)
                require(top is None or nested is None or top == nested, f'{location}: conflicting native identity')
                value = top if top is not None else nested
                if value is not None:
                    identifiers[key] = native_id(value, location + '.' + key)
            require(bool(identifiers) or options.namespace is not None or options.sample_id is not None,
                    f'{location}: unscoped export requires namespace or sample_id')
            namespace = 'mem0:' + fingerprint(identifiers if identifiers else {'namespace': options.namespace or options.sample_id})
            owner = next(iter(identifiers), None)
            sample_key = (owner + ':' + identifiers[owner]) if owner else 'namespace:' + (options.namespace or options.sample_id)
            ranges, available, row_issues, temporal_meta = temporal_projection(payload, meta, options, source_id, location)
            issues.extend(row_issues)
            expires = None
            if payload.get('expiration_date'):
                # An expiration date is a declared wall-clock boundary, not an event date.
                expires = parse_time(payload['expiration_date'], options=options)
                if expires is None:
                    issues.append(issue('expiration_unparsed', source_id, location,
                                        'Expiration retained but its timezone is unspecified or invalid.'))
            lineage_time = lineage_temporal_projection(payload, meta, location)
            if lineage_time is not None:
                lineage_ranges, lineage_available, lineage_expires = lineage_time
                if options.timestamp_fields == ('timestamp',) and options.time_semantics == 'event_time':
                    ranges = lineage_ranges
                if options.visibility_field:
                    require(lineage_available is None or available == lineage_available,
                            f'{location}: native visibility conflicts with MemFolder lineage')
                else:
                    available = lineage_available
                require(expires is None or lineage_expires is None or expires == lineage_expires,
                        f'{location}: native expiration conflicts with MemFolder lineage')
                expires = lineage_expires if lineage_expires is not None else expires
            vectors = {}
            vector = row.get('vector') if is_point else row.get('embedding')
            if vector is not None:
                slots = vector if type(vector) is dict else {'default': vector}
                for name, value in slots.items():
                    if type(value) is dict and 'indices' in value and 'values' in value:
                        issues.append(issue('sparse_vector_preserved', source_id, location,
                                            'Sparse vector retained in native payload; it is not a dense embedding.'))
                        continue
                    vectors[name] = dense_vectors(value, location + '.vector')
            records.append(NativeRecord(native_id=nid, namespace=namespace, sample_key=sample_key,
                partition_key=namespace, parts=(ContentPart(modality='text', text=text),),
                native=FrozenMap(row), selectors=FrozenMap(identifiers), vectors=FrozenMap(vectors),
                kind=payload.get('memory_type') or meta.get('memory_type') or 'memory',
                time_ranges=ranges, available_at=available, expires_at=expires,
                extensions=FrozenMap(temporal_meta)))
        return NativeLibrary(framework=self.framework, format_id=self.format_id,
            records=tuple(records), metadata=FrozenMap(extra), coverage=coverage, issues=tuple(issues))


class MemOSAdapter:
    framework = 'memos'
    format_id = 'memos.textual.v1'

    def decode(self, data, *, options: LoadOptions, source_id: str) -> NativeLibrary:
        extra, raw_edges = {}, []
        if type(data) is dict and 'nodes' in data:
            rows = array_value(data['nodes'], source_id + '.nodes')
            raw_edges = array_value(data.get('edges', []), source_id + '.edges')
            coverage = check_coverage(data, len(rows), len(raw_edges), source_id)
            extra = {k: v for k, v in data.items() if k not in ('nodes', 'edges')}
        else:
            rows = array_value(data, source_id)
            coverage = 'unknown'
        records, issues = [], []
        namespace_by_id = {}
        for index, row in enumerate(rows):
            location = f'nodes[{index}]'
            row = object_value(row, location)
            meta = metadata(row, location)
            nid = native_id(row.get('id'), location)
            cube_values = [v for v in (row.get('cube_id'), row.get('mem_cube_id'),
                           meta.get('cube_id'), meta.get('mem_cube_id'), options.namespace) if v is not None]
            require(len({native_id(v, location + '.cube') for v in cube_values}) <= 1,
                    f'{location}: conflicting cube identity')
            cube = native_id(cube_values[0] if cube_values else options.sample_id, location + '.cube')
            namespace = 'cube:' + cube
            require(nid not in namespace_by_id, f'{location}: duplicate native node ID; load cubes separately')
            namespace_by_id[nid] = namespace
            memory = text_value(row.get('memory'), location + '.memory')
            ranges, available, row_issues, temporal_meta = temporal_projection(row, meta, options, source_id, location)
            issues.extend(row_issues)
            expires = None
            lineage_time = lineage_temporal_projection(row, meta, location)
            if lineage_time is not None:
                lineage_ranges, lineage_available, lineage_expires = lineage_time
                if options.timestamp_fields == ('timestamp',) and options.time_semantics == 'event_time':
                    ranges = lineage_ranges
                if options.visibility_field:
                    require(lineage_available is None or available == lineage_available,
                            f'{location}: native visibility conflicts with MemFolder lineage')
                else:
                    available = lineage_available
                expires = lineage_expires
            vectors = {}
            for name in ('embedding', 'embedding_1024', 'embedding_3072', 'embedding_768'):
                top, nested = row.get(name), meta.get(name)
                require(top is None or nested is None or top == nested, f'{location}: conflicting embedding values')
                if (value := top if top is not None else nested) is not None:
                    vectors[name] = dense_vectors(value, location + '.' + name)
            # Archives/deletions remain available for case analysis, never compression targets.
            status = meta.get('status', row.get('status', 'activated'))
            eligible = status not in ('deleted', 'archived')
            selectors = {'cube_id': cube}
            selectors.update({k: meta[k] for k in ('user_id', 'session_id', 'memory_type', 'status') if k in meta})
            records.append(NativeRecord(native_id=nid, namespace=namespace, sample_key=cube,
                partition_key=namespace, parts=(ContentPart(modality='text', text=memory),),
                native=FrozenMap(row), selectors=FrozenMap(selectors), vectors=FrozenMap(vectors),
                kind=meta.get('memory_type') or meta.get('type') or 'memory', eligible=eligible,
                retention=RetentionPolicy() if eligible else RetentionPolicy(may_drop=False, may_merge=False, may_rewrite=False),
                time_ranges=ranges, available_at=available, expires_at=expires,
                revision=str(meta.get('version') or '0'),
                extensions=FrozenMap(temporal_meta)))
        edges = []
        for index, edge in enumerate(raw_edges):
            location = f'edges[{index}]'
            edge = object_value(edge, location)
            start, end = native_id(edge.get('source'), location), native_id(edge.get('target'), location)
            require(start in namespace_by_id and end in namespace_by_id, f'{location}: dangling native edge')
            relation = text_value(edge.get('type'), location + '.type')
            edges.append(NativeEdge(source_namespace=namespace_by_id[start], source_id=start,
                target_namespace=namespace_by_id[end], target_id=end, relation=relation,
                weight=edge.get('weight', 1.0), directed=edge.get('directed', True),
                native_id=str(edge['id']) if 'id' in edge else None, native=FrozenMap(edge)))
        return NativeLibrary(framework=self.framework, format_id=self.format_id, records=tuple(records),
            edges=tuple(edges), metadata=FrozenMap(extra), coverage=coverage, issues=tuple(issues))


class Mem0NodeExportAdapter:
    """MemoryNode JSONL with native point IDs and source provenance."""
    framework = 'mem0'
    format_id = 'mem0.node_export.v1'

    def decode(self, data, *, options: LoadOptions, source_id: str) -> NativeLibrary:
        rows = array_value(data, source_id)
        records, issues = [], []
        from dataclasses import replace
        for index, row in enumerate(rows):
            location = f'rows[{index}]'
            row = object_value(row, location)
            provenance = object_value(row.get('source'), location + '.source')
            native_id(row.get('node_id'), location + '.node_id')
            candidate = provenance.get('point_id') if provenance.get('point_id') is not None else row.get('raw_pointer')
            point_id = native_id(candidate, location + '.point_id')
            require(row.get('raw_pointer') is None or str(row['raw_pointer']) == point_id, 'Exported point identity conflicts with raw_pointer')
            user_id = native_id(provenance.get('user_id'), location + '.user_id')
            text = text_value(row.get('text'), location + '.text')
            point = {'id': point_id, 'payload': {'data': text, 'user_id': user_id,
                     'timestamp': row.get('timestamp')}, 'vector': row.get('embedding')}
            lib = Mem0Adapter().decode([point], options=options, source_id=source_id)
            record = lib.records[0]
            # Source provenance explicitly records benchmark sample identity.
            sample_key = provenance.get('sample_id') or record.sample_key
            records.append(replace(record, sample_key=native_id(sample_key, location + '.sample_id'), native=FrozenMap(row)))
            issues.extend(replace(i, location=location) for i in lib.issues)
            if row.get('timestamp') == 0:
                issues.append(issue('node_export_zero_timestamp', source_id, location,
                    'Node export uses zero for missing/unparsed time; the raw value is retained.'))
        return NativeLibrary(framework=self.framework, format_id=self.format_id, records=tuple(records), issues=tuple(issues))


class M3Adapter:
    framework = 'm3'
    format_id = 'm3.graph.v1'

    def decode(self, data, *, options: LoadOptions, source_id: str) -> NativeLibrary:
        data = object_value(data, source_id)
        video = native_id(data.get('video_id') or options.namespace or options.sample_id, source_id + '.video_id')
        require(options.namespace is None or options.namespace == video, 'M3 document conflicts with explicit video namespace')
        namespace = 'video:' + video
        rows = array_value(data.get('nodes'), source_id + '.nodes')
        raw_edges = array_value(data.get('edges', []), source_id + '.edges')
        records, issues, text_ids, clip_ids, all_ids = [], [], [], {}, set()
        for index, row in enumerate(rows):
            location = f'nodes[{index}]'
            row = object_value(row, location)
            nid = native_id(row.get('id'), location)
            require(nid not in all_ids, f'{location}: duplicate native node ID')
            all_ids.add(nid)
            kind = text_value(row.get('type'), location + '.type')
            meta = metadata(row, location)
            contents = array_value(meta.get('contents', []), location + '.contents')
            is_text = kind in ('episodic', 'semantic')
            if is_text:
                require(bool(contents), f'{location}: text node has no content')
                parts = tuple(ContentPart(modality='text', text=text_value(v, location + '.contents')) for v in contents)
                clip = meta.get('timestamp')
                require(type(clip) is int and clip >= 0, f'{location}: text node needs a nonnegative integer clip ID')
                partition = 'clip:' + str(clip)
                available = TimePoint(value=clip, clock='m3:' + video + ':clip')
                text_ids.append(nid)
                clip_ids.setdefault(str(clip), []).append(nid)
                identity = any(v.lower().startswith('equivalence') for v in contents)
                eligible = not identity
            else:
                modality = {'img': 'image', 'voice': 'audio'}.get(kind, 'structured')
                parts = tuple(ContentPart(modality=modality, data=FrozenMap({'native_content': value})) for value in contents)
                if not parts:
                    parts = (ContentPart(modality='structured', data=FrozenMap({'node_type': kind})),)
                partition, available, eligible = 'identity', None, False
            vectors = {kind: dense_vectors(row.get('embeddings'), location + '.embeddings')}
            temporal_meta = {}
            if is_text and options.order_by == 'numeric_native_id':
                temporal_meta = {'memfolder.event_timestamp': str(clip),
                    'memfolder.temporal_source': {'selected_field': 'metadata.timestamp',
                        'semantics': 'clip_index', 'clock': available.clock}}
            records.append(NativeRecord(native_id=nid, namespace=namespace, sample_key=video,
                partition_key=partition, parts=parts, native=FrozenMap(row),
                selectors=FrozenMap({'video_id': video, 'node_type': kind,
                                     **({'clip_id': meta['timestamp']} if is_text else {})}),
                vectors=FrozenMap(vectors), kind=kind, eligible=eligible,
                retention=RetentionPolicy() if eligible else RetentionPolicy(may_drop=False, may_merge=False, may_rewrite=False),
                available_at=available, extensions=FrozenMap(temporal_meta)))
        # Validate all official retrieval indexes; preserve their exact ordering in metadata.
        if 'text_nodes' in data:
            supplied = [native_id(v, source_id + '.text_nodes') for v in array_value(data['text_nodes'], 'text_nodes')]
            require(len(set(supplied)) == len(supplied) and set(supplied) == set(text_ids), 'M3 text index disagrees with nodes')
        if 'text_nodes_by_clip' in data:
            index = object_value(data['text_nodes_by_clip'], 'text_nodes_by_clip')
            normalized = {k: [native_id(v, 'clip index') for v in array_value(ids, 'clip index')] for k, ids in index.items()}
            require(set(clip_ids) <= set(normalized) and all(len(set(v)) == len(v) and set(v) == set(clip_ids.get(k, ()))
                    for k, v in normalized.items()), 'M3 clip index disagrees with node timestamps')
        if 'event_sequence_by_clip' in data:
            index = object_value(data['event_sequence_by_clip'], 'event_sequence_by_clip')
            types = {r.native_id: r.kind for r in records}
            supplied_events = {}
            for clip, ids in index.items():
                ids = [native_id(v, 'event index') for v in array_value(ids, 'event index')]
                require(len(set(ids)) == len(ids) and all(v in clip_ids.get(clip, ()) and types[v] == 'episodic' for v in ids),
                        'M3 event index disagrees with episodic nodes')
                supplied_events[clip] = set(ids)
            expected_events = {clip: {nid for nid in ids if types[nid] == 'episodic'} for clip, ids in clip_ids.items()}
            require(all(supplied_events.get(clip, set()) == ids for clip, ids in expected_events.items()),
                    'M3 event index omits episodic nodes')
        types = {r.native_id: r.kind for r in records}
        def valid_identity(tag):
            require(type(tag) is str and '_' in tag, 'Invalid M3 character identity tag')
            modality, identity = tag.split('_', 1)
            require(modality in ('face', 'voice') and types.get(identity) == {'face': 'img', 'voice': 'voice'}[modality],
                    'M3 character index references an unknown or mismatched identity node')
        if 'character_mappings' in data:
            mappings = object_value(data['character_mappings'], 'character_mappings')
            inverse = {}
            for character, tags in mappings.items():
                for tag in array_value(tags, 'character tags'):
                    valid_identity(tag)
                    require(tag not in inverse, 'M3 identity belongs to multiple character groups')
                    inverse[tag] = character
            if 'reverse_character_mappings' in data:
                require(object_value(data['reverse_character_mappings'], 'reverse_character_mappings') == inverse,
                        'M3 forward/reverse character indexes disagree')
        elif 'reverse_character_mappings' in data:
            for tag in object_value(data['reverse_character_mappings'], 'reverse_character_mappings'):
                valid_identity(tag)
        if 'text_nodes' in data:
            rank = {nid: i for i, nid in enumerate(supplied)}
            # Retrieval insertion order is meaningful; structural nodes precede text.
            records.sort(key=lambda r: (r.native_id in rank, rank.get(r.native_id, 0)))
        edges = []
        for index, edge in enumerate(raw_edges):
            location = f'edges[{index}]'
            edge = object_value(edge, location)
            start, end = native_id(edge.get('source'), location), native_id(edge.get('target'), location)
            require(start in all_ids and end in all_ids, f'{location}: dangling native edge')
            # Official VideoGraph stores both orientations. Preserve each entry;
            # do not collapse it into one edge or double its weight.
            edges.append(NativeEdge(source_namespace=namespace, source_id=start,
                target_namespace=namespace, target_id=end, relation=edge.get('type', 'm3.connection'),
                weight=edge.get('weight', 1.0), directed=True,
                native_id=str(edge['id']) if 'id' in edge else None, native=FrozenMap(edge)))
        extra = {k: v for k, v in data.items() if k not in ('nodes', 'edges')}
        return NativeLibrary(framework=self.framework, format_id=self.format_id, records=tuple(records),
            edges=tuple(edges), metadata=FrozenMap(extra), coverage='unknown', issues=tuple(issues))


def _m3_entities(text, media_types):
    entities = []
    for modality, identity in re.findall(r'<(face|voice)_([0-9]+)>', text, flags=re.I):
        modality = modality.lower()
        identity = str(int(identity))
        if media_types.get(identity) == {'face': 'img', 'voice': 'voice'}[modality]:
            entities.append((modality, identity))
    return entities


def _m3_character_indexes(records, edges):
    """Deterministic form of VideoGraph.refresh_equivalences()."""
    by_node = {record.node_id: record for record in records}
    by_native = {str(record.native['id']): record for record in records}
    media_types = {native: record.kind for native, record in by_native.items()
                   if record.kind in ('img', 'voice')}
    equivalences = {record.node_id for record in records
                    if record.kind == 'semantic' and
                    any(part.text and part.text.lower().startswith('equivalence')
                        for part in record.parts)}
    connected = defaultdict(set)
    weights = {}
    for edge in edges:
        left, right = by_node[edge.source_id], by_node[edge.target_id]
        for media, semantic in ((left, right), (right, left)):
            if media.kind in ('img', 'voice') and semantic.node_id in equivalences:
                connected[media.node_id].add(semantic.node_id)
                key = (media.node_id, semantic.node_id)
                weights[key] = max(weights.get(key, float('-inf')), float(edge.weight))
    selected = set()
    ordered_media = sorted((record for record in records if record.kind in ('img', 'voice')),
                           key=lambda record: int(record.native['id']))
    for media in ordered_media:
        candidates = sorted(connected.get(media.node_id, ()),
                            key=lambda node_id: int(by_node[node_id].native['id']))
        if media.kind == 'img':
            selected.update(candidates)
            continue
        face_links, other_links = [], []
        for node_id in candidates:
            entities = _m3_entities(by_node[node_id].text, media_types)
            (face_links if any(kind == 'face' for kind, _ in entities) else other_links).append(node_id)
        selected.update(other_links)
        if face_links:
            selected.add(max(face_links, key=lambda node_id:
                (weights[(media.node_id, node_id)], -int(by_node[node_id].native['id']))))

    parent, rank = {}, {}
    def find(item):
        if item not in parent:
            parent[item], rank[item] = item, 0
        if parent[item] != item:
            parent[item] = find(parent[item])
        return parent[item]
    def union(left, right):
        left, right = find(left), find(right)
        if left == right:
            return
        if rank[left] < rank[right]:
            left, right = right, left
        parent[right] = left
        if rank[left] == rank[right]:
            rank[left] += 1
    for node_id in sorted(selected, key=lambda value: int(by_node[value].native['id'])):
        entities = _m3_entities(by_node[node_id].text, media_types)
        if len(entities) >= 2:
            anchor = entities[0][1]
            for _, identity in entities[1:]:
                union(anchor, identity)
    groups = defaultdict(list)
    for identity in sorted(media_types, key=int):
        groups[find(identity)].append(identity)
    ordered_groups = sorted(groups.values(), key=lambda group: min(map(int, group)))
    mappings = {}
    for index, group in enumerate(ordered_groups):
        mappings[f'character_{index}'] = [
            ('face_' if media_types[identity] == 'img' else 'voice_') + identity
            for identity in group]
    reverse = {tag: character for character, tags in mappings.items() for tag in tags}
    return mappings, reverse


def project_m3_cutoff(snapshot, cutoff):
    """Apply the official ID cutoff and refresh every graph-derived index."""
    require(type(cutoff) is int and cutoff >= 0, 'Invalid M3 before_clip')
    ends = [int(record.native['id']) for record in snapshot.records
            if record.kind in ('episodic', 'semantic') and
            record.native['record']['metadata']['timestamp'] == cutoff]
    require(bool(ends), 'M3 cutoff clip missing; refusing to expose the full graph')
    end = max(ends)
    records = tuple(record for record in snapshot.records if int(record.native['id']) <= end)
    ids = {record.node_id for record in records}
    require(all(record.available_at is None or record.available_at.value <= cutoff for record in records),
            'M3 native ordering crosses clip boundary')
    edges = tuple(edge for edge in snapshot.edges if edge.source_id in ids and edge.target_id in ids)
    text = sorted((record for record in records if record.kind in ('episodic', 'semantic')),
                  key=lambda record: int(record.native['id']))
    by_clip, events = defaultdict(list), defaultdict(list)
    for record in text:
        clip = str(record.native['record']['metadata']['timestamp'])
        native = int(record.native['id'])
        by_clip[clip].append(native)
        if record.kind == 'episodic':
            events[clip].append(native)
    mappings, reverse = _m3_character_indexes(records, edges)
    extensions = to_data(snapshot.extensions)
    imported = extensions.get('memfolder.import', {})
    sources = imported.get('sources', {})
    selected = [key for key, value in sources.items()
                if value.get('source', {}).get('framework') == 'm3']
    require(len(selected) == 1, 'M3 cutoff needs exactly one native graph source')
    source = sources[selected[0]]
    metadata = source['metadata']
    metadata.update(text_nodes=[int(record.native['id']) for record in text],
        text_nodes_by_clip=dict(by_clip), event_sequence_by_clip=dict(events),
        character_mappings=mappings, reverse_character_mappings=reverse,
        next_node_id=max((int(record.native['id']) for record in records), default=-1) + 1)
    return replace(snapshot, records=records, edges=edges, extensions=FrozenMap(extensions))
