"""Hydrate a caller-supplied real VideoGraph class; no SDK imports or fake classes."""
from ..core import to_data
from ..core.values import require


def restore(value):
    if isinstance(value, list): return [restore(v) for v in value]
    if not isinstance(value, dict): return value
    if value.get('encoding') == 'ndarray' and set(value) == {'encoding','dtype','shape','values'}:
        import numpy as np
        dtype = np.dtype(value['dtype']); require(not dtype.hasobject and dtype.kind in 'biuf', 'Unsupported native array dtype')
        result = np.asarray(value['values'], dtype=dtype)
        require(list(result.shape) == value['shape'], 'Native array shape mismatch')
        return result
    if value.get('encoding') == 'base64' and value.get('python_type') == 'bytes' and set(value) == {'encoding','python_type','data'}:
        import base64
        return base64.b64decode(value['data'], validate=True)
    return {k:restore(v) for k,v in value.items()}


def hydrate_m3(data, graph_type):
    """Keep native metadata/dtypes; rebuild clip indexes with integer keys."""
    require(isinstance(graph_type, type) and isinstance(getattr(graph_type,'Node',None), type), 'Supply the actual M3 VideoGraph class')
    values = to_data(data)
    graph = graph_type.__new__(graph_type)
    defaults = {'max_img_embeddings':10,'max_audio_embeddings':20,'img_matching_threshold':.3,'audio_matching_threshold':.6}
    for name,value in {**defaults, **values}.items():
        if name not in ('nodes','edges','text_nodes_by_clip','event_sequence_by_clip'): setattr(graph, name, restore(value))
    graph.nodes = {}
    for row in values['nodes']:
        node = graph_type.Node.__new__(graph_type.Node)
        for key,value in row.items():
            if key not in ('embeddings','embeddings_storage'): setattr(node,key,restore(value))
        node.embeddings = restore(row.get('embeddings_storage', row['embeddings']))
        require(node.id not in graph.nodes, 'Duplicate native graph ID')
        graph.nodes[node.id] = node
    graph.edges = {(int(e['source']), int(e['target'])):e['weight'] for e in values['edges']}
    for field in ('text_nodes_by_clip','event_sequence_by_clip'):
        setattr(graph, field, {int(k):list(v) for k,v in values[field].items()})
    require(set(graph.text_nodes) == {n.id for n in graph.nodes.values() if n.type in ('episodic','semantic')}, 'Native text index mismatch')
    require(all(a in graph.nodes and b in graph.nodes for a,b in graph.edges), 'Dangling native edge')
    shapes = {(len(graph.nodes[i].embeddings), tuple(len(v) for v in graph.nodes[i].embeddings)) for i in graph.text_nodes}
    require(len(shapes) <= 1 and all(count > 0 and len(set(widths)) == 1 and widths[0] > 0 for count,widths in shapes),
        'Native M3 text search requires uniform vector shapes; configure content-embeddings for all text')
    return graph
