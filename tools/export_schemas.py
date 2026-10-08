"""Export public structural JSON Schemas from the implementation."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import memfolder.core as core
import memfolder.loading as loading
import memfolder.wrappers as wrappers

folder = ROOT / 'schemas'
folder.mkdir(exist_ok=True)
records = {v.schema_id: v for module in (core, loading, wrappers) for name in module.__all__ if isinstance(v := getattr(module, name), type)
           and issubclass(v, core.Contract) and v is not core.Contract}
for schema_id, cls in sorted(records.items()):
    (folder / (schema_id + '.schema.json')).write_text(json.dumps(core.json_schema(cls), indent=2) + '\n', encoding='utf-8')
(folder / 'index.json').write_text(json.dumps({'api_version': core.API_VERSION, 'schemas': sorted(records),
    'semantics': 'Structural validation only; constructors and cross-record validators enforce semantic invariants.'}, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'schemas_exported': len(records), 'api_version': core.API_VERSION}))
