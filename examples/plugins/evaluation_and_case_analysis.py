"""Extend evaluation with an answer metric, trace observer and case-lineage writer."""
from dataclasses import dataclass
from memfolder.artifacts import write_json
from memfolder.component_runtime import resolve
from memfolder.core import ContractError, FrozenMap, MetricResult, PluginSpec
from memfolder.core.values import require
from memfolder.plugins import PluginRequest


@dataclass(frozen=True)
class AnswerLength:
    spec = PluginSpec(plugin_id='example.answer_length', role='metric')

    def score(self, case, prediction, context):
        length = sum(len(part.text or '') for part in prediction.answer)
        return (MetricResult(name='answer_characters', version='example.v1',
                             value=float(length), question_id=case.question_id),)


@dataclass(frozen=True)
class TraceObserver:
    spec = PluginSpec(plugin_id='example.trace_observer', role='observer')

    def open(self, context):
        object.__setattr__(self, '_state', {'events': 0, 'verified_public_artifacts': 0})

    def on_event(self, event, context):
        self._state['events'] += 1
        for ref in event.artifact_refs:
            if not context.artifacts.verify(ref):
                raise ContractError('Missing published artifact')
            context.artifacts.read_json(ref)
            self._state['verified_public_artifacts'] += 1

    def close(self, context):
        context.reports.write_json('external-observer.json', FrozenMap(self._state))


@dataclass(frozen=True)
class CaseWriter:
    base_writer: object
    spec = PluginSpec(plugin_id='example.case_writer', role='native_writer')

    @property
    def reader_capabilities(self):
        return (*getattr(self.base_writer, 'reader_capabilities', ()), 'case.lineage.json')

    async def write(self, package, directory, context):
        files = await resolve(self.base_writer.write(package, directory, context))
        case_file = write_json(directory, 'cases.json', {
            'snapshot_fingerprint': package.snapshot_fingerprint,
            'node_id_map': package.node_id_map,
            'lineage': package.lineage,
            'source_snapshot': 'source.snapshot.json',
            'final_snapshot': 'snapshot.json',
        })
        return (*files, case_file)


def metric_factory(parameters, *, context):
    if parameters:
        raise ContractError('AnswerLength has no parameters')
    return AnswerLength()


metric_factory.spec = AnswerLength.spec


def observer_factory(parameters, *, context):
    if parameters:
        raise ContractError('TraceObserver has no parameters')
    return TraceObserver()


observer_factory.spec = TraceObserver.spec


def build_case_writer(parameters, *, context):
    require(set(parameters) <= {'base_writer'}, 'Unknown case writer parameter')
    request = PluginRequest.from_mapping(
        parameters.get('base_writer', {'plugin': 'mem0-points-writer'}))
    writer = context.registry.create(request, role='native_writer', context=context,
                                     available=context.available).instance
    return CaseWriter(writer)


build_case_writer.spec = CaseWriter.spec
