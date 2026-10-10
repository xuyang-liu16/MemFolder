"""Lazy adapter for the official optional LLMLingua-2 package; no implicit fallback."""
import asyncio
from dataclasses import dataclass
from functools import cached_property
from hashlib import sha256
from importlib.metadata import version
import threading
from .core import fingerprint
from .core.values import require
from .planning.common import spec
from .operators.llmlingua2 import validate_rate


@dataclass(frozen=True)
class LLMLingua2Service:
    model_name: str = 'microsoft/llmlingua-2-xlm-roberta-large-meetingbank'
    revision: str = 'ebaba9b0e874dadd3003ffcff828e4397e568089'
    device_map: str = 'cuda'
    dtype: str = 'float16'
    max_batch_size: int = 16
    spec = spec('service.official_llmlingua2.v1', 'service')

    def __post_init__(self):
        require(bool(self.model_name) and bool(self.revision) and bool(self.device_map),
                'Declare LLMLingua-2 model, revision and device')
        require(self.dtype in ('float16', 'float32', 'bfloat16'), 'Invalid LLMLingua-2 dtype')
        require(type(self.max_batch_size) is int and self.max_batch_size > 0,
                'LLMLingua-2 batch size must be positive')
        object.__setattr__(self, '_lock', threading.Lock())

    @property
    def cache_identity(self):
        return fingerprint(('llmlingua==0.2.2', self.model_name, self.revision,
                            self.device_map, self.dtype, self.max_batch_size))

    @cached_property
    def _compressor(self):
        require(version('llmlingua') == '0.2.2', 'Install memfolder[llmlingua2] (llmlingua==0.2.2)')
        import torch
        from llmlingua import PromptCompressor
        return PromptCompressor(model_name=self.model_name, device_map=self.device_map,
            use_llmlingua2=True,
            model_config={'revision': self.revision, 'torch_dtype': getattr(torch, self.dtype),
                          'trust_remote_code': False},
            llmlingua2_config={'max_batch_size': self.max_batch_size})

    def _compress(self, text, rate):
        # One model instance has mutable token-classifier state; serialize access.
        with self._lock:
            result = self._compressor.compress_prompt(text, rate=rate, use_context_level_filter=False)
        require(isinstance(result, dict) and type(result.get('compressed_prompt')) is str,
                'Invalid official LLMLingua-2 response')
        return {'text': result['compressed_prompt'], 'rate': rate,
            'input_view': 'current_record', 'input_text_sha256': sha256(text.encode('utf-8')).hexdigest(),
            'use_llmlingua2': True, 'use_context_level_filter': False,
            'implementation': 'llmlingua==0.2.2', 'model_name': self.model_name,
            'model_revision': self.revision, 'device_map': self.device_map, 'dtype': self.dtype,
            'original_tokens': result.get('origin_tokens'), 'compressed_tokens': result.get('compressed_tokens'),
            'request_fingerprint': fingerprint((self.cache_identity, text, rate, False, 'current_record'))}

    async def compress(self, text, *, rate):
        validate_rate(rate)
        require(type(text) is str and bool(text.strip()), 'LLMLingua-2 needs non-empty current text')
        return await asyncio.to_thread(self._compress, text, rate)

    async def close(self):
        def release():
            with self._lock:
                self.__dict__.pop('_compressor', None)
        await asyncio.to_thread(release)
