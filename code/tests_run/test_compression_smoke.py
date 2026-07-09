"""Smoke tests for RecallFlow v0 modules.

Convention: one ``test_*`` function per public module function. Each test
uses only stdlib + numpy + the in-tree ``embed_backends.random_numpy_embed``.
Run via ``python -m code.tests.test_compression_smoke`` from repo root.
"""
from __future__ import annotations

import math
import sys
import unittest
from typing import List

import numpy as np

from code.benchmarks.embed_backends import random_numpy_embed
from code.compression import (
    MemoryCapsule,
    MemoryNode,
    ProbeQuery,
    assign_to_representatives,
    assert_no_leakage,
    build_capsules,
    build_probe_queries,
    compute_response_fingerprints,
    deduplicate_probes,
    fit_compress,
    l2_normalize,
    recallflow_compress,
    recallflow_prune_only,
    route_cluster_members,
    select_representatives,
    simple_capsule_summary,
    softmax,
)


def _make_nodes(n: int = 16, dim: int = 32, seed: int = 0) -> List[MemoryNode]:
    rng = np.random.default_rng(seed)
    entities = ["Mark", "Alice", "Bob"]
    events = ["preference_change", "plan_update", "meeting"]
    out: List[MemoryNode] = []
    for i in range(n):
        ent = entities[i % len(entities)]
        out.append(
            MemoryNode(
                node_id=f"n{i:03d}",
                text=f"turn {i}: {ent} did something at step {i}",
                timestamp=float(i),
                entities=[ent] if i % 2 == 0 else [ent, "team"],
                events=[events[i % len(events)]] if i % 3 == 0 else [],
                modality="text",
                source={"dataset": "fixture", "dialog_id": "d0", "turn_id": i},
            )
        )
    # Embeddings come from a fixed seed so fingerprints are deterministic.
    embs = rng.standard_normal((n, dim)).tolist()
    for node, emb in zip(out, embs):
        node.embedding = emb
    return out


class TestSchema(unittest.TestCase):
    def test_node_roundtrip(self):
        node = MemoryNode(
            node_id="x",
            text="hello",
            timestamp=1.0,
            entities=["Mark"],
            events=["plan_update"],
        )
        d = node.to_dict()
        node2 = MemoryNode.from_dict(d)
        self.assertEqual(node, node2)


class TestProbes(unittest.TestCase):
    def test_window_emits_entity_temporal_event(self):
        nodes = _make_nodes(n=10)
        probes = build_probe_queries(
            nodes, window_size=4, max_probes=64, probe_types=("entity", "temporal", "event")
        )
        self.assertGreater(len(probes), 0)
        types = {p.probe_type for p in probes}
        for required in {"entity", "temporal", "event"}:
            self.assertIn(required, types)

    def test_no_test_question_leakage(self):
        nodes = _make_nodes(n=8)
        # Construct probe generator from the fixture's metadata only.
        forbidden = [
            "Mark eats what for lunch?",
            "What did Alice say about the plan?",
        ]
        probes = build_probe_queries(
            nodes, window_size=4, max_probes=32, probe_types=("entity", "temporal", "event")
        )
        # Probes come from constant templates, so the forbidden strings
        # should never appear.
        probe_texts = {p.text for p in probes}
        for f in forbidden:
            self.assertNotIn(f, probe_texts)

    def test_assert_no_leakage_raises_on_match(self):
        p = ProbeQuery(probe_id="x", text="about Mark", probe_type="entity")
        with self.assertRaises(AssertionError):
            assert_no_leakage([p], forbidden_strings=["about Mark"])

    def test_dedup_keeps_unique_text(self):
        p1 = ProbeQuery(probe_id="a", text="dup", probe_type="entity")
        p2 = ProbeQuery(probe_id="b", text="dup", probe_type="temporal")
        p3 = ProbeQuery(probe_id="c", text="unique", probe_type="event")
        out = deduplicate_probes([p1, p2, p3])
        self.assertEqual(len(out), 2)
        self.assertEqual({p.text for p in out}, {"dup", "unique"})


class TestResponse(unittest.TestCase):
    def test_softmax_rows_sum_to_one(self):
        s = np.array([[1.0, 2.0, 3.0], [-1.0, 0.0, 1.0]])
        a = softmax(s, axis=1)
        sums = a.sum(axis=1)
        np.testing.assert_allclose(sums, np.ones_like(sums), atol=1e-6)

    def test_l2_normalize_zero_safe(self):
        z = np.zeros((1, 4))
        out = l2_normalize(z, axis=1)
        self.assertTrue(np.allclose(out, 0))

    def test_compute_fingerprints_shapes_and_mass(self):
        q = np.eye(3, dtype=np.float64)
        n = np.eye(3, dtype=np.float64) + 0.01
        A, F, m = compute_response_fingerprints(q, n, tau=0.1)
        self.assertEqual(A.shape, (3, 3))
        self.assertEqual(F.shape, (3, 3))
        np.testing.assert_allclose(A.sum(axis=1), np.ones(3), atol=1e-6)
        np.testing.assert_allclose(m, A.sum(axis=0), atol=1e-6)


