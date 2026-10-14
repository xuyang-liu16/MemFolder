"""Optional online grounding; cached release grounding remains independently usable."""

from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Mapping, Sequence
from ..component_runtime import emit, resolve, spec
from ..core import ContractError, FeatureBatch, FeatureRow, FrozenMap
from ..core.values import require
from ..operators.contracts import ChatRequest, ChatTruncated
from ..operators.record_operations import display_timestamp, record_owner


@dataclass(frozen=True)
class StoredEmbeddings:
    space: object
    name: str = 'semantic'
    spec = spec('features.stored_embeddings', 'feature_provider')

    def extract(self, snapshot, context):
        rows=[]
        for n in snapshot.records:
            if not n.eligible: continue
            selected=[e for e in n.embeddings if e.space == self.space]
            require(len(selected)==1 and bool(selected[0].values),'Missing inline embedding in the configured space')
            rows.append(FeatureRow(node_id=n.node_id,vector=selected[0].values))
        return FeatureBatch(name=self.name,input_fingerprint=snapshot.fingerprint,rows=tuple(rows),space=self.space)


@dataclass(frozen=True)
class CurrentEmbeddings:
    """Read current content-bound vectors; reject stale or ambiguous spaces."""
    space: object | None = None
    name: str = 'semantic'
    spec = spec('features.current_content_embeddings', 'feature_provider')
    def extract(self, snapshot, context):
        nodes = [n for n in snapshot.records if n.eligible]
        if not nodes:
            return FeatureBatch(name=self.name, input_fingerprint=snapshot.fingerprint,
                                rows=(), space=self.space)
        spaces = {e.space for n in nodes for e in n.embeddings
                  if e.source_fingerprint == n.content_fingerprint}
        space = self.space
        if space is None:
            require(len(spaces) == 1, 'Current embeddings require an explicit unambiguous space')
            space = next(iter(spaces))
        rows = []
        for n in nodes:
            matches = [e for e in n.embeddings if e.space == space
                       and e.source_fingerprint == n.content_fingerprint and e.values]
            require(len(matches) == 1, 'Missing/stale current content embedding: '+n.node_id)
            rows.append(FeatureRow(node_id=n.node_id, vector=matches[0].values))
        return FeatureBatch(name=self.name, input_fingerprint=snapshot.fingerprint,
                           rows=tuple(rows), space=space)


def event_time(value, *, timezone_offset=None):
    """Only explicit ISO timestamps/numbers with a declared clock are admitted."""
    if type(value) in (int,float): return float(value)
    require(type(value) is str and value.strip(), 'Missing grounding event timestamp')
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:
        from ..core import ContractError
        raise ContractError('Grounding timestamp must be normalized ISO 8601 before planning') from None
    if dt.tzinfo is None:
        require(timezone_offset is not None, 'Naive event timestamps require an explicit UTC offset')
        from datetime import timedelta
        dt=dt.replace(tzinfo=timezone(timedelta(seconds=timezone_offset)))
    return dt.timestamp()


@dataclass(frozen=True)
class GroundingFeatures:
    """Standard-release grounding JSON, or caller-owned detached per-node records.

    id_map explicitly maps canonical IDs to source IDs. Participants are supplied by
    the adapter, rather than inferred from benchmark-specific user_id suffixes.
    Unknown timestamps are not silently given epoch-zero values.
    """
    grounding: FrozenMap
    participants: tuple[str,...] = ()
    id_map: FrozenMap = FrozenMap()
    timezone_offset: int | None = None
    clock: str = 'unix_seconds'
    name: str = 'entities'
    require_time: bool = True
    spec = spec('features.grounding', 'feature_provider', diagnostics=('memfolder.planning.grounding',))

    def extract(self, snapshot, context):
        nodes={str(n['node_id']):n for n in self.grounding.get('nodes',())}
        speakers={s.strip().casefold() for s in self.participants}
        rows=[]
        for n in snapshot.records:
            if not n.eligible: continue
            source=self.id_map.get(n.node_id,n.node_id)
            require(source in nodes, 'Grounding is incomplete; supply an explicit ID map')
            row=nodes[source];keys=set()
            for e in row.get('entities',()):
                key=str(e.get('key',e.get('canonical',''))).strip().casefold()
                if key and not key.startswith('event::') and str(e.get('canonical','')).strip().casefold() not in speakers:
                    keys.add(key)
            for r in row.get('relations',()):
                for side in ('subject','object'):
                    key=str(r.get(side,'')).strip().casefold()
                    if key and key not in speakers: keys.add(key)
            values={'entities':sorted(keys)}
            if self.require_time:
                values.update(event_time=event_time(row.get('timestamp'),timezone_offset=self.timezone_offset),clock=self.clock)
            rows.append(FeatureRow(node_id=n.node_id,values=FrozenMap(values)))
        batch=FeatureBatch(name=self.name,input_fingerprint=snapshot.fingerprint,rows=tuple(rows))
        emit(context,self.spec.plugin_id,'memfolder.planning.grounding',nodes=[r.node_id for r in rows],
            populated=sum(bool(r.values['entities']) for r in rows),total=len(rows))
        return batch


