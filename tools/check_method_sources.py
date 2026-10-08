"""Verify provenance bytes and the unmodified legacy catalog without importing it."""
import ast
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'memfolder'
items = json.loads((PACKAGE / 'docs/METHOD_PROVENANCE.json').read_text(encoding='utf-8'))
catalog = json.loads((ROOT / 'refactor_review/code_catalog.json').read_text(encoding='utf-8'))
for row in catalog:
    path = Path(row['local_path'])
    assert sha256(path.read_bytes()).hexdigest() == row['sha256'], 'Archived original changed: ' + row['id']
checked = []
for row in items:
    path = ROOT / row.get('local_source', row['source'])
    assert sha256(path.read_bytes()).hexdigest() == row['sha256'], 'Provenance source bytes differ'
    target = PACKAGE / 'src/memfolder' / row['target']
    assert target.is_file()
    identical = 0
    if row.get('symbols'):
        def declarations(file):
            return {node.name: node for node in ast.parse(file.read_text(encoding='utf-8-sig')).body
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        upstream, ported = declarations(path), declarations(target)
        class LazyImportOnly(ast.NodeTransformer):
            def visit_FunctionDef(self, node):
                node = self.generic_visit(node)
                lazy = ast.dump(ast.parse('np = numpy()').body[0])
                node.body = [statement for statement in node.body if ast.dump(statement) != lazy]
                return node
        for name in row['symbols']:
            if name not in upstream:
                continue  # prompt constants are assignments, characterized separately
            original = LazyImportOnly().visit(upstream[name])
            copied = LazyImportOnly().visit(ported[name])
            assert ast.dump(original) == ast.dump(copied), 'Copied pure routine differs beyond lazy dependency acquisition: ' + name
            identical += 1
    checked.append({'target': row['target'], 'source_sha256': row['sha256'], 'pure_declarations_equal_except_lazy_numpy': identical})
report = {'status': 'passed', 'archived_sources_unchanged': len(catalog), 'provenance_records': len(items),
          'checks': checked, 'benchmark_evaluations': 0}
(PACKAGE / 'build/method_source_validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({k: v for k, v in report.items() if k != 'checks'}))
