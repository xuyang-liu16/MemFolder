"""Contract invariants, independent of model calls and backend installations."""
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from memfolder.core import *
from fixtures import BASELINES, BENCHMARKS, FRAMEWORKS, SPACE, plan_and_result, sample


class ValueTests(unittest.TestCase):
    def test_deep_immutability_and_detachment(self):
        original = {'nested': {'values': [1, {'n': 2}]}}
        frozen = FrozenMap(original)
        original['nested']['values'][1]['n'] = 99
        self.assertEqual(frozen['nested']['values'][1]['n'], 2)
        with self.assertRaises(TypeError): frozen['nested']['values'][1]['n'] = 0
        with self.assertRaises(AttributeError): frozen._values = {}
        with self.assertRaises(FrozenInstanceError): sample().memory.initial_snapshot.revision = 9

    def test_opaque_resources_and_nonfinite_values_rejected(self):
        for value in (object(), float('nan'), float('inf'), {1: 'non-string-key'}):
            with self.subTest(value=type(value).__name__), self.assertRaises(ContractError): FrozenMap({'v': value})
        with self.assertRaises(ContractError): TimePoint(value=10**1000, clock='clock')

    def test_strict_types_and_metadata_shape(self):
        for value in (True, '1', 1.5):
            with self.subTest(value=value), self.assertRaises(ContractError):
                TimePoint(value=1, clock='clock')
                replace(sample().memory.initial_snapshot, revision=value)
        with self.assertRaises(ContractError): replace(sample().memory.initial_snapshot, extensions=None)

    def test_version_schema_and_unknown_fields_rejected(self):
        snap = sample().memory.initial_snapshot
        wire = json.loads(dumps(snap))
        for change in ({'schema_version': 2}, {'schema_version': True}, {'schema_id': 'unknown.schema'}):
            with self.subTest(change=change), self.assertRaises(ContractError): loads(json.dumps({**wire, **change}))
        wire['data']['unknown'] = 'bad'
        with self.assertRaises(ContractError): loads(json.dumps(wire))
        with self.assertRaises(ContractError): loads('{"schema_id":"a","schema_id":"b"}')
        with self.assertRaises(ContractError): loads(dumps(snap), expected=ActionPlan)

    def test_extensions_roundtrip_and_fingerprint_stability(self):
        snap = replace(sample().memory.initial_snapshot, extensions={'lab.algorithm': {'weights': [1, 2]}})
        self.assertEqual(loads(dumps(snap)), snap)
        self.assertEqual(fingerprint(FrozenMap({'a': 1, 'b': 2})), fingerprint(FrozenMap({'b': 2, 'a': 1})))
        with self.assertRaises(ContractError): replace(snap, extensions={'not_namespaced': 1})

    def test_contributor_can_declare_wire_schema(self):
        @record('lab.test_custom_state')
        class CustomState(Contract):
            value: int
            extensions: FrozenMap = FrozenMap()
        value = CustomState(value=5, extensions={'lab.tags': ['x']})
        self.assertEqual(loads(dumps(value), expected=CustomState), value)


