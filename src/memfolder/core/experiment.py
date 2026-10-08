"""Serializable experiment results; no live objects or raw config."""
from .data import SampleRef
from .memory import ArtifactRef
from .evaluation import EvaluationReport
from .observation import RunManifest
from .values import Contract,FrozenMap,record,require


@record('memfolder.compression_statistics')
class CompressionStatistics(Contract):
    input_nodes: int
    output_nodes: int
    input_eligible: int
    output_eligible: int
    input_characters: int
    output_characters: int
    input_edges: int
    output_edges: int
    rounds: int
    elapsed_seconds: float
    node_retention: float | None
    character_retention: float | None
    measurement: FrozenMap = FrozenMap()
    def __post_init__(self):
        super().__post_init__()
        require(all(v>=0 for v in (self.input_nodes,self.output_nodes,self.input_eligible,self.output_eligible,
            self.input_characters,self.output_characters,self.input_edges,self.output_edges,self.rounds,self.elapsed_seconds)),'Negative compression statistic')
        require(self.input_eligible<=self.input_nodes and self.output_eligible<=self.output_nodes,'Invalid eligible count')


@record('memfolder.sample_run_result')
class SampleRunResult(Contract):
    sample: SampleRef
    source: ArtifactRef
    final: ArtifactRef
    materialized: ArtifactRef
    statistics: CompressionStatistics
    evaluation: EvaluationReport | None = None
    baseline_evaluation: EvaluationReport | None = None
    timings: FrozenMap = FrozenMap()
    usage: FrozenMap = FrozenMap()
    def __post_init__(self):
        super().__post_init__()
        require(self.evaluation is None or self.evaluation.sample.identity==self.sample.identity,'Result/evaluation sample mismatch')
        require(self.baseline_evaluation is None or self.baseline_evaluation.sample.identity==self.sample.identity,'Baseline/evaluation sample mismatch')


@record('memfolder.experiment_result')
class ExperimentResult(Contract):
    manifest: RunManifest
    samples: tuple[SampleRunResult,...]
    aggregate: FrozenMap = FrozenMap()
    def __post_init__(self):
        super().__post_init__()
        require(tuple(s.sample for s in self.samples)==self.manifest.samples,'Result manifest/sample mismatch')
