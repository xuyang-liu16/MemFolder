"""MemForest clustering and tree-based merge-selection primitives."""
from __future__ import annotations
import math
import heapq
from collections import defaultdict
from typing import List, Dict
import numpy as np

class DisjointSet:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> bool:
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return False
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        return True

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return -1.0
    return float(np.dot(a, b) / (na * nb))

def kmeans_labels(vectors: np.ndarray, k: int, seed: int = 42, max_iter: int = 30) -> np.ndarray:
    n, d = vectors.shape
    if k <= 1 or n <= 1:
        return np.zeros(n, dtype=np.int32)

    rng = np.random.default_rng(seed)
    centroids = np.empty((k, d), dtype=np.float32)

    first = int(rng.integers(0, n))
    centroids[0] = vectors[first]

    closest_dist2 = np.sum((vectors - centroids[0]) ** 2, axis=1)
    for c in range(1, k):
        total = float(np.sum(closest_dist2))
        if total <= 0.0:
            idx = int(rng.integers(0, n))
        else:
            probs = closest_dist2 / total
            idx = int(rng.choice(n, p=probs))
        centroids[c] = vectors[idx]
        dist2 = np.sum((vectors - centroids[c]) ** 2, axis=1)
        closest_dist2 = np.minimum(closest_dist2, dist2)

    labels = np.zeros(n, dtype=np.int32)
    for _ in range(max_iter):
        dist_mat = np.sum((vectors[:, None, :] - centroids[None, :, :]) ** 2, axis=2)
        new_labels = np.argmin(dist_mat, axis=1).astype(np.int32)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels

        for c in range(k):
            mask = labels == c
            if np.any(mask):
                centroids[c] = vectors[mask].mean(axis=0)
            else:
                farthest = int(np.argmax(np.min(dist_mat, axis=1)))
                centroids[c] = vectors[farthest]

    return labels