class MemoryTests(unittest.TestCase):
    def setUp(self): self.snap = sample('m3.robot', 'm3').memory.initial_snapshot

    def test_graph_assets_and_multimodal_roundtrip(self):
        self.assertTrue(self.snap.edges and self.snap.assets)
        self.assertFalse(self.snap.records[-1].eligible)
        self.assertEqual(loads(dumps(self.snap)), self.snap)

    def test_duplicate_ids_and_dangling_edges_rejected(self):
        with self.assertRaises(ContractError): replace(self.snap, records=self.snap.records + self.snap.records[:1])
        with self.assertRaises(ContractError): replace(self.snap, records=self.snap.records[1:])
        with self.assertRaises(ContractError): replace(self.snap, edges=self.snap.edges + self.snap.edges[:1])

    def test_stale_embedding_and_mixed_dimensions_rejected(self):
        node = self.snap.records[0]
        with self.assertRaises(ContractError): replace(node, parts=(ContentPart(modality='text', text='different'),))
        changed = replace(node, parts=(ContentPart(modality='text', text='different'),), embeddings=())
        self.assertNotEqual(changed.content_fingerprint, node.content_fingerprint)
        with self.assertRaises(ContractError): Embedding(space=SPACE, source_fingerprint=changed.content_fingerprint, values=(1,))
        with self.assertRaises(ContractError): replace(node, embeddings=node.embeddings * 2)

    def test_visibility_and_clock_identity(self):
        node = self.snap.records[2]
        self.assertFalse(node.visible_at(TimePoint(value=1, clock='video:sample_001:seconds')))
        self.assertTrue(node.visible_at(TimePoint(value=2, clock='video:sample_001:seconds')))
        with self.assertRaises(ContractError): node.visible_at(TimePoint(value=2, clock='unix_seconds'))
        with self.assertRaises(ContractError): TimeRange(start=TimePoint(value=2, clock='a'), end=TimePoint(value=3, clock='b'))

    def test_artifact_paths_cannot_escape(self):
        for path in ('../file', 'a/../file', '/absolute', 'C:/drive', 'a\\file', './file', 'a//file', '.', 'a\x00file'):
            with self.subTest(path=path), self.assertRaises(ContractError):
                ArtifactRef(artifact_id='a', path=path, sha256='0'*64, media_type='x', schema_id='x')
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(self.snap.assets[0].resolve(Path(folder)).is_relative_to(Path(folder).resolve()))

    def test_delta_requires_explicit_edge_updates_and_advances_revision(self):
        delta = MemoryDelta(delta_id='d', base_fingerprint=self.snap.fingerprint, removed_ids=('n0',))
        with self.assertRaises(ContractError): apply_delta(self.snap, delta)
        after = apply_delta(self.snap, replace(delta, removed_edge_ids=('e0',)))
        self.assertEqual(after.revision, self.snap.revision + 1)
        self.assertEqual(after.assets, self.snap.assets)
        with self.assertRaises(ContractError): apply_delta(after, delta)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.snap = sample().memory.initial_snapshot
        self.plan, self.result = plan_and_result(self.snap)

    def test_valid_merge_prune_and_unselected_assets(self):
        for method in BASELINES:
            snap = sample('m3.robot', 'm3').memory.initial_snapshot
            plan, result = plan_and_result(snap, method)
            validate_result(snap, plan, result)
            self.assertIn(snap.records[-1], result_records(snap, plan, result))

    def test_stale_plan_missing_and_overlapping_targets(self):
        with self.assertRaises(ContractError): validate_plan(replace(self.snap, revision=1), self.plan)
        with self.assertRaises(ContractError): validate_plan(self.snap, replace(self.plan, actions=self.plan.actions[:1]))
        extra = replace(self.plan.actions[0], action_id='other')
        with self.assertRaises(ContractError): validate_plan(self.snap, replace(self.plan, actions=self.plan.actions + (extra,)))

    def test_output_cannot_overwrite_untouched_node(self):
        action = Action(action_id='a', kind='rewrite', member_ids=('n0',), output_ids=('n1',))
        plan = replace(self.plan, target_ids=('n0',), actions=(action,))
        with self.assertRaises(ContractError): validate_plan(self.snap, plan)

    def test_cross_scope_needs_runtime_authorization_and_output_scope(self):
        node = replace(self.snap.records[1], scope=replace(self.snap.records[1].scope, partition_id='other'))
        snap = replace(self.snap, records=(self.snap.records[0], node, *self.snap.records[2:]))
        plan = replace(self.plan, input_fingerprint=snap.fingerprint)
        with self.assertRaises(ContractError): validate_plan(snap, plan)
        plan = replace(plan, boundary='sample', actions=(replace(plan.actions[0], output_scope=node.scope), plan.actions[1]))
        with self.assertRaises(ContractError): validate_plan(snap, plan)
        validate_plan(snap, plan, allowed_boundary='sample')

    def test_locked_nodes_cannot_be_transformed(self):
        n = replace(self.snap.records[0], retention=RetentionPolicy(may_drop=False, may_merge=False, may_rewrite=False))
        snap = replace(self.snap, records=(n, *self.snap.records[1:]))
        with self.assertRaises(ContractError): validate_plan(snap, replace(self.plan, input_fingerprint=snap.fingerprint))

    def test_keep_is_full_semantic_identity(self):
        plan, result = plan_and_result(self.snap, 'RandomPrune')
        kept = result.outcomes[2]
        wrong = replace(kept.outputs[0], native={'backend_id': 'changed'})
        altered = replace(result, outcomes=(*result.outcomes[:2], replace(kept, outputs=(wrong,)), result.outcomes[3]))
        with self.assertRaises(ContractError): validate_result(self.snap, plan, altered)

    def test_lineage_loss_invention_and_visibility_widening_rejected(self):
        outcome = self.result.outcomes[0]
        node = outcome.outputs[0]
        for wrong in (replace(node, origins=node.origins[:1]),
                      replace(node, origins=(*node.origins, self.snap.records[2].origins[0])),
                      replace(node, available_at=TimePoint(value=-1, clock='unix_seconds'))):
            result = replace(self.result, outcomes=(replace(outcome, outputs=(wrong,)), self.result.outcomes[1]))
            with self.assertRaises(ContractError): validate_result(self.snap, self.plan, result)

    def test_retention_policy_propagates_through_merge(self):
        n = replace(self.snap.records[0], retention=RetentionPolicy(may_drop=False))
        snap = replace(self.snap, records=(n, *self.snap.records[1:]))
        plan = replace(self.plan, input_fingerprint=snap.fingerprint)
        result = replace(self.result, plan_fingerprint=plan.fingerprint)
        with self.assertRaises(ContractError): validate_result(snap, plan, result)
        outcome = result.outcomes[0]
        fixed = replace(outcome.outputs[0], retention=RetentionPolicy(may_drop=False))
        validate_result(snap, plan, replace(result, outcomes=(replace(outcome, outputs=(fixed,)), result.outcomes[1])))

    def test_declared_custom_action_supports_new_module_without_core_change(self):
        action = Action(action_id='x', kind='lab.identity_batch', member_ids=('n0', 'n1'), output_ids=('n0', 'n1'))
        plan = replace(self.plan, target_ids=('n0', 'n1'), actions=(action,))
        rule = ActionRule(min_members=1, max_members=None, min_outputs=1, max_outputs=None, preserves_records=True)
        with self.assertRaises(ContractError): validate_plan(self.snap, plan)
        result = OperatorResult(plan_fingerprint=plan.fingerprint, outcomes=(ActionOutcome(action_id='x', status='success', outputs=self.snap.records[:2]),))
        validate_result(self.snap, plan, result, custom_rules={'lab.identity_batch': rule})
        with self.assertRaises(ContractError): validate_plan(self.snap, plan, custom_rules={'keep': rule})

    def test_fallback_and_failed_outcomes_are_explicit(self):
        with self.assertRaises(ContractError): replace(self.result.outcomes[0], status='fallback')
        fallback = replace(self.result.outcomes[0], status='fallback', reason_code='native_after_codec_failure')
        validate_result(self.snap, self.plan, replace(self.result, outcomes=(fallback, self.result.outcomes[1])))
        failed = replace(fallback, status='failed', outputs=())
        with self.assertRaises(ContractError): validate_result(self.snap, self.plan, replace(self.result, outcomes=(failed, self.result.outcomes[1])))

    def test_wrapper_projection_keeps_records_and_assets(self):
        projected = Snapshot(snapshot_id=self.snap.snapshot_id, revision=1, records=result_records(self.snap, self.plan, self.result))
        validate_projection(self.snap, self.plan, self.result, projected)
        with self.assertRaises(ContractError): validate_projection(self.snap, self.plan, self.result, replace(projected, records=projected.records[:1]))

    def test_embedding_refresh_cannot_change_memory(self):
        fresh = tuple(replace(n, embeddings=(Embedding(space=SPACE, source_fingerprint=n.content_fingerprint, values=(2, 1)),)) for n in self.snap.records)
        validate_embedding_refresh(self.snap, replace(self.snap, records=fresh))
        with self.assertRaises(ContractError): validate_embedding_refresh(self.snap, replace(self.snap, revision=1, records=fresh))


