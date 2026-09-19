"""Smoke tests for baselines and the entry script."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from code.baselines.base import REGISTRY, make_compressor
from code.evaluation.adapters.locomo_adapter import load_locomo_stream
from code.evaluation.adapters.memeye_adapter import load_memeye_stream
from code.evaluation.analysis.summarize_run import render_markdown, summarize
from code.benchmarks.embed_backends import random_numpy_embed
from code.compression import build_probe_queries


def _tiny_locomo():
    nodes = load_locomo_stream()
    return nodes[:8]


def _tiny_memeye():
    nodes = load_memeye_stream()
    return nodes


class TestAdapters(unittest.TestCase):
    def test_locomo_text_nodes(self):
        nodes = load_locomo_stream()
        self.assertGreater(len(nodes), 0)
        for n in nodes[:5]:
            self.assertEqual(n.modality, "text")
            self.assertTrue(n.node_id.startswith("locomo_"))

    def test_memeye_multimodal(self):
        nodes = load_memeye_stream()
        self.assertGreater(len(nodes), 0)
        for n in nodes:
            self.assertEqual(n.modality, "multimodal")
            self.assertIsNotNone(n.raw_pointer)


class TestBaselines(unittest.TestCase):
    def setUp(self):
        self.nodes = _tiny_locomo()
        self.probes = build_probe_queries(self.nodes, window_size=4, max_probes=16)
        self.embed = random_numpy_embed(dim=32, seed=0)
        self.budget = 3

    def test_registry_has_all_required(self):
        for required in {
            "no_compression", "random", "recency",
            "embedding_kcenter", "similarity_pruning", "similarity_merging",
            "recallflow_prune_only", "recallflow_full",
        }:
            self.assertIn(required, REGISTRY)

    def test_each_baseline_returns_compressed_memory(self):
        for name in sorted(REGISTRY):
            cm = make_compressor(name).fit(
                self.nodes, self.probes,
                budget=self.budget, embed_fn=self.embed, tau=0.1, seed=0,
            )
            # Common invariants:
            self.assertLessEqual(
                len(cm.retained_node_ids), len(self.nodes)
            )
            self.assertEqual(
                len(set(cm.retained_node_ids)), len(cm.retained_node_ids),
                msg=f"{name} produced duplicate retained ids",
            )
            node_set = {n.node_id for n in self.nodes}
            for rid in cm.retained_node_ids:
                self.assertIn(rid, node_set, msg=f"{name} kept unknown id {rid}")

    def test_recency_keeps_newest(self):
        cm = make_compressor("recency").fit(
            self.nodes, self.probes,
            budget=self.budget, embed_fn=self.embed, tau=0.1, seed=0,
        )
        kept_ids = set(cm.retained_node_ids)
        all_timestamps = sorted(n.timestamp for n in self.nodes)
        # The top-3 newest timestamps should map to retained ids.
        by_id = {n.node_id: n.timestamp for n in self.nodes}
        kept_timestamps = sorted(by_id[i] for i in kept_ids)
        self.assertEqual(kept_timestamps[-self.budget:], all_timestamps[-self.budget:])

    def test_no_compression_keeps_everything(self):
        cm = make_compressor("no_compression").fit(
            self.nodes, self.probes,
            budget=self.budget, embed_fn=self.embed, tau=0.1, seed=0,
        )
        self.assertEqual(set(cm.retained_node_ids), {n.node_id for n in self.nodes})

    def test_recallflow_full_builds_capsules(self):
        cm = make_compressor("recallflow_full").fit(
            self.nodes, self.probes,
            budget=self.budget, embed_fn=self.embed, tau=0.1, seed=0,
        )
        self.assertGreater(len(cm.capsules), 0)

    def test_recallflow_prune_only_no_capsules(self):
        cm = make_compressor("recallflow_prune_only").fit(
            self.nodes, self.probes,
            budget=self.budget, embed_fn=self.embed, tau=0.1, seed=0,
        )
        self.assertEqual(cm.capsules, [])


class TestSummarize(unittest.TestCase):
    def test_markdown_render(self):
        fake = [
            {"method": "m", "budget_ratio": 0.5,
             "num_nodes_before": 12, "num_capsules_after": 0,
             "num_retained": 6, "num_archived": 6, "compression_latency_sec": 0.01}
        ]
        out = render_markdown(summarize(fake))
        self.assertIn("| method |", out)
        self.assertIn("| m |", out)


class TestEntryScript(unittest.TestCase):
    def test_main_appends_jsonl(self):
        from code.evaluation.scripts.run_recallflow_locomo import main
        tmp = Path("/tmp/locomo_v0_smoke.jsonl")
        if tmp.exists():
            tmp.unlink()
        rc = main([
            "--input", "code/evaluation/adapters/fixtures/locomo_fixture.jsonl",
            "--method", "recallflow_full",
            "--budget-ratio", "0.5",
            "--output", str(tmp),
        ])
        self.assertEqual(rc, 0)
        with tmp.open() as f:
            line = f.readline().strip()
        row = json.loads(line)
        self.assertEqual(row["method"], "recallflow_full")
        self.assertEqual(row["budget_ratio"], 0.5)
        self.assertIn("diagnostics", row)


if __name__ == "__main__":
    unittest.main(verbosity=2)
