"""MemForest text variant: joint clustering, MST pair routing, per-round refresh."""

from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
import heapq
import math
from typing import Dict, List
from ..component_runtime import emit, resolve, spec
from .contracts import Group
from ..core import AlgorithmState, FrozenMap, PlanningResult, fingerprint
from ..core.values import require
from .plan_helpers import (
    Geometry,
    check_groups,
    component_nodes,
    feature,
    node_targets,
    numpy,
    plan_groups,
    subset_request,
)
from .record_selection import id_keys


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
    import numpy as np
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return -1.0
    return float(np.dot(a, b) / (na * nb))


def kmeans_labels(vectors: np.ndarray, k: int, seed: int = 42, max_iter: int = 30) -> np.ndarray:
    import numpy as np
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
    import numpy as np
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


@dataclass(frozen=True)
class AverageLinkageGroups:
    feature_name: str = 'semantic'
    id_order: str = 'canonical'
    spec = spec('memforest.average_linkage_proxy','partitioner')
    def partition(self,request,target,context):
        np=numpy();nodes=component_nodes(request);geo=Geometry.of(request,nodes,self.feature_name);keys=id_keys(nodes,self.id_order)
        groups=[[n.node_id] for n in nodes];sums=[v.copy() for v in geo.vectors];sizes=[1.]*len(nodes)
        while len(groups)>target:
            pairs=[(i,j,float(sums[i] @ sums[j])/(sizes[i]*sizes[j])) for i in range(len(groups)) for j in range(i+1,len(groups))]
            best=max(w for _,_,w in pairs)
            i,j,_=min((p for p in pairs if abs(p[2]-best)<=1e-12),key=lambda p:tuple(sorted((min(keys[k] for k in groups[p[0]]),min(keys[k] for k in groups[p[1]])))))
            groups[i]+=groups[j];sums[i]+=sums[j];sizes[i]+=sizes[j]
            for array in (groups,sums,sizes):array.pop(j)
        return tuple(Group(min(ids,key=keys.__getitem__),tuple(sorted(ids,key=keys.__getitem__))) for ids in groups)


def times(request,nodes,mode):
    if mode=='order':return {n.node_id:n.order for n in nodes}
    require(mode=='event_time','MemForest time_order must be event_time or order')
    rows={r.node_id:r.values for r in feature(request,'temporal',[n.node_id for n in nodes]).rows}
    require(all(type(rows[n.node_id].get('event_time')) in (int,float) for n in nodes),'MemForest requires parsed temporal features')
    require(len({rows[n.node_id].get('clock') for n in nodes})==1 and all(rows[n.node_id].get('clock') for n in nodes),'MemForest time clocks disagree')
    return {n.node_id:rows[n.node_id]['event_time'] for n in nodes}


@dataclass(frozen=True)
class JointClusters:
    cluster_ratio: float = .05
    semantic_time_alpha: float = .8
    time_window_size: int = 5
    feature_name: str = 'semantic'
    time_order: str = 'event_time'
    seed: int = 42
    spec = spec('memforest.joint_clusters','partitioner', diagnostics=('memfolder.planning.memforest_clusters',))
    def partition(self,request,target,context):

        require(0<self.cluster_ratio<=1 and 0<=self.semantic_time_alpha<=1 and self.time_window_size>=0,'Invalid joint clustering configuration')
        nodes=component_nodes(request);geo=Geometry.of(request,nodes,self.feature_name,dtype='float32');time=times(request,nodes,self.time_order)
        @dataclass(frozen=True)
        class Item:
            point_id: str
            vector: object
            created_at: float
        items=[Item(n.node_id,geo.vectors[i],time[n.node_id]) for i,n in enumerate(nodes)]
        clusters=build_joint_clusters(items,self.cluster_ratio,self.semantic_time_alpha,self.time_window_size,self.seed)
        groups=tuple(Group(rows[0].point_id,tuple(n.point_id for n in rows)) for _,rows in sorted(clusters.items()))
        emit(context,self.spec.plugin_id,'memfolder.planning.memforest_clusters',nodes=geo.node_ids,
             groups=[{'center':g.anchor_id,'members':g.member_ids} for g in groups])
        return groups