@dataclass(frozen=True)
class EventTimeFeatures:
    name: str = 'temporal'
    aggregation: str = 'earliest'
    spec = spec('features.event_time', 'feature_provider')

    def extract(self,snapshot,context):
        require(self.aggregation in ('earliest','latest'),'Unknown event time aggregation')
        rows=[]
        for n in snapshot.records:
            if not n.eligible: continue
            require(bool(n.time_ranges),'No parsed event time; availability is not event time')
            clocks={r.start.clock for r in n.time_ranges}
            require(len(clocks)==1,'Node event times use multiple clocks')
            choose=max if self.aggregation=='latest' else min
            earliest=choose((r.start for r in n.time_ranges),key=lambda t:t.value)
            rows.append(FeatureRow(node_id=n.node_id,values=FrozenMap({'event_time':earliest.value,'clock':earliest.clock})))
        return FeatureBatch(name=self.name,input_fingerprint=snapshot.fingerprint,rows=tuple(rows))


@dataclass(frozen=True)
class SemanticEmbeddingFeatures:
    """Inject encoder via Services. encode(texts) returns aligned vectors; space is explicit."""
    space: object
    service: str = 'embeddings'
    name: str = 'semantic'
    spec = spec('features.semantic_encoder','feature_provider')

    async def extract(self,snapshot,context):
        nodes=tuple(n for n in snapshot.records if n.eligible)
        if not nodes: return FeatureBatch(name=self.name,input_fingerprint=snapshot.fingerprint,rows=(),space=self.space)
        from ..component_runtime import resolve
        vectors=await resolve(context.services.require(self.service).encode(tuple(n.text for n in nodes)))
        require(len(vectors)==len(nodes),'Encoder output count mismatch')
        return FeatureBatch(name=self.name,input_fingerprint=snapshot.fingerprint,space=self.space,
            rows=tuple(FeatureRow(node_id=n.node_id,vector=tuple(float(v) for v in vector)) for n,vector in zip(nodes,vectors)))


ENTITY_TYPES = sorted(
    [
        "person",
        "work",
        "place",
        "org",
        "group",
        "animal",
        "object",
        "activity",
        "topic",
        "event",
        "other",
    ]
)


_RULES = [
    """Extract ALL content-bearing entities mentioned or clearly implied by the
   node text: people (including authors/creators/public figures), named works
   (books, movies, songs, shows) together with their creators, places and
   locations, organizations / communities / groups, pets or named animals,
   significant objects / possessions, activities / hobbies / jobs /
   fields of work, topics or concepts someone could ask about later, and
   concrete events.""",
    """The bare word "User" refers to the source speaker; resolve it to the
   speaker's own name and do not emit "user" as an entity.""",
    """Do NOT stop at the protagonist. A node like "Loved 'X' by Y" must yield
   both the work X and the person Y. Aim for at least 2 entities per node
   whenever the text carries any concrete content; only pure greetings or
   chit-chat may have fewer.""",
    """`canonical` must be a short noun phrase in lowercase, without a leading
   "the", without verbs. Aliases of the same thing share one canonical label.""",
]


_COREFERENCE_RULE = """Coreference discipline:
   a. If an entity is the SAME referent as a known/recurrent label above,
      reuse that label EXACTLY.
   b. If it merely shares words but is a DIFFERENT referent (e.g. a different
      person with the same first name, different kids, a different song),
      create a disambiguated label, e.g. "max (neighbor)" vs "max (coworker)".
   c. Generic referents must carry owner qualification when an owner is
      known: "melanie's kids", not bare "kids"; "caroline's garden", not
      "garden". Truly public/generic concepts (art, pottery, mental health)
      stay unqualified."""


_TAIL_RULES = [
    "Do not invent entities that are not in the text.",
    """`relations` are optional; keep them only when clean, with a noun-phrase
   subject and object (never a verb phrase or sentence).""",
    """Set `opens_channel=true` for any entity that could plausibly recur in
   later memories.""",
]


