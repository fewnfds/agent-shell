from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from agent_shell.runtime.lifecycle_store import lifecycle_runs_namespace


RunStatus = Literal[
    "pending",
    "running",
    "error",
    "success",
    "timeout",
    "interrupted",
]
RunCheckStatus = RunStatus | Literal["not_found"]
GraphKind = Literal["agent", "workflow"]

ACTIVE_RUN_STATUSES = frozenset({"pending", "running"})
TERMINAL_RUN_STATUSES = frozenset(
    {"error", "success", "timeout", "interrupted"}
)


@dataclass(frozen=True, slots=True)
class RunCaller:
    """Shell scope captured when a Run facade is bound to one Server Run."""

    request_id: str
    lifecycle_id: str
    run_id: str


class GraphRunCallRelation(BaseModel):
    """Minimal Shell relation for one official Agent Server Run."""

    model_config = ConfigDict(extra="forbid")

    lifecycle_id: str
    graph_kind: GraphKind
    operation_id: str
    caller_run_id: str
    resource_id: str
    resource_name: str
    checkpoint_mode: Literal["enabled", "disabled"] | None = None
    assistant_id: str
    thread_id: str
    run_id: str


def official_status(run: Mapping[str, Any]) -> RunStatus:
    status = run.get("status")
    if status not in {
        "pending",
        "running",
        "error",
        "success",
        "timeout",
        "interrupted",
    }:
        raise RuntimeError("LangGraph Server returned an unsupported Run status")
    return status


def relation_key(caller_run_id: str, operation_id: str) -> str:
    return json.dumps(
        [caller_run_id, operation_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )


async def save_lifecycle_run_relation(
    client: Any,
    relation: GraphRunCallRelation,
) -> None:
    await client.store.put_item(
        lifecycle_runs_namespace(relation.lifecycle_id),
        relation.run_id,
        relation.model_dump(mode="json"),
        index=False,
    )


async def search_lifecycle_run_relations(
    client: Any,
    lifecycle_id: str,
    *,
    graph_kind: GraphKind | None = None,
) -> list[GraphRunCallRelation]:
    if not lifecycle_id:
        raise ValueError("lifecycle_id must not be empty")
    relations: list[GraphRunCallRelation] = []
    offset = 0
    while True:
        response = await client.store.search_items(
            lifecycle_runs_namespace(lifecycle_id),
            limit=100,
            offset=offset,
        )
        page = response.get("items", [])
        for item in page:
            value = item.get("value") if isinstance(item, Mapping) else None
            if not isinstance(value, Mapping):
                raise RuntimeError("the Lifecycle Run relation is invalid")
            relation = GraphRunCallRelation.model_validate(value)
            if graph_kind is None or relation.graph_kind == graph_kind:
                relations.append(relation)
        if len(page) < 100:
            break
        offset += len(page)
    return sorted(relations, key=lambda item: item.run_id)


def select_run_relations(
    relations: Sequence[GraphRunCallRelation],
    *,
    run_ids: Sequence[str] | None = None,
) -> list[GraphRunCallRelation]:
    selected_ids = set(run_ids) if run_ids is not None else None
    return [
        relation
        for relation in relations
        if selected_ids is None or relation.run_id in selected_ids
    ]


__all__ = [
    "ACTIVE_RUN_STATUSES",
    "GraphKind",
    "GraphRunCallRelation",
    "RunCaller",
    "RunCheckStatus",
    "RunStatus",
    "TERMINAL_RUN_STATUSES",
    "official_status",
    "relation_key",
    "save_lifecycle_run_relation",
    "search_lifecycle_run_relations",
    "select_run_relations",
]