@dataclass(frozen=True)
class CapacityAllocator:
    spec = spec('budgets.capacity_allocator','budget_allocator')
    def allocate(self,groups,target,context):
        require(len(groups)<=target<=sum(len(g.member_ids) for g in groups),'Target below nonempty cluster count')
        amounts={g.anchor_id:1 for g in groups};remaining=target-len(groups)
        capacity=sum(len(g.member_ids)-1 for g in groups);remainders=[]
        if remaining:
            for g in groups:
                quota=Fraction(remaining*(len(g.member_ids)-1),capacity);extra=quota.numerator//quota.denominator
                amounts[g.anchor_id]+=extra;remainders.append((quota-extra,g.anchor_id))
            for _,i in sorted(remainders,key=lambda r:(-r[0],r[1]))[:target-sum(amounts.values())]:amounts[i]+=1
        return FrozenMap(amounts)


@dataclass(frozen=True)
class PerClusterCeilAllocator:
    keep_ratio: float = .7
    spec = spec('memforest.per_cluster_ceil','budget_allocator')
    def allocate(self,groups,target,context):
        require(0<self.keep_ratio<=1,'Invalid MemForest cluster keep ratio')
        result={g.anchor_id:max(1,math.ceil(len(g.member_ids)*self.keep_ratio)) for g in groups}
        require(sum(result.values())==target,
                'Per-cluster ceil differs from requested scope K; resolve explicit cluster budgets or select capacity allocation')
        return FrozenMap(result)


@dataclass(frozen=True)
class MstPairRouter:
    feature_name: str = 'semantic'
    time_order: str = 'event_time'
    spec = spec('memforest.mst_pair','pair_router', diagnostics=('memfolder.planning.mst_pair',))
    def pair(self,request,nodes,context):

        geo=Geometry.of(request,nodes,self.feature_name,dtype='float32')
        @dataclass(frozen=True)
        class Item:
            vector: object
        pair=best_merge_pair_via_mst([Item(v) for v in geo.vectors])
        require(pair is not None,'MST has no feasible merge pair')
        a,b=(nodes[i] for i in pair);time=times(request,(a,b),self.time_order)
        older,newer=(a,b) if time[a.node_id]<=time[b.node_id] else (b,a)
        emit(context,self.spec.plugin_id,'memfolder.planning.mst_pair',nodes=(older.node_id,newer.node_id),
             older=older.node_id,newer=newer.node_id,edge_rule='0.90*cosine - 0.10*normalized_degree_sum')
        return Group(newer.node_id,(older.node_id,newer.node_id))


