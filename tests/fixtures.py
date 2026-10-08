"""Synthetic shape fixtures, NOT implementations or outputs of named algorithms."""
from dataclasses import replace
from memfolder.core import *

BASELINES = ('MemFolder', 'MemForest', 'ToMe', 'DART', 'StreamMeCo',
             'RandomMerge', 'RandomPrune', 'KmeansPrune', 'KmeansMerge')
BENCHMARKS = ('locomo', 'personamem', 'longmemeval', 'm3.robot', 'm3.web')
FRAMEWORKS = ('mem0', 'memos', 'm3')
PRUNERS = {'DART', 'StreamMeCo', 'RandomPrune', 'KmeansPrune'}
SPACE = EmbeddingSpace(provider='fixture', model='synthetic', revision='1', dimension=2)


def sample(benchmark='locomo', framework='mem0'):
    ref = SampleRef(dataset_id=benchmark, sample_id='sample_001', split='fixture',
                    dataset_fingerprint=fingerprint({'benchmark': benchmark, 'content': 'synthetic-v1'}))
    scope = ScopeRef(dataset_id=benchmark, sample_id=ref.sample_id, partition_id='conversation_or_clip')
    clock = 'video:sample_001:seconds' if benchmark.startswith('m3.') else 'unix_seconds'
    assets = (ArtifactRef(artifact_id='video', path='assets/video.json', sha256='0'*64,
                          media_type='application/json', schema_id='fixture.video'),) if benchmark.startswith('m3.') else ()
    records = []
    history = []
    for i in range(4):
        parts = (ContentPart(modality='text', text=f'Memory {i}: Alice prefers tea.'),)
        if assets:
            parts += (ContentPart(modality='video', artifact=assets[0]),)
        n = MemoryRecord(node_id=f'n{i}', scope=scope, order=i,
            origins=(OriginRef(scope=scope, source_id=f'source_{i}'),), parts=parts,
            available_at=TimePoint(value=i, clock=clock),
            native=FrozenMap({'framework': framework, 'backend_id': f'native-{i}',
                             'cube_id': 'cube0' if framework == 'memos' else None}))
        n = replace(n, embeddings=(Embedding(space=SPACE, source_fingerprint=n.content_fingerprint,
                                            values=(1.0, float(i))),))
        records.append(n)
        history.append(HistoryEvent(event_id=f'h{i}', scope=scope, sequence=i, parts=parts,
                                    occurred_at=n.available_at, speaker='Alice'))
    edges = ()
    if framework == 'm3':
        records.append(MemoryRecord(node_id='identity', scope=scope, order=0,
            origins=(OriginRef(scope=scope, source_id='identity'),),
            parts=(ContentPart(modality='structured', data=FrozenMap({'entity': 'Alice'})),),
            eligible=False, kind='identity',
            retention=RetentionPolicy(may_drop=False, may_merge=False, may_rewrite=False)))
        edges = tuple(GraphEdge(edge_id=f'e{i}', source_id=f'n{i}', target_id='identity',
                                relation='describes_entity', weight=0.5) for i in range(4))
    snap = Snapshot(snapshot_id='snapshot', records=tuple(records), edges=edges, assets=assets)
    truth = {'answer': 'tea', 'alternatives': ['Tea']} if benchmark != 'personamem' else {'preference': 'tea', 'persona_id': 'Alice'}
    options = {}
    if benchmark.startswith('m3.'):
        truth = {'answer_index': 0}
        options = {'choices': ['tea', 'coffee']}
    case = EvaluationCase(question_id='q1', sample=ref,
        question=(ContentPart(modality='text', text='What does Alice prefer?'),),
        ground_truth=FrozenMap(truth), options=options, as_of=TimePoint(value=4, clock=clock),
        evidence=(records[0].origins[0],))
    return DatasetSample(memory=MemoryInput(sample=ref, history=tuple(history), initial_snapshot=snap, assets=assets),
                         evaluation=EvaluationSet(sample=ref, cases=(case,), protocol_id=f'{benchmark}.fixture'))


def plan_and_result(snap, method='MemFolder'):
    """Predefined valid prune/merge shapes; no selection algorithm is run."""
    nodes = [n for n in snap.records if n.eligible]
    actions, outcomes = [], []
    if method in PRUNERS:
        for i, n in enumerate(nodes):
            action = Action(action_id=f'a{i}', kind='drop' if i < 2 else 'keep', member_ids=(n.node_id,),
                            output_ids=() if i < 2 else (n.node_id,))
            actions.append(action)
            outcomes.append(ActionOutcome(action_id=action.action_id, status='success',
                                           outputs=() if i < 2 else (n,)))
    else:
        for i in range(0, len(nodes), 2):
            pair = nodes[i:i+2]
            output_id = f'merged_{i}'
            action = Action(action_id=f'a{i}', kind='merge', member_ids=tuple(n.node_id for n in pair), output_ids=(output_id,))
            output = MemoryRecord(node_id=output_id, scope=pair[0].scope, order=max(n.order for n in pair),
                origins=tuple(o for n in pair for o in n.origins),
                parts=(ContentPart(modality='text', text='Synthetic combined memory.'),),
                available_at=max((n.available_at for n in pair), key=lambda t: t.value))
            actions.append(action)
            outcomes.append(ActionOutcome(action_id=action.action_id, status='success', outputs=(output,)))
    plan = ActionPlan(plan_id='fixture.plan', input_fingerprint=snap.fingerprint,
                      target_ids=tuple(n.node_id for n in nodes), actions=tuple(actions))
    result = OperatorResult(plan_fingerprint=plan.fingerprint, outcomes=tuple(outcomes))
    return plan, result
