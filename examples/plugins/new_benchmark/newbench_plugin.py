"""Contributor-owned synthetic benchmark; imports public APIs only."""
from dataclasses import dataclass
from pathlib import Path

from memfolder.core import (
    ContentPart, ContractError, DatasetSample, EvaluationCase, EvaluationSet, FrozenMap,
    HistoryEvent, MemoryInput, PluginSpec, SampleRef, ScopeRef,
)
from memfolder.loading import LoadOptions, read_json
from memfolder.plugins import BuildContext

SPEC = PluginSpec(plugin_id='example.newbench',role='data_loader',
                  provides=('benchmark.samples','benchmark.memory_evaluation_separation'))


def require(condition,message):
    if not condition:
        raise ContractError(message)


@dataclass(frozen=True,kw_only=True)
class NewBenchmark:
    path: Path
    dataset_id: str
    split: str
    spec = SPEC

    @property
    def source_paths(self):
        return (self.path,)

    def samples(self):
        doc = read_json(self.path,options=LoadOptions())
        require(type(doc.data) is list,'NewBench source must be a list')
        for row in doc.data:
            require(type(row) is dict and set(row)=={'sample_id','turns','questions'},'Invalid NewBench row')
            reference = SampleRef(dataset_id=self.dataset_id,sample_id=row['sample_id'],split=self.split,
                                  dataset_fingerprint=doc.sha256)
            scope = ScopeRef(dataset_id=reference.dataset_id,sample_id=reference.sample_id,partition_id='conversation')
            history = tuple(HistoryEvent(event_id=turn['id'],scope=scope,sequence=index,
                parts=(ContentPart(modality='text',text=turn['text']),),speaker=turn['speaker'],native=FrozenMap(turn))
                for index,turn in enumerate(row['turns']))
            # Retain only turns in memory. Do not copy the whole row with QA labels.
            memory = MemoryInput(sample=reference,history=history)
            cases = tuple(EvaluationCase(question_id=question['id'],sample=reference,
                question=(ContentPart(modality='text',text=question['text']),),
                ground_truth=FrozenMap({'answers':question['answers']})) for question in row['questions'])
            yield DatasetSample(memory=memory,evaluation=EvaluationSet(sample=reference,cases=cases,
                                                                     protocol_id='example.newbench.qa.v1'))


def build(parameters: FrozenMap,*,context: BuildContext):
    require(set(parameters)<={'path','dataset_id','split'} and 'path' in parameters,'Unknown/missing NewBench parameters')
    dataset_id,split=parameters.get('dataset_id','newbench'),parameters.get('split','test')
    require(type(dataset_id) is str and bool(dataset_id) and type(split) is str and bool(split),'Invalid NewBench identity')
    return NewBenchmark(path=context.path(parameters['path']),dataset_id=dataset_id,split=split)


build.spec=SPEC