class TestCoreset(unittest.TestCase):
    def test_select_within_budget_and_unique(self):
        F = np.random.default_rng(0).standard_normal((20, 8)).tolist()
        mass = np.random.default_rng(1).random(20).tolist()
        selected = select_representatives(F, mass, budget=5, seed=0)
        self.assertEqual(len(selected), 5)
        self.assertEqual(len(set(selected)), 5)
        for i in selected:
            self.assertGreaterEqual(i, 0)
            self.assertLess(i, 20)

    def test_select_budget_larger_than_n(self):
        F = np.random.default_rng(0).standard_normal((4, 6)).tolist()
        mass = [1, 2, 3, 4]
        selected = select_representatives(F, mass, budget=10)
        self.assertEqual(sorted(selected), [0, 1, 2, 3])

    def test_select_budget_zero(self):
        F = np.random.default_rng(0).standard_normal((4, 6)).tolist()
        mass = [1, 2, 3, 4]
        self.assertEqual(select_representatives(F, mass, budget=0), [])

    def test_first_pick_is_highest_mass(self):
        F = np.random.default_rng(0).standard_normal((6, 5)).tolist()
        mass = [0.1, 0.2, 0.9, 0.05, 0.4, 0.3]
        selected = select_representatives(F, mass, budget=2)
        # Node 2 has the largest mass => first selected.
        self.assertEqual(selected[0], 2)


class TestCapsule(unittest.TestCase):
    def test_route_distributes(self):
        nodes = _make_nodes(n=8)
        # Fake residuals / mass to force at least one of each bucket.
        residuals = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
        mass = np.array([0.1, 0.2, 0.05, 0.3, 0.4, 0.02, 0.5, 0.06])
        merge, exc, arc = route_cluster_members(
            list(range(8)), residuals, mass,
            low_mass_quantile=0.25, exception_quantile=0.75,
        )
        # All three buckets should be non-empty in this toy setup.
        self.assertGreater(len(merge), 0)
        self.assertGreater(len(exc), 0)
        self.assertGreater(len(arc), 0)
        # No index appears in two buckets.
        union = set(merge) | set(exc) | set(arc)
        self.assertEqual(len(union), 8)

    def test_simple_summary_no_llm(self):
        nodes = _make_nodes(n=5)
        s = simple_capsule_summary(nodes, merge_indices=[0, 1, 2])
        self.assertIn("turn 0", s)
        self.assertIn("turn 1", s)
        self.assertIn("turn 2", s)

    def test_build_capsules_includes_representative(self):
        nodes = _make_nodes(n=10)
        rng = np.random.default_rng(2)
        F = rng.standard_normal((10, 6))
        mass = rng.random(10)
        representatives = [0, 4, 7]
        reps_feats = F[representatives]
        sim = F @ reps_feats.T
        assignments = np.argmin(1 - sim, axis=1)
        residuals = np.min(1 - sim, axis=1)
        caps = build_capsules(
            nodes=nodes,
            representative_indices=representatives,
            assignments=assignments,
            residuals=residuals,
            mass=mass,
        )
        self.assertEqual(len(caps), 3)
        for cap in caps:
            self.assertIn(cap.representative_id, [n.node_id for n in nodes])
            self.assertIn(cap.representative_id, cap.member_node_ids)
            # Representative never appears in archive.
            self.assertNotIn(cap.representative_id, cap.archive_node_ids)


class TestRecallFlow(unittest.TestCase):
    def test_end_to_end_with_random_backend(self):
        nodes = _make_nodes(n=24, dim=32, seed=3)
        probes = build_probe_queries(
            nodes, window_size=8, max_probes=32,
            probe_types=("entity", "temporal", "event"),
        )
        cm = recallflow_compress(
            nodes=nodes,
            probe_queries=probes,
            embed_fn=random_numpy_embed(dim=32, seed=11),
            budget=8,
            tau=0.1,
        )
        # Budget respected.
        self.assertLessEqual(len(cm.capsules), len(nodes))
        # Retained ids should exist in the original nodes.
        node_ids = {n.node_id for n in nodes}
        for rid in cm.retained_node_ids:
            self.assertIn(rid, node_ids)
        # Diagnostics populated.
        for k in (
            "num_nodes_before",
            "num_probes",
            "num_capsules",
            "num_retained",
            "num_archived",
            "compression_latency_sec",
        ):
            self.assertIn(k, cm.diagnostics)

    def test_prune_only_does_not_build_capsules(self):
        nodes = _make_nodes(n=16, dim=16, seed=2)
        probes = build_probe_queries(nodes, window_size=4, max_probes=16)
        cm = recallflow_prune_only(
            nodes=nodes,
            probe_queries=probes,
            embed_fn=random_numpy_embed(dim=16, seed=4),
            budget=4,
        )
        self.assertEqual(cm.capsules, [])
        self.assertEqual(len(cm.retained_node_ids), 4)
        self.assertEqual(len(set(cm.retained_node_ids)), 4)

    def test_fit_compress_wrapper(self):
        nodes = _make_nodes(n=12, dim=12, seed=5)
        cm = fit_compress(
            nodes=nodes,
            embed_fn=random_numpy_embed(dim=12, seed=6),
            budget=5,
            tau=0.1,
            window_size=4,
            max_probes=16,
        )
        self.assertGreater(cm.diagnostics["num_probes"], 0)
        self.assertGreater(len(cm.capsules), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