class BudgetAndFeatureTests(unittest.TestCase):
    def setUp(self): self.snap = sample().memory.initial_snapshot

    def test_zero_budget_and_explicit_rounding(self):
        for rule, expected in (('half_even', 2), ('half_up', 3), ('floor', 2), ('ceil', 3)):
            budget = resolve_budget(self.snap, BudgetRequest(unit='nodes', ratio=.625, rounding=rule))
            self.assertEqual(budget.targets[0].limit, expected)
        self.assertEqual(resolve_budget(self.snap, BudgetRequest(unit='nodes', ratio=0)).targets[0].limit, 0)

    def test_group_budgets_partition_and_round_independently(self):
        groups = (BudgetGroup(group_id='c0', member_ids=('n0', 'n1', 'n2')), BudgetGroup(group_id='c1', member_ids=('n3',)))
        request = BudgetRequest(unit='nodes', ratio=.5, rounding='ceil', allocation='group')
        budget = resolve_budget(self.snap, request, groups=groups)
        self.assertEqual([t.limit for t in budget.targets], [2, 1])
        with self.assertRaises(ContractError): resolve_budget(self.snap, request, groups=(groups[0],))
        with self.assertRaises(ContractError): resolve_budget(self.snap, request, groups=groups + (groups[0],))

    def test_text_units_need_declared_measurement(self):
        with self.assertRaises(ContractError): BudgetRequest(unit='tokens', ratio=.5)
        request = BudgetRequest(unit='tokens', ratio=.5, measurement_id='fixture.tokenizer.v1')
        with self.assertRaises(ContractError): resolve_budget(self.snap, request)
        budget = resolve_budget(self.snap, request, measurements={f'n{i}': 5 for i in range(4)})
        self.assertEqual(budget.targets[0].limit, 10)

    def test_locked_budget_and_enforcement(self):
        locked = tuple(replace(n, retention=RetentionPolicy(may_drop=False, may_merge=False)) for n in self.snap.records)
        with self.assertRaises(ContractError): resolve_budget(replace(self.snap, records=locked), BudgetRequest(unit='nodes', limit=1))
        budget = resolve_budget(self.snap, BudgetRequest(unit='nodes', limit=2, allocation='global'))
        validate_budget(budget, {'global': 2})
        with self.assertRaises(ContractError): validate_budget(budget, {'global': 1})
        with self.assertRaises(ContractError): validate_budget(budget, {})
        upper = replace(budget, request=replace(budget.request, enforcement='at_most'))
        validate_budget(upper, {'global': 1})

    def test_pooled_features_do_not_become_stored_text_embeddings(self):
        batch = FeatureBatch(name='tome.weighted', input_fingerprint=self.snap.fingerprint, space=SPACE,
            vector_semantics='pooled', rows=(FeatureRow(node_id='n0', vector=(.2, .8), mass=2),))
        validate_features(self.snap, batch, required_ids=('n0',))
        with self.assertRaises(ContractError): validate_features(replace(self.snap, revision=1), batch)
        with self.assertRaises(ContractError): validate_features(self.snap, batch, required_ids=('n1',))
        with self.assertRaises(ContractError): replace(batch, rows=(FeatureRow(node_id='n0', vector=(1,)),))

    def test_stream_state_and_initial_vs_current_budgets(self):
        budget = resolve_budget(self.snap, BudgetRequest(unit='nodes', ratio=.5))
        state = AlgorithmState(schema='lab.streaming', version=1, data={'counters': [1, 2]})
        request = PlanningRequest(run_id='r', snapshot=replace(self.snap, revision=1), budgets=(budget,), mode='stream', state=state)
        self.assertEqual(loads(dumps(request)), request)
        with self.assertRaises(ContractError): replace(request, budgets=(replace(budget, request=replace(budget.request, reference='current')),))


