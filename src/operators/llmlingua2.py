"""LLMLingua-2 text compression of final current Record outputs."""
from dataclasses import dataclass, replace
from functools import cached_property
from hashlib import sha256
from pathlib import Path
import math
from ..core import FrozenMap, Snapshot, fingerprint, loads
from ..core.values import require
from ..component_runtime import emit, resolve, spec
from .record_operations import ConservativeRecordBuilder, display_timestamp, record_owner
from .contracts import Member, TextWriteResult


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


def format_group(members):
    return '\n'.join(f'{member.text} ({member.time})' for member in members)


@dataclass(frozen=True)
class GroupBudgetLLMLingua2Writer:
    source_snapshot: Path
    record_snapshot: Path
    budget_snapshot: Path
    calibration_groups: int = 20
    service: str = 'llmlingua2'
    spec = spec('llmlingua2.group_budget_writer.v1', 'text_writer',
                diagnostics=('memfolder.operator.llmlingua2',))

    def __post_init__(self):
        require(type(self.calibration_groups) is int and self.calibration_groups > 0,
                'Calibration group count must be positive')
        for name in ('source_snapshot', 'record_snapshot', 'budget_snapshot'):
            object.__setattr__(self, name, Path(getattr(self, name)))

    @property
    def source_paths(self):
        return self.source_snapshot, self.record_snapshot, self.budget_snapshot

    @cached_property
    def _groups(self):
        source, records, budgets = (loads(path.read_text(encoding='utf-8'), expected=Snapshot)
                                   for path in self.source_paths)
        references = {node.node_id: node for node in budgets.records}
        require(set(references) == {node.node_id for node in records.records},
                'Budget snapshot must cover the same record IDs')
        originals = {};seen = set();groups = {}
        for node in source.records:
            for origin in node.origins:
                require(origin not in originals, 'Source snapshot has ambiguous origin identity')
                originals[origin] = node
        for node in records.records:
            reference = references[node.node_id]
            require(set(reference.origins) == set(node.origins) and reference.scope == node.scope
                    and record_owner(reference) == record_owner(node),
                    'Budget record lineage, scope or owner differs')
            require(not seen.intersection(node.origins), 'Record groups reuse source origins')
            seen.update(node.origins);members = {}
            for origin in node.origins:
                require(origin in originals, 'Source snapshot does not cover a record origin')
                member = originals[origin]
                require((member.scope.dataset_id, member.scope.sample_id) ==
                        (node.scope.dataset_id, node.scope.sample_id) and
                        record_owner(member) == record_owner(node),
                        'Source group crosses sample or owner boundaries')
                members[member.node_id] = member
            require({origin for member in members.values() for origin in member.origins} == set(node.origins),
                    'Source member resolution changed group lineage')
            require(bool(reference.text.strip()), 'Budget record has empty reference text')
            groups[node.node_id] = (node, tuple(Member(member.node_id, member.text,
                display_timestamp(member, 'anchor')) for member in members.values()), reference.text)
        return groups

    @cached_property
    def _calibration_inputs(self):
        samples = {}
        for record, members, _ in self._groups.values():
            key = (record.scope.dataset_id, record.scope.sample_id)
            values = samples.setdefault(key, [])
            if len(values) < self.calibration_groups:
                values.append(format_group(members))
        return {key: tuple(values) for key, values in samples.items()}

    async def write(self, members, action, context):
        from ..services import GROUP_BUDGET_PROFILE, TiktokenCounter
        require(action.kind == 'rewrite' and action.input_view == 'current' and len(members) == 1,
                'Group budget writer requires one current Record per rewrite')
        current = members[0]
        require(current.node_id in self._groups, 'Current Record is absent from the budget snapshot')
        record, originals, budget_text = self._groups[current.node_id]
        require(action.member_ids == (current.node_id,) and current.text == record.text,
                'Current Record differs from the declared record snapshot')
        calibration = self._calibration_inputs[(record.scope.dataset_id, record.scope.sample_id)]
        result = await resolve(context.services.require(self.service).compress_group(originals,
            budget_text=budget_text, calibration_inputs=calibration))
        require(isinstance(result, dict) and result.get('profile') == GROUP_BUDGET_PROFILE and
                result.get('input_view') == 'original_group' and
                result.get('formatted_input_sha256') == sha256(format_group(originals).encode('utf-8')).hexdigest()
                and result.get('budget_text_sha256') == sha256(budget_text.encode('utf-8')).hexdigest(),
                'Group token-budget service input differs')
        text = result.get('text');require(type(text) is str, 'LLMLingua-2 returned a non-text result')
        empty = not text.strip()
        reason = 'empty_classifier_output' if empty else 'classifier_exception' if result['status'] == 'exception_fallback' else None
        output = (originals[0].text.strip() or 'empty') if empty else text
        metadata = FrozenMap({**{key: value for key, value in result.items() if key != 'text'},
            'record_node_id': current.node_id, 'member_ids': tuple(member.node_id for member in originals),
            'source_record_fingerprint': fingerprint(record),
            'lineage_fingerprint': fingerprint(tuple(sorted(record.origins, key=fingerprint))),
            'output_text_sha256': sha256(output.encode('utf-8')).hexdigest(),
            'classifier_output_tokens': result['classifier_output_tokens'],
            'compressed_tokens': TiktokenCounter().count(output),
            'status': 'empty_output_fallback' if empty else result['status'],
            'fallback_reason': reason})
        emit(context, self.spec.plugin_id, 'memfolder.operator.llmlingua2',
             nodes=(current.node_id,), actions=(action.action_id,), **metadata)
        return TextWriteResult(text=output, status='fallback' if reason else 'success', reason_code=reason,
            usage=FrozenMap({'local_classifier_calls': int(result['classifier_called'])}), metadata=metadata)


@dataclass(frozen=True)
class CurrentRecordRewriteBuilder:
    """Retain current record identity/time/order while requiring fresh content vectors."""
    builder: object = ConservativeRecordBuilder()
    spec = spec('context.current_record_builder.v1', 'record_builder')

    async def build(self, inputs, action, written, context):
        require(len(inputs) == 1 and action.kind == 'rewrite' and action.input_view == 'current',
                'Context rewrite builder requires one current record')
        source = inputs[0]
        if 'source_record_fingerprint' in written.metadata:
            require(written.metadata['source_record_fingerprint'] == fingerprint(source),
                    'Current Record differs from the writer source record')
        node = await resolve(self.builder.build(inputs, action, written, context))
        require(node.node_id == source.node_id, 'Context rewrite must retain current record ID')
        return replace(node, order=source.order,
            extensions=FrozenMap({**source.extensions, **node.extensions}))