def best_merge_pair_via_mst(
    nodes: List[MemoryNode],
    interaction_router=None,
) -> tuple[int, int] | None:
    n = len(nodes)
    if n < 2:
        return None
    edges: List[tuple[float, int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            sim = cosine_similarity(nodes[i].vector, nodes[j].vector)
            if interaction_router is not None:
                affinity = interaction_router.group_affinity(
                    _router_source_ids(nodes[i]),
                    _router_source_ids(nodes[j]),
                )
                if affinity <= 0.0:
                    continue
                sim = affinity if _router_combination() == "replace" else sim * affinity
            edges.append((sim, i, j))
    edges.sort(key=lambda x: x[0], reverse=True)
    dsu = DisjointSet(n)
    mst: List[tuple[float, int, int]] = []
    for sim, i, j in edges:
        if dsu.union(i, j):
            mst.append((sim, i, j))
            if len(mst) == n - 1:
                break
    if not mst:
        return None

    degree = [0] * n
    for _, u, v in mst:
        degree[u] += 1
        degree[v] += 1

    degree_sums = [degree[u] + degree[v] for _, u, v in mst]
    max_degree_sum = max(degree_sums) if degree_sums else 1
    if max_degree_sum <= 0:
        max_degree_sum = 1

    def edge_score(item: tuple[float, int, int]) -> float:
        sim, u, v = item
        degree_norm = (degree[u] + degree[v]) / max_degree_sum
        return 0.90 * sim - 0.10 * degree_norm

    _, i, j = max(mst, key=edge_score)
    return i, j

def build_joint_clusters(
    sample_nodes: List[MemoryNode],
    cluster_ratio: float,
    semantic_time_alpha: float,
    time_window_size: int,
    seed: int,
    interaction_router=None,
) -> Dict[int, List[MemoryNode]]:
    n = len(sample_nodes)
    if n == 0:
        return {}

    vectors = np.stack([node.vector for node in sample_nodes], axis=0)
    k = max(1, min(n, int(math.floor(cluster_ratio * n))))
    labels = kmeans_labels(vectors, k=k, seed=seed)

    semantic_clusters: Dict[int, List[int]] = defaultdict(list)
    for idx, label in enumerate(labels.tolist()):
        semantic_clusters[label].append(idx)

    cluster_ids = sorted(semantic_clusters.keys())
    center_index_by_cluster: Dict[int, int] = {}
    for cid in cluster_ids:
        indices = semantic_clusters[cid]
        cluster_vectors = vectors[indices]
        centroid = cluster_vectors.mean(axis=0)
        dist2 = np.sum((cluster_vectors - centroid) ** 2, axis=1)
        center_local = int(np.argmin(dist2))
        center_index_by_cluster[cid] = indices[center_local]

    center_indices = set(center_index_by_cluster.values())

    if interaction_router is not None:
        node_index = {str(node.point_id): index for index, node in enumerate(sample_nodes)}
        ordered_indices = sorted(range(n), key=lambda i: (sample_nodes[i].created_at, i))
        time_pos = {idx: pos for pos, idx in enumerate(ordered_indices)}
        assigned: Dict[int, List[int]] = {
            cid: [center_index_by_cluster[cid]] for cid in cluster_ids
        }
        owner: Dict[int, int] = {
            center_index_by_cluster[cid]: cid for cid in cluster_ids
        }
        center_for_cluster = dict(center_index_by_cluster)
        next_cluster_id = max(cluster_ids, default=-1) + 1
        supplemental_centers: List[int] = []

        def joint_score(index: int, center_index: int) -> float:
            semantic = cosine_similarity(vectors[index], vectors[center_index])
            delta = abs(time_pos[index] - time_pos[center_index])
            temporal = 1.0 if delta <= time_window_size else 0.0
            return semantic_time_alpha * semantic + (1.0 - semantic_time_alpha) * temporal

        components = interaction_router.connected_components()
        for component_node_ids in components:
            component = sorted(node_index[str(node_id)] for node_id in component_node_ids)
            component_set = set(component)
            seeds = sorted(
                (
                    (cid, center_index)
                    for cid, center_index in center_for_cluster.items()
                    if center_index in component_set
                ),
                key=lambda item: (str(sample_nodes[item[1]].point_id), item[0]),
            )
            if not seeds:
                component_vectors = vectors[component]
                centroid = component_vectors.mean(axis=0)
                dist2 = np.sum((component_vectors - centroid) ** 2, axis=1)
                minimum = float(np.min(dist2))
                tied = [
                    component[pos]
                    for pos, value in enumerate(dist2)
                    if abs(float(value) - minimum) <= 1e-12
                ]
                center_index = min(tied, key=lambda row: str(sample_nodes[row].point_id))
                cid = next_cluster_id
                next_cluster_id += 1
                center_for_cluster[cid] = center_index
                assigned[cid] = [center_index]
                owner[center_index] = cid
                supplemental_centers.append(center_index)
                seeds = [(cid, center_index)]

            frontier: list[tuple[float, int, str, str, int, int]] = []

            def push_neighbors(parent: int, cid: int, depth: int) -> None:
                center_index = center_for_cluster[cid]
                for neighbor_id in interaction_router.adjacent_node_ids(
                    str(sample_nodes[parent].point_id)
                ):
                    neighbor = node_index[str(neighbor_id)]
                    if neighbor not in component_set or neighbor in owner:
                        continue
                    heapq.heappush(
                        frontier,
                        (
                            -joint_score(neighbor, center_index),
                            depth,
                            str(sample_nodes[center_index].point_id),
                            str(sample_nodes[neighbor].point_id),
                            cid,
                            neighbor,
                        ),
                    )

            for cid, center_index in seeds:
                push_neighbors(center_index, cid, 1)
            while frontier:
                _, depth, _, _, cid, index = heapq.heappop(frontier)
                if index in owner:
                    continue
                owner[index] = cid
                assigned[cid].append(index)
                push_neighbors(index, cid, depth + 1)

            missing = component_set - set(owner)
            if missing:
                raise RuntimeError(
                    "Router-connected reassignment failed to cover component nodes: "
                    f"{sorted(str(sample_nodes[index].point_id) for index in missing)}"
                )

        if sorted(owner) != list(range(n)):
            raise RuntimeError("Router-connected clustering does not partition the sample")

        result: Dict[int, List[MemoryNode]] = {}
        for cid in sorted(assigned):
            center_index = center_for_cluster[cid]
            others = sorted(
                (index for index in assigned[cid] if index != center_index),
                key=lambda index: (sample_nodes[index].created_at, str(sample_nodes[index].point_id)),
            )
            result[cid] = [sample_nodes[index] for index in [center_index, *others]]

        _append_router_audit({
            "stage": "router_connected_clustering",
            "num_nodes": n,
            "original_kmeans_clusters": len(cluster_ids),
            "router_components": len(components),
            "supplemental_router_centers": [
                str(sample_nodes[index].point_id) for index in supplemental_centers
            ],
            "realized_connected_clusters": len(result),
            "cluster_sizes": {str(cid): len(nodes) for cid, nodes in result.items()},
            "partition_complete": True,
            "preprocessing_api_calls": 0,
        })
        return result

    assigned: Dict[int, List[int]] = {cid: [center_index_by_cluster[cid]] for cid in cluster_ids}

    ordered_indices = sorted(range(n), key=lambda i: (sample_nodes[i].created_at, i))
    time_pos = {idx: pos for pos, idx in enumerate(ordered_indices)}
    center_items = sorted(center_index_by_cluster.items())

    for idx in ordered_indices:
        if idx in center_indices:
            continue
        original_cluster = int(labels[idx])
        best_score = None
        best_clusters: List[int] = []
        for cid, center_idx in center_items:
            semantic_flag = cosine_similarity(vectors[idx], vectors[center_idx])
            delta = abs(time_pos[idx] - time_pos[center_idx])
            time_flag = 1.0 if delta <= time_window_size else 0.0
            score = semantic_time_alpha * semantic_flag + (1.0 - semantic_time_alpha) * time_flag
            if best_score is None or score > best_score + 1e-12:
                best_score = score
                best_clusters = [cid]
            elif abs(score - best_score) <= 1e-12:
                best_clusters.append(cid)

        if len(best_clusters) == 1:
            target_cluster = best_clusters[0]
        else:
            target_cluster = original_cluster if original_cluster in best_clusters else best_clusters[0]
        assigned[target_cluster].append(idx)

    result: Dict[int, List[MemoryNode]] = {}
    for cid in cluster_ids:
        indices = assigned.get(cid, [])
        if not indices:
            continue
        result[cid] = [sample_nodes[i] for i in indices]
    return result
