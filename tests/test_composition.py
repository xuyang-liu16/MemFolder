"""Extension boundary checks; every model response is synthetic."""
from dataclasses import replace
import unittest

from memfolder.core import *
from memfolder.compression import CompressionEngine, DiagnosticCollector, ServiceMap
from memfolder.planning import *
from memfolder.planning.common import spec
from memfolder.operators import *
from test_compression import request, apply, sync, CTX, NUMPY, Words, ScriptedChat, operator_context


def protected_request():
    req = request()
    nodes = list(req.snapshot.records)
    nodes[0] = replace(nodes[0], retention=RetentionPolicy(may_merge=False))
    nodes[1] = replace(nodes[1], retention=RetentionPolicy(may_drop=False))
    snapshot = replace(req.snapshot, records=tuple(nodes))
    return replace(req, snapshot=snapshot,
        features=tuple(replace(b, input_fingerprint=snapshot.fingerprint) for b in req.features),
        budgets=(resolve_budget(snapshot, BudgetRequest(unit='nodes', limit=4)),))


@unittest.skipUnless(NUMPY, 'Install memfolder[algorithms]')
class CompositionTests(unittest.TestCase):
    def test_shared_selectors_respect_the_operation_when_crossed(self):
        req = protected_request()
        for selector in (DensityPeakAnchors(), RandomSelector(), DartSelector(), ClusterRepresentatives()):
            with self.subTest(selector=type(selector).__name__, operation='drop'):
                plan = sync(PrunePlanner(selector).plan(req, CTX)).plan
                kept = {a.member_ids[0] for a in plan.actions if a.kind == 'keep'}
                self.assertIn('n01', kept)
                self.assertEqual(len(kept), 4)
            with self.subTest(selector=type(selector).__name__, operation='merge'):
                plan, _, _ = apply(req, RecordFolderPlanner(anchors=selector))
                self.assertTrue(any(a.kind == 'keep' and a.member_ids == ('n00',) for a in plan.actions))
                self.assertEqual(len(plan.actions), 4)

    def test_noop_mainline_needs_no_embeddings_or_grounding(self):
        req = replace(request(target=9), features=())
        plan = sync(RecordFolderPlanner().plan(req, CTX)).plan
        self.assertTrue(all(a.kind == 'keep' for a in plan.actions))

    def test_async_cluster_plugin_is_awaited_by_representative_selector(self):
        class AsyncClusters:
            spec = KmeansClusters.spec
            async def partition(self, req, target, context):
                return KmeansClusters().partition(req, target, context)
        req = request()
        _, _, records = apply(req, PrunePlanner(ClusterRepresentatives(AsyncClusters())))
        self.assertEqual(len(records), 4)

    def test_chain_generator_rejects_backward_edges(self):
        class Backward:
            spec = TemporalCandidates.spec
            def generate(self, req, context):
                batch = TemporalCandidates().generate(req, context)
                first = batch.candidates[0]
                return replace(batch, candidates=(replace(first, source_id=first.target_id, target_id=first.source_id),))
        with self.assertRaisesRegex(ContractError, 'forward in time'):
            sync(RecordFolderPlanner(candidates=Backward()).plan(request(), CTX))

    def test_chain_generator_rejects_protected_endpoints(self):
        class ProtectedEndpoint:
            spec = TemporalCandidates.spec
            def generate(self, req, context):
                batch = TemporalCandidates().generate(req, context)
                first = batch.candidates[0]
                return replace(batch, candidates=(replace(first, source_id='n00'),))
        with self.assertRaisesRegex(ContractError, 'mergeable local nodes'):
            sync(RecordFolderPlanner(candidates=ProtectedEndpoint()).plan(protected_request(), CTX))

    def test_chain_matcher_rejects_branching_even_if_edges_are_accepted(self):
        class Accept:
            spec = AnchorGate.spec
            def decide(self, req, scores, context):
                info = req.extensions['memfolder.recordfolder']
                return GateBatch(score_fingerprint=fingerprint(scores), decisions=tuple(
                    GateDecision(candidate_id=s.candidate_id,
                        accepted=info['endpoints'][s.candidate_id][1] not in info['anchors'],
                        thresholds=FrozenMap({'gain': 1.0}), reason_codes=('test_gate',)) for s in scores.scores))
        class Branch:
            spec = ChainMatcher.spec
            def match(self, req, candidates, scores, gates, context):
                accepted = {d.candidate_id for d in gates.decisions if d.accepted}
                rows = [c for c in candidates.candidates if c.candidate_id in accepted]
                for a in rows:
                    for b in rows:
                        if a.source_id == b.source_id and a.target_id != b.target_id:
                            return CandidateSelection(candidate_fingerprint=fingerprint(candidates),
                                selected_ids=(a.candidate_id, b.candidate_id))
                raise AssertionError('Fixture needs two successors')
        with self.assertRaisesRegex(ContractError, 'one incoming and one outgoing'):
            sync(RecordFolderPlanner(gate=Accept(), matcher=Branch()).plan(request(), CTX))

    def test_legacy_memforest_group_budgets_survive_all_rounds(self):
        req = request(n=12, target=None, mode='repeat')
        budget = sync(resolve_memforest_budget(req, CTX, keep_ratio=.5))
        req = replace(req, budgets=(budget,))
        class Encoder:
            def encode(self, texts):
                return [(float(len(t)), float(sum(map(ord, t)) % 31), 1.) for t in texts]
        engine = CompressionEngine(MemForestPlanner(allocator=LegacyClusterCeil(.5)),
            TextOperator(ConcatWriter()), (SemanticEmbeddingFeatures(req.features[0].space), EventTimeFeatures(aggregation='latest')))
        # Features are regenerated on every revision, including the first.
        run = sync(engine.run(replace(req, features=()), services=ServiceMap({'embeddings': Encoder()})))
        self.assertEqual(len(run.snapshot.records), sum(t.limit for t in budget.targets))
        self.assertGreater(len(run.steps), 1)

    def test_graph_selector_cannot_select_from_the_other_class(self):
        class WrongClass:
            spec = SphericalCoverage.spec
            def select(self, req, ids, context):
                return ('n00',)  # media-connected, belongs to class two
        with self.assertRaisesRegex(ContractError, 'crossed its declared class'):
            sync(StreamMeCoPlanner(first_selector=WrongClass()).plan(request(graph=True, target=None), CTX))


