"""Generate explicit experiment variants; no implicit benchmark dispatch."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT / 'examples/recipes'
folder.mkdir(parents=True, exist_ok=True)


def write(name, planner, operator, features=()):
    config = {'planner': planner, 'operator': operator}
    if features:
        config['features'] = list(features)
    (folder / (name + '.json')).write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')


write('recordfolder', {'plugin': 'recordfolder'}, {'plugin': 'recordfolder-operator'})
write('contextfolder', {'plugin': 'contextfolder'}, {'plugin': 'contextfolder-operator'})
write('recordfolder-semantic-only', {'plugin': 'recordfolder', 'parameters': {
    'candidates': {'plugin': 'temporal-candidates', 'parameters': {'use_entities': False, 'temporal_order': 'order'}},
    'scorer': {'plugin': 'fused-affinity', 'parameters': {'mode': 'no_entity'}}}}, {'plugin': 'recordfolder-operator'})
write('random-prune', {'plugin': 'random-prune'}, {'plugin': 'rule-operator'})
write('random-merge', {'plugin': 'random-merge'}, {'plugin': 'recordfolder-operator'})
write('random-merge-round', {'plugin': 'random-merge-round'}, {'plugin': 'recordfolder-operator'})
write('tome-text', {'plugin': 'tome'}, {'plugin': 'tome-operator'}, ({'plugin': 'current-embeddings'},))
write('tome-bsm-text', {'plugin': 'tome-bsm'}, {'plugin': 'recordfolder-operator'})
write('tome-m3-pooled', {'plugin': 'tome-pooled', 'parameters': {'partitioner': {
    'plugin': 'tome-pooled-groups', 'parameters': {'id_order': 'source_numeric'}}}}, {'plugin': 'recordfolder-operator'})
memforest_features = ({'plugin': 'event-time-features', 'parameters': {'aggregation': 'latest'}},)
write('memforest-mst-capacity', {'plugin': 'memforest'}, {'plugin': 'memforest-operator'}, memforest_features)
write('memforest-mst-cluster-ceil', {'plugin': 'memforest', 'parameters': {
    'allocator': {'plugin': 'legacy-cluster-ceil', 'parameters': {'keep_ratio': .7}}}}, {'plugin': 'memforest-operator'}, memforest_features)
write('memforest-m3-proxy', {'plugin': 'memforest-proxy', 'parameters': {'partitioner': {
    'plugin': 'average-linkage-groups', 'parameters': {'id_order': 'source_numeric'}}}}, {'plugin': 'recordfolder-operator'})
for variant in ('random_anchor_farthest', 'medoid_pivot'):
    write('dart-' + variant, {'plugin': 'dart', 'parameters': {'selector': {
        'plugin': 'dart-selector', 'parameters': {'variant': variant}}}}, {'plugin': 'rule-operator'})
for method in ('kmeans-prune', 'kmeans-merge'):
    write(method, {'plugin': method}, {'plugin': 'rule-operator' if method.endswith('prune') else 'recordfolder-operator'})
write('streammeco-official', {'plugin': 'streammeco'}, {'plugin': 'rule-operator'})
write('tome-with-contextfolder', {'plugin': 'tome-bsm'}, {'plugin': 'contextfolder-operator'})
write('llmlingua2-post-record', {'plugin': 'current-record-rewrite'},
    {'plugin': 'llmlingua2-operator', 'parameters': {'writer': {
        'plugin': 'llmlingua2-writer', 'parameters': {'rate': 0.55}}}})
write('contextfolder-post-record', {'plugin': 'current-record-rewrite'},
    {'plugin': 'text-operator', 'parameters': {'writer': {'plugin': 'contextfolder-writer'},
                                           'record_builder': {'plugin': 'current-record-builder'}}})
write('random-anchors-with-contextfolder', {'plugin': 'contextfolder', 'parameters': {
    'anchors': {'plugin': 'random-selector'}}}, {'plugin': 'contextfolder-operator'})
write('external-recency-with-recordfolder', {'plugin': 'recordfolder', 'parameters': {
    'anchors': {'plugin': 'example.recency'}}}, {'plugin': 'recordfolder-operator'})
write('external-recency-prune', {'plugin': 'prune-planner', 'parameters': {
    'selector': {'plugin': 'example.recency'}}}, {'plugin': 'rule-operator'})
write('offline-random-merge', {'plugin': 'random-merge'}, {'plugin': 'text-operator', 'parameters': {'writer': {'plugin': 'concat-writer'}}})
print(json.dumps({'recipes_written': len(list(folder.glob('*.json')))}))