_SCHEMA = """Allowed entity types: {types}

Return exactly one JSON object:
{{
  "nodes": [
    {{
      "id": 0,
      "entities": [
        {{"canonical": "becoming nicole", "type": "work", "roles": ["liked"], "mentions": ["Becoming Nicole"], "opens_channel": true}},
        {{"canonical": "amy ellis nutt", "type": "person", "roles": ["author"], "mentions": ["Amy Ellis Nutt"], "opens_channel": true}}
      ],
      "relations": [{{"subject": "amy ellis nutt", "predicate": "wrote", "object": "becoming nicole"}}]
    }}
  ]
}}

Every input id must occur exactly once. Output JSON only, no commentary.

INPUT NODES:
{records}"""


_HEADER = """Role: exhaustive entity extraction for a memory compression graph.

You will ground every memory node of one conversation session. The extracted
entities decide which memories are allowed to merge, so recall of
content-bearing entities matters more than precision of wording.

Session metadata:
- sample_id: {sample_id}
- exact_timestamp: {timestamp}
{registry_line}"""


def build_prompt(
    *,
    sample: int,
    timestamp: str,
    records: Sequence[Mapping[str, Any]],
    registry: Sequence[str] | None,
) -> str:
    rules = [*_RULES, *( [_COREFERENCE_RULE] if registry is not None else [] ), *_TAIL_RULES]
    header = _HEADER.format(
        sample_id=sample,
        timestamp=timestamp,
        registry_line=(
            "- known/recurrent canonical labels from earlier sessions: "
            f"{json.dumps(sorted(registry), ensure_ascii=False)}"
            if registry is not None
            else ""
        ),
    )
    numbered = "\n".join(f"{number}. {rule}" for number, rule in enumerate(rules, start=1))
    schema = _SCHEMA.format(
        types=ENTITY_TYPES,
        records=json.dumps([dict(record) for record in records], ensure_ascii=False),
    )
    return f"{header}\n\nExtraction rules:\n{numbered}\n\n{schema}"


def normalise_label(value: str, speaker: str) -> str:
    label = re.sub(r"\s+", " ", str(value or "").strip().casefold())
    label = re.sub(r"^the\s+", "", label)
    return speaker if label in {"user", "user's", "speaker"} else label


def normalise_row(row: Mapping[str, Any], speaker: str) -> dict[str, Any]:
    entities = []
    for entity in row.get("entities") or []:
        key = normalise_label(entity.get("canonical", ""), speaker)
        if not key:
            continue
        entities.append(
            {
                "canonical": key,
                "key": key,
                "type": str(entity.get("type") or "other").casefold(),
                "roles": [str(value) for value in (entity.get("roles") or [])][:4],
                "mentions": [str(value) for value in (entity.get("mentions") or [])][:4],
                "opens_channel": bool(entity.get("opens_channel", True)),
            }
        )
    relations = []
    for relation in row.get("relations") or []:
        subject = normalise_label(relation.get("subject", ""), speaker)
        obj = normalise_label(relation.get("object", ""), speaker)
        predicate = re.sub(r"\s+", " ", str(relation.get("predicate") or "").strip().casefold())
        if subject and obj and subject != obj and len(predicate.split()) <= 4:
            relations.append({"subject": subject, "predicate": predicate, "object": obj})
    return {"entities": entities, "relations": relations}


RETRY_SUFFIX = (
    "\n\nRETRY REQUIREMENT: one complete JSON object, every input id exactly "
    "once, no Markdown, no commentary."
)


