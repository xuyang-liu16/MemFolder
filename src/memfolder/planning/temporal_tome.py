"""Meeting-defined memory ToMe: temporal halves with live pairwise contraction.

One pair per scope is planned per step. The operator publishes the new text and
embedding before the next source is matched; matching never freezes an entire
half into an N-way summary group.
"""
from dataclasses import dataclass, replace
from ..core import AlgorithmState, FrozenMap, PlanningResult
from ..core.values import require
from .common import Group, Geometry, emit, node_targets, numpy, plan_groups, spec


def temporal_key(node):
    clocks = {r.start.clock for r in node.time_ranges}
    require(len(clocks) <= 1, 'Temporal ToMe cannot compare multiple clocks')
    # An explicitly ordered dataset without event times may use its ordinal clock.
    value = max((r.start.value for r in node.time_ranges), default=node.order)
    return value, node.order, node.node_id


@dataclass(frozen=True)
class TemporalTomePlanner:
    feature_name: str = 'semantic'
    spec = spec('tome.temporal_half.dynamic_pair.v1', 'planner',
        actions=('keep', 'merge'), modes=('repeat',),
        diagnostics=('memfolder.planning.tome_temporal_pair', 'memfolder.planning.plan',
                     'memfolder.compression.completed'))

    async def plan(self, request, context):
        previous = {}
        if request.state is not None:
            require(request.state.schema == 'memfolder.tome.temporal_half'
                    and request.state.version == 1, 'Wrong temporal ToMe state')
            previous = request.state.data['groups']
        groups, states, selected = [], {}, {}
        np = numpy()
        for key, nodes, target in node_targets(request):
            require(len({n.scope for n in nodes}) <= 1, 'ToMe cannot merge across scopes')
            locked = [n for n in nodes if not n.retention.may_merge]
            active = sorted((n for n in nodes if n.retention.may_merge), key=temporal_key)
            clocks = {r.start.clock for n in active for r in n.time_ranges}
            require(len(clocks) <= 1 and (not clocks or all(n.time_ranges for n in active)),
                    'Temporal ToMe needs comparable event times or all-ordinal ordering')
            keep = target - len(locked)
            require(keep >= (1 if active else 0), 'Protected nodes make ToMe budget unreachable')
            groups.extend(Group(n.node_id, (n.node_id,)) for n in locked)
            ids = {n.node_id for n in active}
            prior = previous.get(key)
            if prior is not None:
                require(set(prior['sources']) | set(prior['destinations']) == ids
                        and len(prior['sources']) + len(prior['destinations']) == len(ids),
                        'Stale temporal ToMe state')
            if len(active) <= keep:
                groups.extend(Group(n.node_id, (n.node_id,)) for n in active)
                continue
            if prior is None or not prior['sources']:
                split = len(active) // 2
                sources = [n.node_id for n in active[:split]]
                destinations = [n.node_id for n in active[split:]]
                pass_index = 0 if prior is None else prior['pass_index'] + 1
            else:
                sources, destinations = list(prior['sources']), list(prior['destinations'])
                pass_index = prior['pass_index']
            by_id = {n.node_id: n for n in active}
            source = by_id[sources[0]]
            targets = [by_id[i] for i in destinations]
            geometry = Geometry.of(request, [source, *targets], self.feature_name, dtype='float32')
            require(bool((np.linalg.norm(geometry.vectors, axis=1) > 0).all()),
                    'Temporal ToMe cannot match zero embeddings')
            scores = geometry.vectors[1:] @ geometry.vectors[0]
            # Destinations remain in chronological order: ties choose the first one.
            best = int(np.argmax(scores))
            destination = targets[best]
            require(temporal_key(source) <= temporal_key(destination),
                    'Temporal ToMe destination must be at least as recent as source')
            for n in active:
                if n.node_id == source.node_id:
                    continue
                members = (source.node_id, destination.node_id) if n.node_id == destination.node_id else (n.node_id,)
                groups.append(Group(n.node_id, members))
            states[key] = {'sources': sources[1:], 'destinations': destinations,
                           'pass_index': pass_index}
            selected[destination.node_id] = {'timestamp_policy': 'latest',
                'output_order': destination.order, 'source_id': source.node_id,
                'destination_id': destination.node_id, 'half_pass': pass_index,
                'selected_similarity': float(scores[best])}
            emit(context, self.spec.plugin_id, 'memfolder.planning.tome_temporal_pair',
                nodes=(source.node_id, destination.node_id), pass_index=pass_index,
                source_id=source.node_id, destination_id=destination.node_id,
                remaining_sources=len(sources)-1, destination_count=len(destinations),
                similarity=float(scores[best]), input_view='current', timestamp_policy='latest',
                source_content_fingerprint=source.content_fingerprint,
                destination_content_fingerprint=destination.content_fingerprint)
        plan = plan_groups(request, tuple(groups), method=self.spec.plugin_id, input_view='current')
        plan = replace(plan, actions=tuple(replace(a,
            parameters=FrozenMap({**a.parameters, **selected[a.output_ids[0]]}))
            if a.kind == 'merge' else a for a in plan.actions))
        return PlanningResult(plan=plan, next_state=AlgorithmState(
            schema='memfolder.tome.temporal_half', version=1,
            data=FrozenMap({'groups': states})))