class AsyncOperatorTests(unittest.TestCase):
    def test_custom_loop_stages_have_actual_zero_model_calls(self):
        class Extract:
            spec = FactPlanner.spec
            async def extract(self, lines, context):
                return (Fact('factual detail', 'Which detail?', 'detail', 'high', False),)
        class Compile:
            spec = ContextCompiler.spec
            async def compile(self, *args):
                return 'factual detail'
        class Verify:
            spec = BlindFactVerifier.spec
            async def verify(self, encoding, facts, context):
                return (True,)
        writer = ContextFolderWriter(fact_planner=Extract(), compiler=Compile(), verifier=Verify())
        req = request(n=1, target=1)
        context = operator_context(req.snapshot, ScriptedChat([]))
        action = Action(action_id='test', kind='rewrite', member_ids=('n00',), output_ids=('n00',), input_view='original')
        result = sync(writer.write((Member('n00', req.snapshot.records[0].text, 'unknown'),), action, context))
        self.assertEqual(result.usage['chat_calls'], 0)
        self.assertEqual(result.status, 'success')

    def test_native_writer_awaits_asynchronous_chat(self):
        class AsyncChat(ScriptedChat):
            async def complete(self, request):
                return super().complete(request)
        req = request(n=2, target=1)
        plan = sync(PartitionPlanner().plan(req, CTX)).plan
        client = AsyncChat(['merged text'])
        context = operator_context(req.snapshot, client)
        result = sync(TextOperator().apply(req.snapshot, plan, context))
        self.assertEqual(result.outcomes[0].outputs[0].text, 'merged text')
        self.assertEqual(len(client.requests), 1)

    def test_writer_metadata_is_detached_from_mutable_plugin_data(self):
        data = {'nested': {'count': 1}}
        output = TextWriteResult('text', metadata=data)
        data['nested']['count'] = 8
        self.assertEqual(output.metadata['nested']['count'], 1)
        with self.assertRaises(TypeError):
            output.metadata['nested']['count'] = 9


if __name__ == '__main__':
    unittest.main()
