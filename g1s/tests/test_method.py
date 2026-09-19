"""Tests for the algorithmic core.

Every test here runs without a network, a store or an API key.  That is the
point: steps 3 and 4 -- anchor selection and chaining -- are the method, and
they are deterministic functions of (embeddings, entity sets, timestamps).
What is pinned below is exactly what a rerun has to reproduce.

    python -m pytest g1s/tests -q
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from g1s import store
from g1s.entities import Grounding, build_grounding, entity_set, speakers_of
from g1s.plan import Group, Plan, target_count
from g1s.steps import s3_anchors as anchors
from g1s.steps import s4_chaining as chaining

# --------------------------------------------------------------------- helpers


def ring(n: int, dimensions: int = 8, seed: int = 0) -> np.ndarray:
    generator = np.random.default_rng(seed)
    matrix = generator.normal(size=(n, dimensions))
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def distance_of(vectors: np.ndarray) -> np.ndarray:
    return anchors.cosine_distance(np.clip(vectors @ vectors.T, -1.0, 1.0))


def ids(n: int) -> tuple[str, ...]:
    return tuple(f"n{index:02d}" for index in range(n))


def plan_of(node_ids, groups, *, keep_ratio=0.5, metadata=None) -> Plan:
    return Plan(
        method="test",
        sample_id=0,
        scope_id="scope",
        source_store="/dev/null",
        keep_ratio=keep_ratio,
        generator_model="",
        num_nodes_before=len(node_ids),
        groups=[
            Group(
                anchor_node_id=anchor,
                member_indices=[node_ids.index(member) for member in members],
                member_node_ids=list(members),
                source_timestamps=["" for _ in members],
            )
            for anchor, members in groups
        ],
        metadata=metadata or {},
    )


# ------------------------------------------------------- 3. anchors: tie-breaks


def test_target_count_rounds_and_clamps():
    assert target_count(10, 0.5) == 5
    assert target_count(7, 0.3) == 2
    # never zero, however small the ratio
    assert target_count(1, 0.01) == 1
    assert target_count(10, 1.0) == 10
    with pytest.raises(ValueError):
        target_count(10, 1.5)


def test_stable_argmax_breaks_exact_ties_by_node_id():
    node_ids = ids(4)
    scores = np.array([1.0, 1.0, 0.5, 1.0])
    # candidate order must not matter: the smallest node id among the tied wins
    assert anchors.stable_argmax(scores, np.array([3, 1]), node_ids) == 1
    assert anchors.stable_argmax(scores, np.array([1, 3]), node_ids) == 1
    assert anchors.stable_argmax(scores, np.array([3, 1, 0]), node_ids) == 0


def test_stable_argmax_treats_float_noise_as_a_tie():
    node_ids = ids(3)
    scores = np.array([1.0, 1.0 + 1e-14, 0.0])
    # index 1 is numerically larger but within atol, so the id decides
    assert anchors.stable_argmax(scores, np.array([0, 1, 2]), node_ids) == 0


def test_delta_falls_back_to_max_distance_for_the_densest_node():
    density = np.array([3.0, 1.0, 2.0])
    distance = np.array([[0.0, 1.0, 2.0], [1.0, 0.0, 3.0], [2.0, 3.0, 0.0]])
    values = anchors.delta(density, distance, np.array([0, 1, 2]))
    # node 0 is the densest: nothing is denser, so it takes its largest distance
    assert values[0] == pytest.approx(2.0)
    # node 1's nearest denser neighbour is node 0 at distance 1
    assert values[1] == pytest.approx(1.0)
    assert values[2] == pytest.approx(2.0)


def test_density_peaks_is_deterministic_and_the_right_size():
    node_ids = ids(24)
    distance = distance_of(ring(24, seed=7))
    first = anchors.density_peaks(node_ids=node_ids, distance=distance, target=8)
    second = anchors.density_peaks(node_ids=node_ids, distance=distance, target=8)
    assert first == second
    assert len(set(first)) == 8


def test_density_peaks_spreads_out_over_clusters():
    """Three tight clusters, three anchors: one per cluster."""
    base = np.eye(3)
    rows = []
    for cluster in range(3):
        for offset in range(5):
            row = base[cluster] * 10.0 + np.full(3, 0.01 * offset)
            rows.append(row / np.linalg.norm(row))
    vectors = np.asarray(rows)
    node_ids = ids(len(rows))
    picked = anchors.density_peaks(
        node_ids=node_ids, distance=distance_of(vectors), target=3
    )
    assert sorted(index // 5 for index in picked) == [0, 1, 2]


def test_baseline_partition_covers_every_node_exactly_once():
    node_ids = ids(20)
    distance = distance_of(ring(20, seed=3))
    picked = anchors.density_peaks(node_ids=node_ids, distance=distance, target=6)
    groups = anchors.baseline_partition(node_ids=node_ids, distance=distance, anchors=picked)
    assert sorted(groups) == sorted(picked)
    members = [index for group in groups.values() for index in group]
    assert sorted(members) == list(range(20))
    for anchor, group in groups.items():
        assert group[0] == anchor  # the anchor leads its own group


# ------------------------------------------------- 4. chaining: the fused score


def candidate(shared: float, entity: float, cosine: float) -> chaining.Candidate:
    return chaining.Candidate(
        predecessor="a", successor="b", shared_mass=shared, entity_similarity=entity, cosine=cosine
    )


def test_fusion_weights_by_evidence_not_by_a_tuned_constant():
    """alpha = m*sigma_s^2 / (m*sigma_s^2 + sigma_e^2): more shared mass, more entity."""
    weak = candidate(shared=0.0, entity=0.0, cosine=0.5)
    strong = candidate(shared=10.0, entity=1.0, cosine=0.5)
    sigma_e2 = sigma_s2 = 1.0
    # with no shared entity mass the score is pure cosine
    assert chaining.fuse(weak, sigma_e2, sigma_s2, "full") == pytest.approx(0.5)
    # with a lot of it, the entity signal dominates
    assert chaining.fuse(strong, sigma_e2, sigma_s2, "full") > 0.9


def test_fusion_ablations_isolate_one_signal_each():
    item = candidate(shared=4.0, entity=0.8, cosine=0.2)
    assert chaining.fuse(item, 1.0, 1.0, "no_entity") == pytest.approx(0.2)
    assert chaining.fuse(item, 1.0, 1.0, "no_semantic") == pytest.approx(0.8)
    middle = chaining.fuse(item, 1.0, 1.0, "full")
    assert 0.2 < middle < 0.8


def test_fused_score_stays_between_its_two_inputs():
    generator = np.random.default_rng(11)
    for _ in range(200):
        shared = float(generator.uniform(0.0, 5.0))
        entity = float(generator.uniform(0.0, 1.0))
        cosine = float(generator.uniform(-1.0, 1.0))
        value = chaining.fuse(candidate(shared, entity, cosine), 0.3, 0.7, "full")
        assert min(entity, cosine) - 1e-9 <= value <= max(entity, cosine) + 1e-9


def test_variance_floor_prevents_a_degenerate_divide():
    identical = [candidate(1.0, 0.5, 0.5) for _ in range(5)]
    sigma_e2, sigma_s2 = chaining.signal_variances(identical)
    assert sigma_e2 >= chaining.EPSILON
    assert sigma_s2 >= chaining.EPSILON
    assert math.isfinite(chaining.fuse(identical[0], sigma_e2, sigma_s2, "full"))


# ------------------------------------------------- 4. chaining: edges and chains


def test_edges_only_form_backwards_and_within_the_window():
    order = list(ids(10))
    grounding = Grounding(
        sample=0,
        sets={node_id: frozenset({"x"}) for node_id in order},
        weight={"x": 1.0},
        timestamps={},
    )
    vectors = {node_id: np.ones(4) / 2.0 for node_id in order}
    pairs = chaining.candidate_pairs(order, grounding, vectors, window=3)
    positions = {node_id: index for index, node_id in enumerate(order)}
    for pair in pairs:
        gap = positions[pair.successor] - positions[pair.predecessor]
        assert 1 <= gap <= 3


def test_top_k_keeps_the_best_gains_and_anchor_gating_drops_the_rest():
    edges_in = {
        ("p1", "s"): 0.9,
        ("p2", "s"): 0.8,
        ("p3", "s"): 0.1,
    }
    # A successor whose baseline already beats every candidate keeps no edge.
    candidates = [
        chaining.Candidate("p1", "s", 1.0, 0.9, 0.9),
        chaining.Candidate("p2", "s", 1.0, 0.8, 0.8),
    ]
    kept = chaining.proposed_edges(
        candidates,
        anchors={"a"},
        baseline={"s": 0.99},
        config=chaining.ChainingConfig(topk=2),
    )
    assert kept == {}
    loose = chaining.proposed_edges(
        candidates,
        anchors={"a"},
        baseline={"s": 0.0},
        config=chaining.ChainingConfig(topk=1),
    )
    assert list(loose) == [("p1", "s")]  # the higher gain survives the cut
    assert set(edges_in) - set(loose)


def test_matching_gives_each_node_at_most_one_predecessor_and_one_successor():
    order = list(ids(6))
    edges = {
        ("n00", "n02"): 0.9,
        ("n00", "n03"): 0.8,   # n00 cannot precede both
        ("n01", "n03"): 0.7,
        ("n02", "n04"): 0.6,
    }
    matched = chaining.match_edges(edges, order, anchors={"n00"}, mode="hungarian")
    predecessors = [pair[0] for pair in matched]
    successors = [pair[1] for pair in matched]
    assert len(predecessors) == len(set(predecessors))
    assert len(successors) == len(set(successors))


def test_matching_maximises_total_weight_where_greedy_would_not():
    order = list(ids(4))
    # greedy takes (n00,n02)=0.9 and is then stuck; the optimum is 0.8+0.85
    edges = {
        ("n00", "n02"): 0.9,
        ("n00", "n03"): 0.8,
        ("n01", "n02"): 0.85,
    }
    optimal = chaining.match_edges(edges, order, anchors=set(), mode="hungarian")
    greedy = chaining.match_edges(edges, order, anchors=set(), mode="greedy")
    assert sum(weight for *_, weight in optimal) >= sum(weight for *_, weight in greedy)
    assert sum(weight for *_, weight in optimal) == pytest.approx(1.65)


def test_chains_are_paths_in_temporal_order():
    rank = {node_id: index for index, node_id in enumerate(ids(6))}
    matched = [("n00", "n01", 1.0), ("n01", "n02", 1.0), ("n04", "n05", 1.0)]
    chains = chaining.chains_from(matched, rank)
    assert ["n00", "n01", "n02"] in chains
    assert ["n04", "n05"] in chains
    for chain in chains:
        assert [rank[node] for node in chain] == sorted(rank[node] for node in chain)


def test_a_chain_is_hosted_whole_by_its_closest_anchor():
    vectors = {
        "a1": np.array([1.0, 0.0]),
        "a2": np.array([0.0, 1.0]),
        "c1": np.array([0.0, 1.0]),
        "c2": np.array([0.1, 0.99]),
    }
    host = chaining.host_of(["c1", "c2"], ["a1", "a2"], {"a1", "a2"}, vectors)
    assert host == "a2"


# ------------------------------------------------------- plan-level invariants


def test_plan_check_rejects_an_incomplete_partition():
    node_ids = ids(4)
    plan = plan_of(node_ids, [("n00", ["n00", "n01"]), ("n02", ["n02"])])
    with pytest.raises(AssertionError):
        plan.check(4, 0.5)  # n03 is unassigned


def test_plan_check_rejects_a_node_in_two_groups():
    node_ids = ids(4)
    plan = plan_of(node_ids, [("n00", ["n00", "n01"]), ("n02", ["n02", "n01", "n03"])])
    with pytest.raises(AssertionError):
        plan.check(4, 0.5)


def test_plan_check_requires_the_anchor_to_lead_its_group():
    node_ids = ids(4)
    plan = plan_of(node_ids, [("n00", ["n01", "n00"]), ("n02", ["n02", "n03"])])
    with pytest.raises(AssertionError):
        plan.check(4, 0.5)


def test_chaining_preserves_the_universe_and_the_anchors():
    """The whole contract of step 4: same nodes, same anchors, different membership."""
    node_ids = ids(12)
    vectors = ring(12, seed=5)
    scope = _FakeScope(node_ids, vectors)
    base = anchors.build_plan(scope, keep_ratio=0.5)
    grounding = build_grounding(
        {
            "sample_id": 0,
            "nodes": [
                {
                    "id": index,
                    "node_id": node_id,
                    "source": "speaker_0",
                    "entities": [{"key": f"e{index // 2}"}],
                    "relations": [],
                }
                for index, node_id in enumerate(node_ids)
            ],
        },
        0,
        node_ids,
    )
    chained = chaining.regroup(base, scope, grounding)

    assert chained.anchors() == base.anchors()
    assert sorted(chained.partition()) == sorted(base.partition())
    assert len(chained.groups) == len(base.groups)
    chained.check(len(node_ids), 0.5)
    chained.check_same_universe(base)


def test_chaining_is_reproducible():
    node_ids = ids(14)
    scope = _FakeScope(node_ids, ring(14, seed=9))
    grounding = Grounding(
        sample=0,
        sets={node_id: frozenset({f"e{index % 3}"}) for index, node_id in enumerate(node_ids)},
        weight={f"e{index}": 1.0 for index in range(3)},
        timestamps={},
    )
    base = anchors.build_plan(scope, keep_ratio=0.5)
    first = chaining.regroup(base.clear_merge_products(), scope, grounding)
    second = chaining.regroup(base.clear_merge_products(), scope, grounding)
    assert first.partition() == second.partition()


# ------------------------------------------------------------ entity extraction


def test_entity_set_drops_the_speakers_themselves():
    record = {"nodes": [{"source": "melanie_3"}, {"source": "caroline_3"}]}
    assert speakers_of(record) == {"melanie", "caroline"}
    node = {
        "source": "melanie_3",
        "entities": [
            {"key": "melanie", "canonical": "melanie"},
            {"key": "pottery class", "canonical": "pottery class"},
        ],
        "relations": [{"subject": "melanie", "object": "kiln"}],
    }
    assert entity_set(node, {"melanie"}) == frozenset({"pottery class", "kiln"})


def test_idf_makes_a_ubiquitous_entity_worthless():
    node_ids = ids(4)
    record = {
        "sample_id": 0,
        "nodes": [
            {
                "id": index,
                "node_id": node_id,
                "source": "a_0",
                "entities": [{"key": "everywhere"}, {"key": f"rare{index}"}],
                "relations": [],
            }
            for index, node_id in enumerate(node_ids)
        ],
    }
    grounding = build_grounding(record, 0, node_ids)
    assert grounding.weight["everywhere"] == pytest.approx(0.0)
    assert grounding.weight["rare0"] > 0.0
    # two nodes share only the ubiquitous entity, so they share no evidence
    assert grounding.shared_mass("n00", "n01") == pytest.approx(0.0)


# ------------------------------------------------------------------ test double


class _FakeScope:
    """A Scope with embeddings supplied directly, so tests need no store."""

    def __init__(self, node_ids, vectors):
        self.sample = 0
        self.source_store = Path("/dev/null")
        self.node_ids = tuple(node_ids)
        self.embeddings = vectors
        self.index_of = {node_id: index for index, node_id in enumerate(self.node_ids)}
        self.timestamps = tuple(
            f"2023-05-{index + 1:02d} 10:00:00" for index in range(len(self.node_ids))
        )
        self.by_id = {
            node_id: store.Point(
                node_id=node_id,
                payload={"data": node_id, "timestamp": self.timestamps[index]},
                vector=vectors[index],
                vector_name=None,
            )
            for index, node_id in enumerate(self.node_ids)
        }
        self.scope_id = "fake"

    def __len__(self):
        return len(self.node_ids)

    def cosine(self):
        return np.clip(self.embeddings @ self.embeddings.T, -1.0, 1.0)

    def provenance(self):
        return {"scope": "fake"}
