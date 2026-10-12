"""Open verified artifacts with caller-configured native readers."""
from pathlib import Path
import json
from ..core.values import require
from .base import verify_materialization
from .io import safe_path
from .m3_native import hydrate_m3


def open_qdrant_view(directory):
    """Return (client, collection). Caller closes this read/write-capable SDK client."""
    directory = Path(directory).resolve(); _,native = verify_materialization(directory)
    require(native.framework_id == 'mem0', 'Expected Mem0 output')
    config = json.loads((directory/'qdrant.reader.json').read_text(encoding='utf-8'))
    from qdrant_client import QdrantClient
    return QdrantClient(path=str(safe_path(directory,config['path']))), config['collection']


def load_memos_view(directory, memory, *, user_name=None):
    """Explicitly load into an EMPTY configured Naive/TreeTextMemory instance.

    Configuration, credentials and graph-store ownership belong to the caller.
    This method refuses to append into an existing bank.
    """
    directory = Path(directory).resolve(); _,native = verify_materialization(directory)
    require(native.framework_id == 'memos', 'Expected MemOS output')
    existing = memory.get_all(user_name=user_name) if native.data['backend'] == 'tree_text' else memory.get_all()
    if isinstance(existing, dict): existing = existing.get('nodes', existing)
    require(not existing, 'MemOS target must be empty')
    if native.data['backend'] == 'tree_text': memory.load(str(directory), user_name=user_name)
    else: memory.load(str(directory))
    return memory


def load_m3_view(directory, graph_type):
    _,native = verify_materialization(directory)
    require(native.framework_id == 'm3', 'Expected M3 output')
    return hydrate_m3(native.data, graph_type)
