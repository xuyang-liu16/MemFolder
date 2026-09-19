"""Step 4 — chaining: the method.

Step 3 assigned every node to its nearest anchor.  That is a reasonable
partition and a poor one: nearest-anchor is a *static* rule, so a conversation
that develops an episode over five sessions gets shredded across five groups
whose anchors happen to be closest in embedding space.  What we actually want to
compress together is an *episode* -- a run of memories that continue one another
in time.

So this step builds chains.  Reading the sample forward in time, each memory may
attach to one earlier memory, and the resulting links form trajectories that are
then hosted, whole, by an anchor.

Four ideas, in the order the code applies them:

1.  **Fused affinity.**  Two memories continue one another if they talk about
    the same things (entity overlap) or read alike (embedding cosine).  Neither
    signal is reliable alone, so they are combined:

        affinity = alpha * s_ent + (1 - alpha) * cos

    with ``alpha`` set per pair rather than tuned:

        alpha = (m * sigma_s^2) / (m * sigma_s^2 + sigma_e^2)

    ``m`` is the IDF mass the pair shares.  When a pair shares a lot of rare
    entity mass, the entity signal is trustworthy for *this* pair and alpha goes
    to 1; when it shares nothing, alpha goes to 0 and the pair is judged on
    embeddings alone.  The two variances rescale the signals to a common footing
    and are estimated from the sample itself, over every candidate pair -- there
    is no hyper-parameter to fit.

2.  **Anchor gating.**  A link is only worth making if it beats what step 3
    already offered.  ``gain = affinity - baseline[succ]``, where the baseline is
    the successor's cosine to its ``pi0`` anchor.  Non-positive gain means the
    nearest-anchor assignment was already at least as good, and no edge is
    proposed.

3.  **Matching.**  Each node may continue at most one predecessor and be
    continued by at most one successor -- otherwise "chains" would be arbitrary
    clusters.  That is exactly a bipartite matching, solved for the maximum
    total gain (Hungarian).  Chains fall out as the connected components.

4.  **Hosting.**  A chain is assigned, as a unit, to the anchor it is closest to
    in aggregate.  Nodes that never got matched keep their ``pi0`` group, so the
    partition stays complete and the anchor set and group count never change.

The three ``affinity`` / ``gating`` / ``matching`` options exist because each is
an ablation of one of the ideas above; the locked configuration is the default
of each.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np

from ..entities import Grounding
from ..plan import Plan, make_group
from ..scope import Scope

#: How far back a memory may reach for a predecessor, in nodes.
WINDOW = 50
#: How many predecessors a node keeps before the matching runs.
TOPK = 8
#: Variance floor, so a degenerate signal cannot divide by ~0.
EPSILON = 1e-6

Affinity = Literal["full", "no_entity", "no_semantic"]
Gating = Literal["anchor", "none"]
Matching = Literal["hungarian", "greedy"]


@dataclass(frozen=True)
class ChainingConfig:
    window: int = WINDOW
    topk: int = TOPK
    affinity: Affinity = "full"
    gating: Gating = "anchor"
    matching: Matching = "hungarian"

    @property
    def seed(self) -> str:
        """Identifies the variant inside plan metadata."""
        return (
            "ep_traj_temporal_forward_max_weight_matching"
            f"_affinity-{self.affinity}_gating-{self.gating}_matching-{self.matching}"
        )


@dataclass
class Candidate:
    predecessor: str
    successor: str
    shared_mass: float
    entity_similarity: float
    cosine: float


# ------------------------------------------------------------------ 1. affinity


def candidate_pairs(
    order: Sequence[str],
    grounding: Grounding,
    vectors: dict[str, np.ndarray],
    window: int,
) -> list[Candidate]:
    """Every (earlier, later) pair within ``window`` steps, scored on both signals."""
    candidates: list[Candidate] = []
    for successor_position, successor in enumerate(order):
        start = max(0, successor_position - window)
        for predecessor in order[start:successor_position]:
            shared = grounding.shared_mass(predecessor, successor)
            union = grounding.union_mass(predecessor, successor)
            candidates.append(
                Candidate(
                    predecessor=predecessor,
                    successor=successor,
                    shared_mass=shared,
                    entity_similarity=shared / union if union > 0.0 else 0.0,
                    cosine=float(np.dot(vectors[predecessor], vectors[successor])),
                )
            )
    return candidates


def signal_variances(candidates: Sequence[Candidate]) -> tuple[float, float]:
    """``(sigma_e^2, sigma_s^2)``, estimated over *all* candidate pairs.

    Deliberately computed before any filtering: the variances describe how
    informative each signal is in this sample, which is a property of the
    sample and not of the subset that survives gating.
    """
    if not candidates:
        return EPSILON, EPSILON
    entity = float(np.var([candidate.entity_similarity for candidate in candidates]))
    semantic = float(np.var([candidate.cosine for candidate in candidates]))
    return max(entity, EPSILON), max(semantic, EPSILON)


def fuse(candidate: Candidate, sigma_e2: float, sigma_s2: float, mode: Affinity) -> float:
    if mode == "no_entity":
        return candidate.cosine
    if mode == "no_semantic":
        return candidate.entity_similarity if candidate.shared_mass > 0.0 else 0.0
    mass = candidate.shared_mass
    alpha = (mass * sigma_s2) / (mass * sigma_s2 + sigma_e2)
    return alpha * candidate.entity_similarity + (1.0 - alpha) * candidate.cosine


# -------------------------------------------------------------------- 2. gating


def proposed_edges(
    candidates: Sequence[Candidate],
    *,
    anchors: set[str],
    baseline: dict[str, float],
    config: ChainingConfig,
) -> dict[tuple[str, str], float]:
    """Edges that beat the baseline, capped at ``topk`` per successor."""
    sigma_e2, sigma_s2 = signal_variances(candidates)
    by_successor: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for candidate in candidates:
        # An anchor is never a successor: anchors are fixed points of the plan.
        if candidate.successor in anchors:
            continue
        affinity = fuse(candidate, sigma_e2, sigma_s2, config.affinity)
        gain = (
            affinity
            if config.gating == "none"
            else affinity - baseline[candidate.successor]
        )
        if gain > 0.0:
            by_successor[candidate.successor].append((candidate.predecessor, gain))

    edges: dict[tuple[str, str], float] = {}
    for successor, rows in by_successor.items():
        rows.sort(key=lambda row: (-row[1], row[0]))
        for predecessor, gain in rows[: config.topk]:
            edges[(predecessor, successor)] = gain
    return edges


# ------------------------------------------------------------------ 3. matching


def match_edges(
    edges: dict[tuple[str, str], float],
    order: Sequence[str],
    anchors: set[str],
    mode: Matching,
) -> list[tuple[str, str, float]]:
    """Choose at most one predecessor per successor, and vice versa."""
    if mode == "greedy":
        matched: list[tuple[str, str, float]] = []
        used_predecessors: set[str] = set()
        used_successors: set[str] = set()
        for (predecessor, successor), gain in sorted(
            edges.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
        ):
            if predecessor in used_predecessors or successor in used_successors:
                continue
            used_predecessors.add(predecessor)
            used_successors.add(successor)
            matched.append((predecessor, successor, float(gain)))
        return matched

    from scipy.optimize import linear_sum_assignment

    successors = [node_id for node_id in order if node_id not in anchors]
    weights = np.zeros((len(successors), len(order)), dtype=np.float64)
    successor_row = {node_id: row for row, node_id in enumerate(successors)}
    predecessor_column = {node_id: column for column, node_id in enumerate(order)}
    for (predecessor, successor), gain in edges.items():
        weights[successor_row[successor], predecessor_column[predecessor]] = gain
    rows, columns = linear_sum_assignment(weights, maximize=True)
    matched = []
    for row, column in zip(rows, columns):
        successor = successors[row]
        predecessor = order[column]
        gain = float(weights[row, column])
        # The assignment fills the rectangle with zeros; only real edges count.
        if gain > 0.0 and (predecessor, successor) in edges:
            matched.append((predecessor, successor, gain))
    return matched


def chains_from(
    matched: Sequence[tuple[str, str, float]], rank: dict[str, int]
) -> list[list[str]]:
    """Connected components of the matching, each in temporal order."""
    parent: dict[str, str] = {}

    def find(node_id: str) -> str:
        parent.setdefault(node_id, node_id)
        while parent[node_id] != node_id:
            parent[node_id] = parent[parent[node_id]]
            node_id = parent[node_id]
        return node_id

    for predecessor, successor, _ in matched:
        root_predecessor, root_successor = find(predecessor), find(successor)
        if root_predecessor != root_successor:
            parent[root_successor] = root_predecessor

    members = {node_id for edge in matched for node_id in edge[:2]}
    components: dict[str, list[str]] = defaultdict(list)
    for node_id in members:
        components[find(node_id)].append(node_id)
    chains = [sorted(chain, key=lambda node_id: rank[node_id]) for chain in components.values()]
    chains.sort(key=lambda chain: (rank[chain[0]], chain[0]))
    return chains


# ------------------------------------------------------------------- 4. hosting


def host_of(
    chain: Sequence[str], anchors: Sequence[str], anchor_set: set[str], vectors: dict[str, np.ndarray]
) -> str:
    """The anchor a whole chain belongs to: the one it is closest to in total."""
    if chain[0] in anchor_set:
        return chain[0]
    best_anchor, best_score = anchors[0], None
    for anchor in anchors:
        score = sum(float(np.dot(vectors[node_id], vectors[anchor])) for node_id in chain)
        if best_score is None or score > best_score:
            best_anchor, best_score = anchor, score
    return best_anchor


# ------------------------------------------------------------------- the step


def regroup(
    base: Plan,
    scope: Scope,
    grounding: Grounding,
    config: ChainingConfig = ChainingConfig(),
) -> Plan:
    """Rewrite ``base``'s membership by chaining. Anchors and group count are kept."""
    anchors = base.anchors()
    anchor_set = set(anchors)
    pi0 = base.partition()
    if set(pi0) != set(scope.node_ids):
        raise RuntimeError(
            f"sample {scope.sample}: plan universe ({len(pi0)}) != store universe "
            f"({len(scope.node_ids)})"
        )

    vectors = {node_id: scope.embeddings[index] for node_id, index in scope.index_of.items()}
    order = sorted(
        scope.node_ids,
        key=lambda node_id: (
            grounding.event_time(node_id, scope.by_id[node_id].payload),
            node_id,
        ),
    )
    rank = {node_id: position for position, node_id in enumerate(order)}
    baseline = {
        node_id: float(np.dot(vectors[node_id], vectors[pi0[node_id]]))
        for node_id in scope.node_ids
    }

    candidates = candidate_pairs(order, grounding, vectors, config.window)
    edges = proposed_edges(
        candidates, anchors=anchor_set, baseline=baseline, config=config
    )
    matched = match_edges(edges, order, anchor_set, config.matching)
    chains = chains_from(matched, rank)

    members: dict[str, set[str]] = {anchor: set() for anchor in anchors}
    hosted_chains: dict[str, list[list[str]]] = {anchor: [] for anchor in anchors}
    chained = {node_id for edge in matched for node_id in edge[:2]}
    chain_heads = {chain[0] for chain in chains if chain[0] in anchor_set}

    for anchor in anchors:
        if anchor not in chain_heads:
            members[anchor].add(anchor)
    for node_id in scope.node_ids:
        if node_id not in chained and node_id not in anchor_set:
            members[pi0[node_id]].add(node_id)
    for chain in chains:
        anchor = host_of(chain, anchors, anchor_set, vectors)
        members[anchor].update(chain)
        hosted_chains[anchor].append(chain)

    groups = []
    for anchor in anchors:
        group = make_group(scope, anchor, members[anchor])
        group.chains = hosted_chains[anchor]
        groups.append(group)

    plan = Plan(
        method=base.method,
        sample_id=base.sample_id,
        scope_id=base.scope_id,
        source_store=base.source_store,
        keep_ratio=base.keep_ratio,
        generator_model=base.generator_model,
        num_nodes_before=base.num_nodes_before,
        groups=groups,
        config_id=base.config_id,
        metadata={
            **base.metadata,
            "step": "chaining",
            "partition_seed": config.seed,
            "window": config.window,
            "topk": config.topk,
            "epsilon": EPSILON,
            "chaining_stats": {
                "candidate_pairs": len(candidates),
                "edges_after_topk": len(edges),
                "matched_edges": len(matched),
                "matched_weight": sum(gain for _, _, gain in matched),
                "chains": len(chains),
                "nodes_in_chains": len(chained),
                "chain_node_fraction": len(chained) / max(len(scope.node_ids), 1),
                "entity_coverage": grounding.coverage(scope.node_ids),
            },
        },
    )
    plan.check(len(scope.node_ids), base.keep_ratio)
    return plan.check_same_universe(base)
