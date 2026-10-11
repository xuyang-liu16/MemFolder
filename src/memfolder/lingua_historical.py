"""Recovered LongMemEval LLMLingua-2 recipe, separate from the rate-only adapter.

Imports and configuration assembly never load weights or download a checkpoint.
This recipe matches the recovered successful compression calls; it does not
establish equivalence of the Record parents or the historical QA environment.
"""
import asyncio
from dataclasses import dataclass
from functools import cached_property
from hashlib import sha256
from importlib.metadata import version
import threading

from .core import fingerprint
from .core.values import require
from .operators.llmlingua2 import validate_rate
from .planning.common import spec


PROFILE = 'llmlingua2.longmemeval.historical55.normalized_fallback.v3'


class _HistoricalCounter:
    def count(self, text):
        import tiktoken
        # Preserve the recovered encoder's token counting, including its
        # handling of special-token strings, rather than broadening that API.
        return len(tiktoken.get_encoding('cl100k_base').encode(text))


@dataclass(frozen=True)
class HistoricalLLMLingua2Service:
    model_name: str = 'microsoft/llmlingua-2-xlm-roberta-large-meetingbank'
    revision: str = 'ebaba9b0e874dadd3003ffcff828e4397e568089'
    device_map: str = 'cuda'
    spec = spec('service.llmlingua2_historical55.v1', 'service')

    def __post_init__(self):
        require(all(type(value) is str and value for value in
                    (self.model_name, self.revision, self.device_map)),
                'Declare the historical LLMLingua model, revision and device')
        object.__setattr__(self, '_lock', threading.Lock())

    @property
    def cache_identity(self):
        return fingerprint((PROFILE, 'llmlingua==0.2.2', self.model_name,
                            self.revision, self.device_map, 'cl100k_base',
                            'python_round', 6, True, 'conditional_newline'))

    @cached_property
    def _counter(self):
        return _HistoricalCounter()

    @cached_property
    def _compressor(self):
        require(version('llmlingua') == '0.2.2',
                'Install memfolder[llmlingua2] (llmlingua==0.2.2)')
        from huggingface_hub import snapshot_download
        from llmlingua import PromptCompressor
        checkpoint = snapshot_download(repo_id=self.model_name, revision=self.revision)
        # The recovered factory supplies only these three arguments. In
        # particular, it does not override dtype or the internal batch size.
        return PromptCompressor(model_name=str(checkpoint),
                                use_llmlingua2=True, device_map=self.device_map)

    def _compress(self, text, rate):
        source = text.strip()
        source_tokens = self._counter.count(source)
        kwargs = {'target_token': max(6, round(rate * source_tokens)),
                  'force_reserve_digit': True}
        if '\n' in source:
            kwargs['force_tokens'] = ['\n']
        with self._lock:
            result = self._compressor.compress_prompt(source, **kwargs)
        require(isinstance(result, dict) and
                isinstance(result.get('compressed_prompt'), (str, type(None))),
                'Invalid historical LLMLingua-2 response')
        output = (result.get('compressed_prompt') or '').strip()
        # The existing writer explicitly retains its source on empty output.
        # Other model failures propagate; no failed inference becomes a score.
        response = {'text': output, 'rate': rate, 'profile': PROFILE,
                'input_view': 'current_record',
                'input_text_sha256': sha256(text.encode('utf-8')).hexdigest(),
                'normalized_input_sha256': sha256(source.encode('utf-8')).hexdigest(),
                'output_text_sha256': sha256((output or source).encode('utf-8')).hexdigest(),
                'use_llmlingua2': True,
                # A single string has no context-level filtering in the
                # upstream algorithm; this flag describes effective behavior.
                'use_context_level_filter': False,
                'effective_kwargs': kwargs, 'budget_tokenizer': 'cl100k_base',
                'original_tokens': source_tokens,
                'compressed_tokens': self._counter.count(output or source),
                'implementation': 'llmlingua==0.2.2',
                'model_name': self.model_name, 'model_revision': self.revision,
                'device_map': self.device_map, 'constructor_policy': 'defaults',
                'fallback_reason': None if output else 'empty_classifier_output',
                'source_preserved': not bool(output),
                'request_fingerprint': fingerprint((self.cache_identity, text, rate, kwargs))}
        if not output:
            response['fallback_text'] = source
        return response

    async def compress(self, text, *, rate):
        validate_rate(rate)
        require(type(text) is str and bool(text.strip()),
                'Historical LLMLingua requires nonempty final Record text')
        return await asyncio.to_thread(self._compress, text, rate)

    async def close(self):
        def release():
            with self._lock:
                self.__dict__.pop('_compressor', None)
        await asyncio.to_thread(release)
