"""Public trace queries and case comparisons, usable after the algorithm exits."""
from dataclasses import replace
from pathlib import Path
from .core import (ArtifactRef,CaseView,DiagnosticLinks,EventEnvelope,FrozenMap,OriginRef,
    RunComparison,RunManifest,TraceCoverage,from_data,loads,to_data)
from .core.values import require
from .artifacts import ArtifactStore,PublicArtifacts


class FileRunReader:
    def __init__(self,directory):
        self.root=Path(directory).resolve();self.store=ArtifactStore(self.root)
        self.manifest=loads((self.root/'run.manifest.json').read_text(encoding='utf-8'),expected=RunManifest)
        self.events=();self.allowed=set();self.coverage=self.manifest.coverage
        require(self.coverage is not None,'Run has no coverage declaration')
        index=next((r for r in self.manifest.artifacts if r.path=='trace/index.json'),None)
        if index is not None:
            data=self.store.read(index)
            self.events=tuple(from_data(EventEnvelope,v) for v in data['events'])
            self.allowed={from_data(ArtifactRef,v) for v in data['public_artifacts']}
            require(from_data(TraceCoverage,data['coverage'])==self.coverage,'Trace coverage mismatch')
            require(all(e.run_id==self.manifest.run_id for e in self.events) and [e.sequence for e in self.events]==list(range(len(self.events))),'Invalid trace ordering/run identity')
            missing=tuple(sorted(r.path for r in self.allowed if not self.store.verify(r)))
            events_ref=next((r for r in self.manifest.artifacts if r.path=='trace/events.jsonl'),None)
            if events_ref is None or not self.store.verify(events_ref):missing+=('trace/events.jsonl',)
            if missing:self.coverage=replace(self.coverage,complete_for_capture=False,missing_artifacts=missing)
        self.artifacts=PublicArtifacts(self.store,self.allowed)

    def links(self,event):return from_data(DiagnosticLinks,to_data(event.extensions.get('memfolder.links',FrozenMap())))

    def sample(self,dataset_id,sample_id):
        matches=[s for s in self.manifest.samples if (s.dataset_id,s.sample_id)==(dataset_id,sample_id)]
        require(len(matches)==1,'Case sample is absent or ambiguous');return matches[0]

    def _case(self,sample,origins,*,actions=(),questions=(),branch=None):
        require(sample in self.manifest.samples,'Case sample does not belong to run')
        selected=[];requested_origins=tuple(origins);origins=set(origins);actions=set(actions);questions=set(questions)
        # Close the provenance links first, then include each relevant stage once.
        pool=[e for e in self.events if e.sample==sample and (branch is None or e.extensions.get('memfolder.branch')==branch)]
        changed=True
        while changed:
            before=(len(origins),len(actions))
            for e in pool:
                links=self.links(e)
                if e.action_id is not None or e.question_id is not None:
                    if origins.intersection(links.origins) or actions.intersection(links.action_ids) or questions.intersection(links.question_ids):
                        origins.update(links.origins);actions.update(links.action_ids)
            changed=before!=(len(origins),len(actions))
        for e in pool:
            links=self.links(e)
            if origins.intersection(links.origins) or actions.intersection(links.action_ids) or questions.intersection(links.question_ids):selected.append(e)
        refs=tuple(dict.fromkeys(r for e in selected for r in e.artifact_refs))
        # The result is complete for the chosen capture policy, not necessarily a
        # full text/vector record. Omitted cases remain explicitly not_recorded.
        status='not_recorded' if not selected else 'complete_for_capture' if self.coverage.complete_for_capture else 'partial'
        return CaseView(run_id=self.manifest.run_id,sample=sample,origins=tuple(sorted(requested_origins or origins,key=lambda o:(o.scope.partition_id,o.source_id,o.revision))),
            coverage=self.coverage,events=tuple(selected),artifacts=refs,status=status,
            extensions=FrozenMap({'memfolder.branch':branch,'memfolder.question_ids':sorted(questions),'memfolder.action_ids':sorted(actions)}))

    def by_origin(self,origin):return self._case(self.sample(origin.scope.dataset_id,origin.scope.sample_id),(origin,))
    def by_action(self,sample,action_id):return self._case(sample,(),actions=(action_id,))
    def by_question(self,sample,question_id,*,branch=None):return self._case(sample,(),questions=(question_id,),branch=branch)
    def compare(self,other,origins):
        require(bool(origins),'Compare requires original identities')
        first=origins[0];left=self._case(self.sample(first.scope.dataset_id,first.scope.sample_id),origins)
        right=other._case(other.sample(first.scope.dataset_id,first.scope.sample_id),origins)
        roles={'reader','evaluator','metric','answerer','retriever','service','judge_prompt','reader_prompt'}
        a={(b.plugin_id,b.role,b.parameters_fingerprint,b.implementation_revision) for b in self.manifest.bindings if b.role in roles}
        b={(b.plugin_id,b.role,b.parameters_fingerprint,b.implementation_revision) for b in other.manifest.bindings if b.role in roles}
        differences=('reader/evaluation/service bindings differ',) if a!=b else ()
        if self.manifest.extensions.get('memfolder.protocols')!=other.manifest.extensions.get('memfolder.protocols'):differences+=('question/evaluation protocols differ',)
        alignment='incomparable' if left.sample.identity!=right.sample.identity else 'partial' if differences or left.status!='complete_for_capture' or right.status!='complete_for_capture' else 'matched'
        return RunComparison(left=left,right=right,alignment=alignment,protocol_differences=differences)

    def origins(self,*,sample_id=None,source_id=None):
        return tuple(dict.fromkeys(o for e in self.events for o in self.links(e).origins if (sample_id is None or o.scope.sample_id==sample_id) and (source_id is None or o.source_id==source_id)))

    def export(self,case,directory):
        require(case.run_id==self.manifest.run_id,'Case belongs to another run')
        directory=Path(directory);require(not directory.exists(),'Case output already exists');directory.mkdir(parents=True)
        store=ArtifactStore(directory);store.put('case.json',case)
        for ref in case.artifacts:
            value=self.artifacts.read_json(ref);store.put('artifacts/'+Path(ref.path).name,value)
        return directory/'case.json'
