"""Export public structural JSON Schemas from the implementation."""
from pathlib import Path
import argparse
import importlib.util
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
package_spec = importlib.util.spec_from_file_location('memfolder', ROOT / 'src' / '__init__.py',
    submodule_search_locations=[str(ROOT / 'src')])
package = importlib.util.module_from_spec(package_spec)
sys.modules['memfolder'] = package
package_spec.loader.exec_module(package)
import memfolder.core as core
import memfolder.loading as loading
import memfolder.wrappers as wrappers

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', type=Path, default=ROOT / 'build' / 'schemas',
                    help='Output directory (default: build/schemas in the checkout)')
folder = parser.parse_args().output_dir.resolve()
folder.mkdir(parents=True, exist_ok=True)
records = {v.schema_id: v for module in (core, loading, wrappers) for name in module.__all__ if isinstance(v := getattr(module, name), type)
           and issubclass(v, core.Contract) and v is not core.Contract}
for schema_id, cls in sorted(records.items()):
    (folder / (schema_id + '.schema.json')).write_text(json.dumps(core.json_schema(cls), indent=2) + '\n', encoding='utf-8')
(folder / 'index.json').write_text(json.dumps({'api_version': core.API_VERSION, 'schemas': sorted(records),
    'semantics': 'Structural validation only; constructors and cross-record validators enforce semantic invariants.'}, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'schemas_exported': len(records), 'api_version': core.API_VERSION}))