def extract_json(raw: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating a model that wrapped it in prose."""
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        value, _ = json.JSONDecoder().raw_decode(match.group(0))
        return value


EVENT_PREFIX = "event::"


def _key(value: Any) -> str:
    return str(value or "").strip().casefold()


def entity_set(node: Mapping[str, Any], speakers: set[str]) -> frozenset[str]:
    """Informative entity keys of one node."""
    from_entities = {
        _key(entity.get("key"))
        for entity in node.get("entities", [])
        if str(entity.get("key", "")).strip()
        and _key(entity.get("canonical")) not in speakers
        and not str(entity.get("key", "")).startswith(EVENT_PREFIX)
    }
    from_relations = {
        _key(relation.get(side))
        for relation in node.get("relations", [])
        for side in ("subject", "object")
        if str(relation.get(side, "")).strip() and _key(relation.get(side)) not in speakers
    }
    return frozenset(from_entities | from_relations)


def source_speaker(node, names):
    owner = record_owner(node)
    if owner is None:
        return names.get(node.node_id, '')
    # Native conversation exports append the numeric sample to speaker IDs.
    # An arbitrary user handle without that suffix is not renamed.
    speaker = owner.rsplit('_', 1)[0] if re.search(r'_\d+$', owner) else owner
    return str(names.get(owner, speaker)).strip().casefold()


@dataclass(frozen=True)
class SessionGrounder:
    max_tokens: int = 4096
    attempts: int = 4
    max_split_depth: int = 2
    spec = spec('grounding.session_registry', 'session_grounder')

    def __post_init__(self):
        require(type(self.max_tokens) is int and self.max_tokens > 0,
                'Grounding output budget must be positive')
        require(type(self.attempts) is int and self.attempts > 0,
                'Grounding attempts must be positive')
        require(type(self.max_split_depth) is int and self.max_split_depth >= 0,
                'Grounding split depth must be nonnegative')

    async def ground(self, nodes, context, *, service='grounding', speaker_names=FrozenMap()):
        require(bool(nodes), 'Session grounding needs a sample')
        require(len({(n.scope.dataset_id,n.scope.sample_id) for n in nodes}) == 1,
                'Grounding registry cannot cross samples')
        prepared = [{'node':node, 'timestamp':display_timestamp(node),
                     'speaker':source_speaker(node,speaker_names)} for node in nodes]
        prepared.sort(key=lambda row:(row['timestamp'],
            str(row['node'].native.get('id',row['node'].node_id)),row['node'].node_id))
        sessions = defaultdict(list)
        for index,row in enumerate(prepared):
            row['index'] = index
            sessions[row['timestamp']].append(row)
        clocks = {r.start.clock for n in nodes for r in n.time_ranges}
        require(len(clocks) <= 1, 'Grounding session times use multiple clocks')

        def session_order(item):
            label, rows = item
            values = [r.start.value for row in rows for r in row['node'].time_ranges]
            # Missing times remain unparsed labels; they are never fabricated as epoch.
            return (1,min(values),label) if values else (0,label,label)

        known, results = set(), {}
        sample = nodes[0].scope.sample_id
        sample = int(sample) if sample.isdigit() else sample

        async def call(label, rows, depth=0):
            wanted = {row['index'] for row in rows}
            prompt = build_prompt(sample=sample,timestamp=label,
                records=[{'id':row['index'],'source':row['speaker'],'text':row['node'].text} for row in rows],
                registry=sorted(known))
            for attempt in range(self.attempts):
                try:
                    raw = await resolve(context.services.require(service).complete(ChatRequest(
                        role='memory_grounding',prompt=prompt if attempt==0 else prompt+RETRY_SUFFIX+f'\nValidation retry {attempt+1}.',
                        max_tokens=self.max_tokens,temperature=0,response_format='json_object',
                        prompt_id='grounding.session_registry.v1',require_complete=True)))
                    payload = extract_json(raw)
                    got = payload.get('nodes')
                    require(isinstance(got,list) and all(isinstance(row,dict) for row in got),
                            'Grounding response needs node objects')
                    require(sorted(int(row['id']) for row in got) == sorted(wanted),
                            'Grounding response ID coverage mismatch')
                    for row in got:
                        require(isinstance(row.get('entities') or [],list) and
                                all(isinstance(e,dict) for e in row.get('entities') or []),
                                'Invalid grounding entities')
                        require(isinstance(row.get('relations') or [],list) and
                                all(isinstance(r,dict) for r in row.get('relations') or []),
                                'Invalid grounding relations')
                    return payload
                except ChatTruncated:
                    if depth >= self.max_split_depth or len(rows) <= 1:
                        raise
                    half = len(rows)//2
                    left = await call(label,rows[:half],depth+1)
                    right = await call(label,rows[half:],depth+1)
                    return {'nodes':[*left['nodes'],*right['nodes']]}
                except Exception:
                    if attempt+1 == self.attempts:
                        raise ContractError('Session grounding failed after bounded attempts; no partial features returned') from None
            raise AssertionError('Unreachable grounding retry state')

        for label, rows in sorted(sessions.items(),key=session_order):
            payload = await call(label,rows)
            by_id = {int(row['id']):row for row in payload['nodes']}
            for row in rows:
                normalized = normalise_row(by_id[row['index']],row['speaker'])
                known.update(entity['key'] for entity in normalized['entities'])
                results[row['index']] = {'node_index':row['index'],'node_id':row['node'].node_id,
                    'timestamp':label,'source':record_owner(row['node']) or '',**normalized}
        return {'nodes':[results[i] for i in range(len(prepared))],
                'participants':sorted({row['speaker'] for row in prepared if row['speaker']})}


def merge_map(labels, embeddings, threshold):
    import numpy as np
    parent = list(range(len(labels)))
    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index
    cosine = embeddings @ embeddings.T
    np.fill_diagonal(cosine,0.)
    ii,jj = np.where(cosine >= threshold)
    for left,right in zip(ii.tolist(),jj.tolist()):
        left,right = find(left),find(right)
        if left != right:
            if (len(labels[right]),labels[right]) < (len(labels[left]),labels[left]):
                parent[left] = right
            else:
                parent[right] = left
    return {label:labels[find(i)] for i,label in enumerate(labels)}


@dataclass(frozen=True)
class SynonymLabels:
    service: str = 'embeddings'
    threshold: float = .85
    spec = spec('grounding.synonym_labels', 'label_merger')

    def __post_init__(self):
        require(type(self.threshold) in (int,float) and 0 < self.threshold <= 1,
                'Synonym cosine threshold must be in (0,1]')

    async def merge(self, document, context):
        labels = set()
        for row in document['nodes']:
            labels.update(e['key'] for e in row['entities'] if e['key'])
            labels.update(r[side] for r in row['relations'] for side in ('subject','object') if r[side])
        labels = sorted(labels)
        if not labels:
            return document
        import numpy as np
        values = await resolve(context.services.require(self.service).encode(tuple(labels)))
        embeddings = np.asarray(values,dtype=np.float64)
        require(embeddings.ndim==2 and embeddings.shape[0]==len(labels) and embeddings.shape[1]>0
                and bool(np.isfinite(embeddings).all()), 'Invalid synonym label embeddings')
        norms = np.linalg.norm(embeddings,axis=1,keepdims=True)
        require(bool((norms>0).all()), 'Synonym label embeddings cannot be zero')
        mapping = merge_map(labels,embeddings/norms,self.threshold)
        rows = []
        for row in document['nodes']:
            seen = {}
            for entity in row['entities']:
                key = mapping.get(entity['key'],entity['key'])
                ne = {**entity,'key':key,'canonical':key}
                if key in seen:
                    seen[key]['roles'] = sorted(set(seen[key]['roles'])|set(ne['roles']))
                    seen[key]['mentions'] = sorted(set(seen[key]['mentions'])|set(ne['mentions']))[:4]
                else:
                    seen[key] = ne
            relations = []
            for relation in row['relations']:
                subject,obj = (mapping.get(relation[side],relation[side]) for side in ('subject','object'))
                if subject and obj and subject != obj:
                    relations.append({**relation,'subject':subject,'object':obj})
            rows.append({**row,'entities':list(seen.values()),'relations':relations})
        return {**document,'nodes':rows}


@dataclass(frozen=True)
class ChatGroundingFeatures:
    service: str = 'grounding'
    name: str = 'entities'
    aliases: FrozenMap = FrozenMap()
    require_time: bool = False
    speaker_names: FrozenMap = FrozenMap()
    grounder: object = SessionGrounder()
    label_merger: object = SynonymLabels()
    spec=spec('features.chat_grounding','feature_provider', diagnostics=('memfolder.planning.grounding',))
    async def extract(self,snapshot,context):
        samples={}
        for node in snapshot.records:
            if not node.eligible:continue
            samples.setdefault((node.scope.dataset_id,node.scope.sample_id),[]).append(node)
        grounded={}
        for nodes in samples.values():
            document=await resolve(self.grounder.ground(tuple(nodes),context,
                service=self.service,speaker_names=self.speaker_names))
            document=await resolve(self.label_merger.merge(document,context))
            require(len(document['nodes'])==len(nodes) and
                    {row['node_id'] for row in document['nodes']}=={node.node_id for node in nodes},
                    'Grounding components changed node coverage')
            speakers=set(document['participants'])
            for row in document['nodes']:
                grounded[row['node_id']]=sorted({self.aliases.get(key,key) for key in entity_set(row,speakers)})
        rows=[]
        for node in snapshot.records:
            if not node.eligible:continue
            values={'entities':grounded[node.node_id]}
            if self.require_time:
                require(bool(node.time_ranges),'Grounding time must come from explicit parsed event time')
                times=[r.start for r in node.time_ranges];require(len({t.clock for t in times})==1,'Mixed grounding clocks')
                first=min(times,key=lambda t:t.value);values.update(event_time=first.value,clock=first.clock)
            rows.append(FeatureRow(node_id=node.node_id,values=FrozenMap(values)))
        batch=FeatureBatch(name=self.name,input_fingerprint=snapshot.fingerprint,rows=tuple(rows))
        emit(context,self.spec.plugin_id,'memfolder.planning.grounding',nodes=[r.node_id for r in rows],
            populated=sum(bool(r.values['entities']) for r in rows),total=len(rows),samples=len(samples))
        return batch
