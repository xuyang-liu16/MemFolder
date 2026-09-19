"""Smoke tests for RecallFlow-URB P0."""
from __future__ import annotations

import unittest

import numpy as np

from code.benchmarks.embed_backends import random_numpy_embed
from code.compression.recallflow import recallflow_urb_prune_only
from code.compression.response import compute_response_fingerprints
from code.compression.schema import MemoryNode
from code.compression.urb import basis_hash, compute_family_centroids, default_urb


def make_nodes(n: int = 12, dim: int = 1024):
    embed = random_numpy_embed(dim=dim, seed=91)
    nodes = []
    for i in range(n):
        text = f"memory {i}: user mentioned plan and preference {i % 3}"
        nodes.append(
            MemoryNode(
                node_id=f"n{i:03d}",
                text=text,
                timestamp=float(i),
                embedding=embed(text),
                source={"dataset": "fixture"},
            )
        )
    return nodes


class TestURBSmoke(unittest.TestCase):
    def test_bank_count_and_hash_stable(self):
        basis = default_urb()
        self.assertEqual(basis.num_families, 10)
        self.assertEqual(basis.num_paraphrases, 40)
        self.assertEqual(basis_hash(basis), basis_hash(default_urb()))

    def test_centroid_shape_and_norm(self):
        basis = default_urb()
        centroids = compute_family_centroids(
            basis,
            random_numpy_embed(dim=1024, seed=7),
            embedding_dim=1024,
        )
        self.assertEqual(centroids.shape, (10, 1024))
        norms = np.linalg.norm(centroids, axis=1)
        np.testing.assert_allclose(norms, np.ones(10), atol=1e-6)

    def test_response_shape(self):
        nodes = make_nodes()
        basis = default_urb()
        centroids = compute_family_centroids(
            basis,
            random_numpy_embed(dim=1024, seed=7),
            embedding_dim=1024,
        )
        A, F, mass = compute_response_fingerprints(
            centroids,
            [n.embedding for n in nodes],
            tau=0.1,
        )
        self.assertEqual(A.shape, (10, len(nodes)))
        self.assertEqual(F.shape, (len(nodes), 10))
        self.assertEqual(mass.shape, (len(nodes),))
        np.testing.assert_allclose(A.sum(axis=1), np.ones(10), atol=1e-6)

    def test_prune_only_budget_and_determinism(self):
        nodes = make_nodes(n=20)
        basis = default_urb()
        centroids = compute_family_centroids(
            basis,
            random_numpy_embed(dim=1024, seed=7),
            embedding_dim=1024,
        )
        a = recallflow_urb_prune_only(nodes, centroids, budget=7, coreset_seed=3)
        b = recallflow_urb_prune_only(nodes, centroids, budget=7, coreset_seed=3)
        self.assertEqual(len(a.retained_node_ids), 7)
        self.assertEqual(a.retained_node_ids, b.retained_node_ids)


if __name__ == "__main__":
    unittest.main()
