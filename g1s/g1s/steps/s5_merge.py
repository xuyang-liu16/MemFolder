"""Step 5 — merge: one group, one prompt, one memory.

Every group produced by step 4 becomes a single memory entry.  Singletons pass
through untouched -- there is nothing to merge and an LLM rewrite would only
introduce drift.  Groups of two or more are sent to the model *whole*, in one
call, with their timestamps attached.

Sending the whole group at once matters.  The historic implementation folded
members in pairwise (merge 1+2, then that with 3, ...), which costs ``n-1``
calls per group and compounds the summariser's losses: by the fourth fold the
model is summarising a summary of a summary.  One N-way call costs one request
and lets the model see all the evidence before it writes anything.

Timestamps are included because LoCoMo questions are largely temporal, and a
memory that says "last June" is worthless unless the merge resolves it against
the session date.  That instruction is the bulk of the prompt.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Sequence

from ..llm import ChatClient
from ..plan import Group, Plan
from ..scope import Scope

MERGE_PROMPT = """
You are an intelligent memory summarization assistant. Please extract the core information from the following {n} memory entries and their timestamps, and generate a concise and coherent summary paragraph. If the memories contain relative time expressions (e.g., “last June,” “two months ago”), convert them into specific dates based on the corresponding timestamps (for example, if a memory mentions “last June” and the timestamp is February 2023, the actual time should be June 2022). The summary length should be kept within the combined length of the original memories as much as possible. Output only the final summarized result, without any explanations, analysis, reasoning steps, or additional content.
{lines}
"""


@dataclass(frozen=True)
class Member:
    node_id: str
    text: str
    time: str


def members_of(group: Group, scope: Scope) -> list[Member]:
    """The group's memories in chronological order, ties broken by node id."""
    members = []
    for node_id in group.member_node_ids:
        point = scope.by_id.get(node_id)
        if point is None:
            raise RuntimeError(f"node {node_id} is not in sample {scope.sample}")
        members.append(
            Member(node_id=node_id, text=point.text, time=point.event_time.isoformat())
        )
    members.sort(key=lambda member: (member.time, member.node_id))
    return members


def build_prompt(members: Sequence[Member]) -> str:
    lines = "\n".join(
        f"Memory {position + 1}: {member.text}, Timestamp {position + 1}: {member.time}"
        for position, member in enumerate(members)
    )
    return MERGE_PROMPT.format(n=len(members), lines=lines)


def merge_group(group: Group, scope: Scope, chat: ChatClient) -> Group:
    members = members_of(group, scope)
    group.compression_time_start = members[0].time
    group.compression_time_end = members[-1].time
    if len(members) == 1:
        group.final_text = members[0].text
        group.merge_api_calls_realized = 0
        return group
    group.final_text = chat.complete(build_prompt(members), sample=scope.sample)
    group.merge_api_calls_realized = 1
    return group


def merge_plan(plan: Plan, scope: Scope, chat: ChatClient, *, workers: int = 8) -> Plan:
    """Fill in every group's ``final_text``. Groups are independent, so run them in parallel."""
    if workers <= 1:
        for group in plan.groups:
            merge_group(group, scope, chat)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(merge_group, group, scope, chat) for group in plan.groups]
            for future in as_completed(futures):
                future.result()
    missing = [group.anchor_node_id for group in plan.groups if not group.final_text]
    if missing:
        raise RuntimeError(f"sample {scope.sample}: {len(missing)} groups have no merged text")
    plan.metadata = {
        **plan.metadata,
        "step": "merge",
        "merge_prompt": "oneshot_n_way(temperature=0)",
        "merge_model": chat.endpoint.model,
    }
    return plan
