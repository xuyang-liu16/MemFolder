"""Generate three synthetic native stores and import them through the public API."""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.stdout.reconfigure(encoding='utf-8')
from memfolder.core import EmbeddingSpace, FrozenMap, dumps
from memfolder.loading import LoadOptions, load_m3, load_mem0, load_memos_cube, save_library

parser = argparse.ArgumentParser()
parser.add_argument('--output-dir', type=Path, default=ROOT / 'build' / 'loading-demo')
args = parser.parse_args()
folder = args.output_dir
folder.mkdir(parents=True, exist_ok=False)

mem0 = folder / 'mem0.json'
mem0.write_text(json.dumps({'points': [
    {'id': 'native-a', 'payload': {'data': 'Alice 喜欢茶。', 'user_id': 'Alice_1'}, 'vector': [1., 0.]},
    {'id': 'native-b', 'payload': {'data': 'Bob 喜欢咖啡。', 'user_id': 'Bob_1'}, 'vector': [0., 1.]},
]}, ensure_ascii=False), encoding='utf-8')
options = LoadOptions(dataset_id='synthetic-locomo', sample_id='sample-1',
    selectors=FrozenMap({'user_id': ('Alice_1', 'Bob_1')}),
    embedding_spaces={'default': EmbeddingSpace(provider='synthetic', model='fixture-2d', revision='1', dimension=2)})

cube = folder / 'cube'
cube.mkdir()
(cube / 'config.json').write_text(json.dumps({'cube_id': 'sample-1', 'text_mem': {
    'backend': 'tree_text', 'config': {'memory_filename': 'textual_memory.json'}}}), encoding='utf-8')
(cube / 'textual_memory.json').write_text(json.dumps({'nodes': [
    {'id': 'm1', 'memory': 'Alice 喜欢茶。', 'metadata': {'memory_type': 'LongTermMemory'}},
    {'id': 'm2', 'memory': '她每天下午喝茶。', 'metadata': {'memory_type': 'WorkingMemory'}}],
    'edges': [{'source': 'm1', 'target': 'm2', 'type': 'RELATED'}],
    'total_nodes': 2, 'total_edges': 1}, ensure_ascii=False), encoding='utf-8')

m3 = folder / 'm3.json'
m3.write_text(json.dumps({'video_id': 'robot/demo', 'nodes': [
    {'id': 0, 'type': 'img', 'metadata': {'contents': ['synthetic-image-reference']}, 'embeddings': [[1., 0.]]},
    {'id': 1, 'type': 'voice', 'metadata': {'contents': ['synthetic-audio-reference']}, 'embeddings': [[0., 1.]]},
    {'id': 2, 'type': 'semantic', 'metadata': {'contents': ['Equivalence: <voice_1> is <face_0>'], 'timestamp': 0}, 'embeddings': [[1., 0.]]},
    {'id': 3, 'type': 'episodic', 'metadata': {'contents': ['Alice 打开门。'], 'timestamp': 0}, 'embeddings': [[0., 1.]]}],
    'edges': [{'source': 0, 'target': 3, 'weight': 1.}, {'source': 3, 'target': 0, 'weight': 1.}],
    'text_nodes': [2, 3], 'text_nodes_by_clip': {'0': [2, 3]}, 'event_sequence_by_clip': {'0': [3]},
    'character_mappings': {'character_0': ['face_0', 'voice_1']},
    'reverse_character_mappings': {'face_0': 'character_0', 'voice_1': 'character_0'}}, ensure_ascii=False), encoding='utf-8')

libraries = {'mem0': load_mem0(mem0, options=options), 'memos': load_memos_cube(cube), 'm3': load_m3(m3)}
for name, library in libraries.items():
    save_library(library, folder / (name + '.library.json'))
    (folder / (name + '.report.json')).write_text(dumps(library.report, indent=2), encoding='utf-8')
    print(f'{name}: samples={library.report.samples_loaded}, records={library.report.records_loaded}, '
          f'edges={library.report.edges_loaded}, eligible={library.report.eligible_records}')
print('Synthetic fixtures only; no named compression method or benchmark evaluation was run.')
