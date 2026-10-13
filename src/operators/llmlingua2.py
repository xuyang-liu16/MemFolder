"""LLMLingua-2 text compression of final current Record outputs."""
from dataclasses import dataclass, replace
from hashlib import sha256
import math
from ..core import FrozenMap
from ..core.values import require
from ..component_runtime import emit, resolve, spec
from .record_operations import ConservativeRecordBuilder
from .contracts import TextWriteResult


def validate_rate(rate):
    require(type(rate) in (int, float) and math.isfinite(rate) and 0 < rate <= 1,
            'LLMLingua-2 rate must be a finite retention ratio in (0, 1]')


@dataclass(frozen=True)
class LLMLingua2Writer:
    rate: float = 0.55
    service: str = 'llmlingua2'
    spec = spec('llmlingua2.current_record_writer.v1', 'text_writer',
                diagnostics=('memfolder.operator.llmlingua2',))

    def __post_init__(self):
        validate_rate(self.rate)

    async def write(self, members, action, context):
        require(action.kind == 'rewrite' and action.input_view == 'current' and len(members) == 1,
                'LLMLingua-2 requires one final current Record per rewrite')
        source = members[0].text
        digest = sha256(source.encode('utf-8')).hexdigest()
        result = await resolve(context.services.require(self.service).compress(source, rate=self.rate))
        require(isinstance(result, dict) and result.get('rate') == self.rate and
                result.get('input_text_sha256') == digest and
                result.get('input_view') == 'current_record' and
                result.get('use_llmlingua2') is True and
                result.get('use_context_level_filter') is False,
                'LLMLingua-2 service input or compression configuration differs')
        text = result.get('text')
        require(type(text) is str, 'LLMLingua-2 returned a non-text result')
        reason = None if text.strip() else 'empty_classifier_output'
        fallback = source
        if reason and 'fallback_text' in result:
            fallback = result['fallback_text']
            require(type(fallback) is str and bool(fallback) and fallback == source.strip() and
                    result.get('normalized_input_sha256') == sha256(fallback.encode()).hexdigest(),
                    'Normalized fallback must bind the stripped current Record')
        metadata = FrozenMap({k: v for k, v in result.items() if k != 'text'})
        emit(context, self.spec.plugin_id, 'memfolder.operator.llmlingua2',
             nodes=(members[0].node_id,), rate=self.rate, input_view='current_record',
             input_text_sha256=digest, output_text_sha256=sha256((fallback if reason else text).encode()).hexdigest(),
             fallback_reason=reason, original_tokens=result.get('original_tokens'),
             compressed_tokens=result.get('compressed_tokens'))
        return TextWriteResult(text=fallback if reason else text,
            status='fallback' if reason else 'success', reason_code=reason,
            usage=FrozenMap({'local_classifier_calls': 1}), metadata=metadata)


@dataclass(frozen=True)
class CurrentRecordRewriteBuilder:
    """Retain current record identity/time/order while requiring fresh content vectors."""
    builder: object = ConservativeRecordBuilder()
    spec = spec('context.current_record_builder.v1', 'record_builder')

    async def build(self, inputs, action, written, context):
        require(len(inputs) == 1 and action.kind == 'rewrite' and action.input_view == 'current',
                'Context rewrite builder requires one current record')
        source = inputs[0]
        node = await resolve(self.builder.build(inputs, action, written, context))
        require(node.node_id == source.node_id, 'Context rewrite must retain current record ID')
        return replace(node, order=source.order,
            extensions=FrozenMap({**source.extensions, **node.extensions}))
