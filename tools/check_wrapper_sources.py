"""Pin source evidence used by native codecs and reader characterization."""
from pathlib import Path
from hashlib import sha256
import json

ROOT=Path(__file__).resolve().parents[1]
sources=json.loads((ROOT/'docs/LOADING_SOURCES.json').read_text(encoding='utf-8'))
selection={'mem0':('mem0/vector_stores/qdrant.py','mem0/memory/main.py'),
    'memos':('src/memos/memories/textual/naive.py','src/memos/memories/textual/tree.py','src/memos/memories/textual/item.py','src/memos/graph_dbs/neo4j.py'),
    'm3':('mmagent/videograph.py',)}
official={}
for framework,paths in selection.items():
    source=sources['official_sources'][framework]
    entries=[e for e in source['sources'] if e['path'] in paths]
    assert len(entries)==len(paths)
    for entry in entries:
        file=ROOT/'build/upstream'/framework/entry['path']
        assert sha256(file.read_bytes()).hexdigest()==entry['sha256'], 'Pinned upstream source changed'
    official[framework]={'repository':source['repository'],'revision':source['revision'],'sources':entries}
catalog=json.loads((ROOT.parent/'refactor_review/code_catalog.json').read_text(encoding='utf-8'))
historical=[]
for identity in ('m3:tools/g1s/materialize.py','standard_release:g1s/g1s/steps/s6_materialize.py'):
    row=next(r for r in catalog if r['id']==identity)
    assert sha256(Path(row['local_path']).read_bytes()).hexdigest()==row['sha256']
    historical.append({'id':identity,'sha256':row['sha256']})
report={'checked_date':'2026-10-05','status':'passed','official_sources':official,'historical_sources':historical,
    'scope':'Source-format/API characterization, not complete SDK installation or live Neo4j execution',
    'design':'Native representation independently implemented; graph projection and embeddings are replaceable',
    'adaptations':['New output rather than historical inplace modification','Explicit encoder/model-space injection',
        'Default max-weight edge redirection; optional projector replaces it','M3 text/clip/event indexes rebuilt; character names not recomputed',
        'MemOS full credential configuration not exported','Mem0 named/sparse changed content requires specialized codec',
        'Mem0 native expiration uses dates; sub-day expiration rejected']}
(ROOT/'docs/WRAPPER_SOURCES.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':'passed','official_files':sum(len(s['sources']) for s in official.values()),'historical_materializers':len(historical)}))