@dataclass(frozen=True)
class MemForestPlanner:
    clusterer: object = JointClusters()
    allocator: object = CapacityAllocator()
    router: object = MstPairRouter()
    spec = spec('memforest.mst','planner',actions=('keep','merge'),modes=('repeat',), diagnostics=('memfolder.compression.completed', 'memfolder.planning.plan'))
    async def plan(self,request,context):
        previous={}
        if request.state is not None:
            require(request.state.schema=='memfolder.memforest.clusters' and request.state.version==1,'Wrong MemForest state schema/version')
            previous=request.state.data['scopes']
        state={};groups=[]
        for key,nodes,target in node_targets(request):
            if not nodes:continue
            require(len({n.scope for n in nodes})==1,'MemForest merge budget group must remain within one scope')
            locked=tuple(n for n in nodes if not n.retention.may_merge);active=tuple(n for n in nodes if n.retention.may_merge)
            groups.extend(Group(n.node_id,(n.node_id,)) for n in locked);k=target-len(locked)
            require(k>=1 if active else k==0,'MemForest target cannot preserve protected nodes')
            if not active:continue
            local=subset_request(request,active)
            if key not in previous:
                # Group budgets were produced by the upstream joint clusterer.
                # Re-clustering these groups would silently change the per-cluster allocation method.
                node_budget=next(b for b in request.budgets if b.request.unit=='nodes')
                initial=(Group(active[0].node_id,tuple(n.node_id for n in active)),) if node_budget.request.allocation=='group' else await resolve(self.clusterer.partition(local,k,context))
                from .plan_helpers import check_groups
                check_groups(active,initial)
                limits=await resolve(self.allocator.allocate(initial,k,context))
                require(set(limits)=={g.anchor_id for g in initial} and sum(limits.values())==k,'Cluster allocation must equal scope target')
                assignment={i:g.anchor_id for g in initial for i in g.member_ids}
            else:
                assignment=dict(previous[key]['assignment']);limits=previous[key]['limits']
                require(set(assignment)=={n.node_id for n in active} and sum(limits.values())==k,'Stale MemForest cluster state')
            clustered=defaultdict(list)
            for n in active:clustered[assignment[n.node_id]].append(n)
            next_assignment=dict(assignment)
            time=times(request,active,getattr(self.router,'time_order','event_time'))
            for cluster,rows in clustered.items():
                rows=tuple(sorted(rows,key=lambda n:time[n.node_id]))
                if len(rows)>limits[cluster]:
                    pair=await resolve(self.router.pair(local,rows,context));require(len(pair.member_ids)==2,'MST router must select one pair')
                    require(set(pair.member_ids)<={n.node_id for n in rows} and pair.anchor_id in pair.member_ids,'Invalid MST pair')
                    groups.append(pair)
                    for i in pair.member_ids:next_assignment.pop(i)
                    next_assignment[pair.anchor_id]=cluster
                    groups.extend(Group(n.node_id,(n.node_id,)) for n in rows if n.node_id not in pair.member_ids)
                else:groups.extend(Group(n.node_id,(n.node_id,)) for n in rows)
            state[key]={'assignment':next_assignment,'limits':dict(limits)}
        plan=plan_groups(request,tuple(groups),method=self.spec.plugin_id,input_view='current')
        from dataclasses import replace
        plan=replace(plan,actions=tuple(replace(a,parameters=FrozenMap({**a.parameters,'timestamp_policy':'latest'})) for a in plan.actions),
            extensions=FrozenMap({**plan.extensions,'memfolder.budget_allocator':self.allocator.spec.plugin_id}))
        return PlanningResult(plan=plan,next_state=AlgorithmState(schema='memfolder.memforest.clusters',version=1,data=FrozenMap({'scopes':state})))


async def resolve_memforest_budget(request,context,*,clusterer=None,keep_ratio=.7):
    """Original per-cluster ceil recipe, resolved before any text merge."""
    from ..core import BudgetGroup, BudgetRequest, resolve_budget
    clusterer=clusterer or JointClusters();by_scope=defaultdict(list)
    for n in request.snapshot.records:
        if n.eligible:by_scope[n.scope].append(n)
    groups=[]
    for scope,nodes in by_scope.items():
        require(all(n.retention.may_merge for n in nodes),'Per-cluster MemForest clustering requires mergeable nodes; use capacity adaptation for protected inputs')
        local=subset_request(request,tuple(nodes));clusters=await resolve(clusterer.partition(local,len(nodes),context))
        from .plan_helpers import check_groups
        check_groups(nodes,clusters)
        for g in clusters:groups.append(BudgetGroup(group_id=fingerprint((scope,g.anchor_id)),member_ids=g.member_ids))
    return resolve_budget(request.snapshot,BudgetRequest(unit='nodes',ratio=keep_ratio,allocation='group',rounding='ceil',minimum=1),groups=tuple(groups))
