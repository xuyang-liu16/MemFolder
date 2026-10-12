"""Restricted value import of official M3 pickles; never import the M3 runtime."""
from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import pickle

from memfolder.core import ContractError, FrozenMap
from memfolder.core.values import require
from .readers import SourceDocument
from .types import LoadOptions


class _Graph:
    pass


class _Node:
    pass


class _M3Unpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module in ('mmagent.videograph', 'videograph'):
            if name == 'VideoGraph':
                return _Graph
            if name in ('VideoGraph.Node', 'Node'):
                return _Node
        allowed = {
            ('numpy', 'ndarray'), ('numpy', 'dtype'),
            ('numpy.core.multiarray', '_reconstruct'), ('numpy._core.multiarray', '_reconstruct'),
            ('numpy.core.multiarray', 'scalar'), ('numpy._core.multiarray', 'scalar'),
            ('numpy.core.numeric', '_frombuffer'), ('numpy._core.numeric', '_frombuffer'),
        }
        if (module, name) not in allowed:
            raise ContractError('M3 pickle contains an unsupported global; use a JSON export for this variant')
        try:
            import numpy as np
        except ImportError:
            raise ContractError('This M3 pickle requires the optional numpy package') from None
        require(hasattr(np, 'ndarray') and hasattr(np, 'dtype'), 'M3 pickle needs a functional numpy installation')
        if name == 'ndarray':
            return np.ndarray
        if name == 'dtype':
            return np.dtype
        # Both numpy 1.x and 2.x serialization module names are recognized.
        core = getattr(np, '_core', None)
        if core is None:
            core = np.core
        if name == '_reconstruct':
            return core.multiarray._reconstruct
        if name == 'scalar':
            def scalar(dtype, value):
                require(not dtype.hasobject and dtype.kind in 'biuf', 'Unsupported numpy scalar dtype')
                return core.multiarray.scalar(dtype, value)
            return scalar
        def frombuffer(buffer, dtype, shape, order):
            require(not dtype.hasobject and dtype.kind in 'biuf', 'Unsupported numpy array dtype')
            return core.numeric._frombuffer(buffer, dtype, shape, order)
        return frombuffer

    def persistent_load(self, pid):
        raise ContractError('External references are not supported in M3 pickle imports')


def json_value(value, *, arrays_as_lists=False):
    if value is None or type(value) in (str, int, float, bool):
        return value
    if type(value) is bytes:
        return {'encoding': 'base64', 'python_type': 'bytes', 'data': base64.b64encode(value).decode('ascii')}
    if type(value) in (tuple, list):
        return [json_value(v, arrays_as_lists=arrays_as_lists) for v in value]
    if type(value) is dict:
        require(all(type(k) in (str, int) for k in value), 'Unsupported M3 metadata map key')
        require(len({str(k) for k in value}) == len(value), 'Colliding M3 metadata keys')
        return {str(k): json_value(v, arrays_as_lists=arrays_as_lists) for k, v in value.items()}
    # Lazy numpy import only after a pickle actually contains numerical arrays.
    if type(value).__module__.startswith('numpy'):
        import numpy as np
        require(isinstance(value, (np.ndarray, np.generic)), 'Unsupported numpy object')
        require(not value.dtype.hasobject and value.dtype.kind in 'biuf', 'Unsupported M3 array dtype')
        if isinstance(value, np.generic):
            return value.item()
        values = value.tolist()
        if arrays_as_lists:
            return values
        return {'encoding': 'ndarray', 'dtype': str(value.dtype), 'shape': list(value.shape), 'values': values}
    raise ContractError('Unsupported M3 metadata object; no opaque object was imported')


def graph_to_document(graph, *, video_id: str) -> dict:
    require(type(graph) is _Graph, 'M3 pickle does not contain a VideoGraph')
    require(type(getattr(graph, 'nodes', None)) is dict and type(getattr(graph, 'edges', None)) is dict,
            'M3 graph is missing nodes or edges')
    nodes = []
    for key, node in graph.nodes.items():
        require(type(node) is _Node, 'Unsupported M3 node object')
        require(type(key) in (str, int) and str(key) == str(getattr(node, 'id', None)), 'M3 node key/ID mismatch')
        payload = {k: json_value(v) for k, v in vars(node).items() if k != 'embeddings'}
        vectors = getattr(node, 'embeddings', [])
        payload['embeddings'] = json_value(vectors, arrays_as_lists=True)
        # Preserve ndarray dtype/shape instead of only retaining converted floats.
        payload['embeddings_storage'] = json_value(vectors)
        nodes.append(payload)
    edges = []
    for key, weight in graph.edges.items():
        require(type(key) is tuple and len(key) == 2, 'Unsupported M3 edge key')
        edges.append({'source': json_value(key[0]), 'target': json_value(key[1]), 'weight': json_value(weight)})
    result = {k: json_value(v) for k, v in vars(graph).items() if k not in ('nodes', 'edges')}
    require('video_id' not in result or result['video_id'] == video_id, 'Conflicting M3 video identity')
    result.update({'video_id': video_id, 'nodes': nodes, 'edges': edges})
    FrozenMap(result)
    return result


def read_m3_pickle(path: str | Path, *, options: LoadOptions, source_id: str | None = None) -> SourceDocument:
    path = Path(path)
    label = source_id or path.name
    require(path.is_file() and path.stat().st_size <= options.max_file_bytes, 'Missing/oversized M3 pickle')
    raw = path.read_bytes()
    require(len(raw) <= options.max_file_bytes, 'M3 pickle file-size limit exceeded')
    try:
        stream = BytesIO(raw)
        graph = _M3Unpickler(stream).load()
        require(stream.read(1) == b'', 'Trailing data after M3 pickle')
    except (pickle.UnpicklingError, EOFError, ValueError, TypeError, AttributeError) as ex:
        raise ContractError('M3 pickle is invalid or uses an unsupported value representation') from None
    data = graph_to_document(graph, video_id=options.namespace or options.sample_id or path.stem)
    return SourceDocument(source_id=label, data=data, sha256=sha256(raw).hexdigest())