class BoundaryTests(unittest.TestCase):
    def test_all_nine_methods_five_benchmark_variants_three_framework_shapes(self):
        for method in BASELINES:
            for benchmark in BENCHMARKS:
                for framework in FRAMEWORKS:
                    with self.subTest(method=method, benchmark=benchmark, framework=framework):
                        dataset = sample(benchmark, framework)
                        self.assertEqual(loads(dumps(dataset)), dataset)
                        snap = dataset.memory.initial_snapshot
                        plan, result = plan_and_result(snap, method)
                        validate_result(snap, plan, result)
                        self.assertEqual(loads(dumps(plan)), plan)
                        self.assertEqual(loads(dumps(result)), result)

    def test_eval_answers_do_not_enter_planning_contract(self):
        dataset = sample()
        changed = replace(dataset.evaluation, cases=(replace(dataset.evaluation.cases[0], ground_truth={'answer': 'coffee'}),))
        self.assertNotEqual(changed, dataset.evaluation)
        request = PlanningRequest(run_id='r', snapshot=dataset.memory.initial_snapshot)
        self.assertNotIn('ground_truth', dumps(request))
        self.assertNotIn('evaluation', {f.name for f in fields(PlanningRequest)})

    def test_reader_questions_carry_options_but_no_ground_truth_or_evidence(self):
        dataset = sample('m3.robot')
        questions = dataset.evaluation.reader_input()
        self.assertEqual(questions.questions[0].options['choices'], ('tea', 'coffee'))
        self.assertNotIn('answer_index', dumps(questions))
        self.assertNotIn('evidence', dumps(questions))
        changed = replace(dataset.evaluation, cases=(replace(dataset.evaluation.cases[0], ground_truth={'answer_index': 1}),))
        self.assertEqual(questions, changed.reader_input())
        self.assertEqual(loads(dumps(questions)), questions)

    def test_evaluation_annotations_do_not_change_dataset_identity(self):
        dataset = sample()
        annotated = replace(dataset.memory.sample, extensions={'lab.annotation': 'reader note'})
        prediction = Prediction(question_id='q1', sample=annotated,
                                answer=(ContentPart(modality='text', text='tea'),))
        report = EvaluationReport(sample=dataset.memory.sample, protocol_id='fixture',
                                  predictions=(prediction,), metrics=())
        self.assertEqual(loads(dumps(report)), report)
        with self.assertRaises(ContractError): replace(report, sample=replace(report.sample, dataset_fingerprint='1'*64))

    def test_capability_gaps_fail_before_execution(self):
        planner = PluginSpec(plugin_id='streammeco.official', role='planner', requires=('graph.edges',), action_kinds=('keep', 'drop'), execution_modes=('once', 'stream'))
        operator = PluginSpec(plugin_id='identity_prune', role='operator', action_kinds=('keep', 'drop'), execution_modes=('once', 'stream'))
        with self.assertRaises(ContractError): validate_composition(planner, (operator,), mode='once', available=('text',))
        validate_composition(planner, (operator,), mode='once', available=('graph.edges',))
        with self.assertRaises(ContractError): validate_composition(planner, (replace(operator, action_kinds=('keep',)),), mode='once', available=('graph.edges',))
        with self.assertRaises(ContractError): validate_composition(planner, (operator,), mode='repeat', available=('graph.edges',))

    def test_backend_map_must_cover_records(self):
        snap = sample().memory.initial_snapshot
        artifact = ArtifactRef(artifact_id='view', path='view.json', sha256='0'*64, media_type='application/json', schema_id='fixture.view')
        with self.assertRaises(ContractError): MaterializedView(framework_id='mem0', snapshot=snap, artifact=artifact, node_id_map={})
        view = MaterializedView(framework_id='mem0', snapshot=snap, artifact=artifact, node_id_map={n.node_id: f'uuid-{i}' for i, n in enumerate(snap.records)})
        self.assertEqual(loads(dumps(view)), view)

    def test_rewrite_and_tensor_tokens_have_no_text_only_assumption(self):
        snap = sample().memory.initial_snapshot
        original = snap.records[0]
        action = Action(action_id='rewrite', kind='rewrite', member_ids=('n0',), output_ids=('encoded',), input_view='original')
        plan = ActionPlan(plan_id='contextfolder.single', input_fingerprint=snap.fingerprint, target_ids=('n0',), actions=(action,))
        node = replace(original, node_id='encoded', parts=(ContentPart(modality='text', text='Synthetic codec result'),), embeddings=())
        result = OperatorResult(plan_fingerprint=plan.fingerprint, outcomes=(ActionOutcome(action_id='rewrite', status='success', outputs=(node,)),))
        validate_result(snap, plan, result)
        token = replace(original, kind='token', parts=(ContentPart(modality='tensor', data={'shape': [128], 'dtype': 'float16'}),), embeddings=())
        self.assertEqual(loads(dumps(token)), token)


