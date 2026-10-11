"""Optional native MemOS session for experiment and contributor-owned SDK services.

Configure the run directory before importing this module. The upstream SDK's
cached factories are process-global; use one configured session per process.
"""
class NativeMemOSSession:
    def __init__(self,transport):
        from .native import new_native
        self.reader,self.tree=new_native(transport)
    def build(self,batch):
        from .native import build_batch
        return build_batch(self.reader,self.tree,batch)
    def search(self,query,*,user_name):
        from .native import retrieve
        return retrieve(self.tree,query,user_name)
    def close(self):self.tree.graph_store.close()
    def __enter__(self):return self
    def __exit__(self,*exc):self.close()
