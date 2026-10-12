"""Validate prediction coverage, score separately, preserve absent/failed metrics."""
from dataclasses import dataclass
from ..core import EvaluationReport,MetricResult,FrozenMap
from ..core.values import require
from ..planning.common import spec,resolve
from .metrics import ExactMatch,TokenF1,EvidenceRecall


@dataclass(frozen=True)
class MetricEvaluator:
    metrics: tuple = (ExactMatch(),TokenF1(),EvidenceRecall())
    strict: bool = True
    spec=spec('evaluation.metrics','evaluator')
    async def evaluate(self,questions,predictions,context):
        require(len({p.question_id for p in predictions})==len(predictions),'Duplicate predictions')
        require(all(p.sample.identity==questions.sample.identity for p in predictions),'Prediction sample mismatch')
        ids={q.question_id for q in questions.cases};by_id={p.question_id:p for p in predictions}
        require(set(by_id)==ids,'Missing or unexpected predictions')
        measured=[]
        for case in questions.cases:
            for metric in self.metrics:
                try:
                    values=await resolve(metric.score(case,by_id[case.question_id],context))
                    require(all(type(v) is MetricResult and v.question_id==case.question_id for v in values),'Metric escaped question identity')
                    measured.extend(values)
                except Exception:
                    if self.strict:raise
                    measured.append(MetricResult(name=metric.spec.plugin_id,version='plugin-failure.v1',value=None,status='failed',question_id=case.question_id))
        require(len({(m.name,m.version,m.question_id) for m in measured})==len(measured),'Duplicate metric identity')
        return EvaluationReport(sample=questions.sample,protocol_id=questions.protocol_id,predictions=tuple(predictions),metrics=tuple(measured))


def aggregate(reports):
    groups={}
    for report in reports:
        synthetic=any(p.usage.get('test_only',False) for p in report.predictions)
        for m in report.metrics:groups.setdefault((report.protocol_id,m.name,m.version,synthetic),[]).append(m)
    return FrozenMap({'metrics':[{'protocol_id':protocol,'name':name,'version':version,'test_only':synthetic,'mean':sum(v.value for v in values if v.status=='measured')/sum(v.status=='measured' for v in values) if any(v.status=='measured' for v in values) else None,
        'measured':sum(v.status=='measured' for v in values),'not_run':sum(v.status=='not_run' for v in values),'failed':sum(v.status=='failed' for v in values)} for (protocol,name,version,synthetic),values in sorted(groups.items())]})


@dataclass(frozen=True)
class ProtocolEvaluator:
    routes: tuple
    fallback: object | None = None
    spec=spec('evaluation.protocol_router','evaluator')
    async def evaluate(self,questions,predictions,context):
        evaluator=dict(self.routes).get(questions.protocol_id,self.fallback)
        require(evaluator is not None,'No evaluator configured for this protocol')
        return await resolve(evaluator.evaluate(questions,predictions,context))