class ComponentTests(unittest.TestCase):
    def test_external_component_and_optional_diagnostics_leave_result_unchanged(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
        from custom_component import ThresholdGate
        class NoServices:
            def require(self, service_id): raise LookupError(service_id)
        class Collector:
            def __init__(self): self.records = []
            def enabled(self, schema): return True
            def emit(self, record): self.records.append(record)
        collector = Collector()
        request = PlanningRequest(run_id='r', snapshot=sample().memory.initial_snapshot)
        scores = ScoreBatch(candidate_fingerprint='0'*64, scores=(CandidateScore(candidate_id='c0', value=.8),))
        component = ThresholdGate(threshold=.7)
        off = component.decide(request, scores, AlgorithmContext(services=NoServices(), diagnostics=NullDiagnostics()))
        on = component.decide(request, scores, AlgorithmContext(services=NoServices(), diagnostics=collector))
        self.assertEqual(off, on)
        self.assertTrue(on.decisions[0].accepted)
        self.assertEqual(len(collector.records), 1)
        validate_gates(scores, on)
        self.assertEqual(loads(dumps(component.parameters)), component.parameters)

    def test_candidate_scores_gates_are_linked_by_fingerprints_and_ids(self):
        snap = sample().memory.initial_snapshot
        candidates = CandidateBatch(input_fingerprint=snap.fingerprint, candidates=(Candidate(candidate_id='c0', source_id='n0', target_id='n1'),))
        scores = ScoreBatch(candidate_fingerprint=fingerprint(candidates), scores=(CandidateScore(candidate_id='c0', value=.8, components={'cosine': .9, 'entity': .7}),))
        gates = GateBatch(score_fingerprint=fingerprint(scores), decisions=(GateDecision(candidate_id='c0', accepted=False, reason_codes=('anchor_gain_not_met',), thresholds={'minimum_gain': .1}),))
        selection = CandidateSelection(candidate_fingerprint=fingerprint(candidates), selected_ids=())
        validate_candidates(snap, candidates)
        validate_scores(candidates, scores)
        validate_gates(scores, gates)
        validate_selection(candidates, selection)
        for value in (candidates, scores, gates, selection): self.assertEqual(loads(dumps(value)), value)
        with self.assertRaises(ContractError): validate_scores(candidates, replace(scores, scores=()))
        with self.assertRaises(ContractError): validate_gates(scores, replace(gates, decisions=()))
        with self.assertRaises(ContractError): validate_candidates(replace(snap, revision=1), candidates)
        with self.assertRaises(ContractError): validate_selection(candidates, replace(selection, selected_ids=('unknown',)))

    def test_sparse_component_output_is_explicit(self):
        candidates = CandidateBatch(input_fingerprint='0'*64, candidates=(Candidate(candidate_id='c0', source_id='a', target_id='b'),))
        sparse = ScoreBatch(candidate_fingerprint=fingerprint(candidates), scores=(), complete=False)
        validate_scores(candidates, sparse)
        self.assertFalse(sparse.complete)

    def test_no_model_or_framework_dependency_on_import(self):
        script = "import sys;sys.path.insert(0,sys.argv[1]);import memfolder.core;assert not any(x.split('.')[0] in {'numpy','torch','pydantic','mem0','memos','mmagent'} for x in sys.modules)"
        subprocess.run([sys.executable, '-c', script, str(Path(__file__).resolve().parents[1] / 'src')], check=True, capture_output=True)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.dataset = sample()
        self.event = EventEnvelope(event_id='e1', run_id='r', sequence=0, name='plan.created', stage='plan',
            phase='completed', span_id='p', monotonic_ns=1, sample=self.dataset.memory.sample,
            scope=self.dataset.memory.initial_snapshot.records[0].scope, summary={'count': 4})

    def test_events_are_detached_roundtrippable_and_scalar_only(self):
        source = {'count': 4}
        event = replace(self.event, summary=source)
        source['count'] = 0
        self.assertEqual(event.summary['count'], 4)
        self.assertEqual(loads(dumps(event)), event)
        with self.assertRaises(ContractError): replace(event, summary={'snapshot': {'node': 'n0'}})

    def test_projection_has_no_native_payload_or_unrequested_text(self):
        snap = self.dataset.memory.initial_snapshot
        node = replace(snap.records[0], native={'sensitive_private_field': 'fixture-secret'})
        projected = project_snapshot(replace(snap, records=(node, *snap.records[1:])))
        serialized = json.dumps(to_data(projected))
        self.assertNotIn('fixture-secret', serialized)
        self.assertNotIn(node.text, serialized)
        self.assertIn(node.text, json.dumps(to_data(project_snapshot(snap, include_text=True))))
        with self.assertRaises(TypeError): projected['nodes'][0]['node_id'] = 'changed'

    def test_coverage_and_case_alignment_do_not_fake_completeness(self):
        capture = CapturePolicy(profile='cases', sample_ids=('sample_001',), text_policy='selected')
        coverage = TraceCoverage(capture=capture, complete_for_capture=True, events_written=1)
        with self.assertRaises(ContractError): replace(coverage, events_dropped=1)
        case = CaseView(run_id='r', sample=self.dataset.memory.sample, origins=self.dataset.memory.initial_snapshot.records[0].origins,
                        coverage=coverage, events=(self.event,), status='complete_for_capture')
        self.assertEqual(loads(dumps(case)), case)
        other = replace(case, run_id='other', events=())
        RunComparison(left=case, right=other, alignment='matched')
        annotated = replace(other, sample=replace(other.sample, extensions={'lab.note': 'annotation'}))
        RunComparison(left=case, right=annotated, alignment='matched')
        other = replace(other, sample=replace(other.sample, dataset_fingerprint='1'*64))
        with self.assertRaises(ContractError): RunComparison(left=case, right=other, alignment='matched')

    def test_manifest_separates_quality_and_trace_from_compression(self):
        with self.assertRaises(ContractError): RunManifest(run_id='r', config_fingerprint='0'*64, samples=(self.dataset.memory.sample,), bindings=(), seed=0,
            mode='once', compression_status='completed', evaluation_status='not_run', observation_status='complete')
        report = MetricResult(name='quality', version='v1', value=None, status='not_run')
        self.assertEqual(loads(dumps(report)), report)
        with self.assertRaises(ContractError): replace(report, value=0)

    def test_null_diagnostics_never_calls_an_observer(self):
        diag = NullDiagnostics()
        self.assertFalse(diag.enabled('lab.gate'))
        self.assertIsNone(diag.emit(DiagnosticRecord(schema='lab.gate', version=1, component_id='gate', data={'accepted': False})))


if __name__ == '__main__': unittest.main()
