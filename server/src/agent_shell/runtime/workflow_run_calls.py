from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


WorkflowRunStatus = Literal[
    "pending",
    "running",
    "error",
    "success",
    "timeout",
    "interrupted",
]
WorkflowRunCheckStatus = WorkflowRunStatus | Literal["not_found"]

ACTIVE_WORKFLOW_RUN_STATUSES = frozenset({"pending", "running"})
TERMINAL_WORKFLOW_RUN_STATUSES = frozenset(
    {"error", "success", "timeout", "interrupted"}
)


def workflow_run_calls_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    if not lifecycle_id:
        raise ValueError("lifecycle_id must not be empty")
    return ("workflow-lifecycle", lifecycle_id, "run-calls")


class WorkflowRunCallRelation(BaseModel):
    """Shell-owned relationship between a caller and one official Server Run."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = 1
    lifecycle_id: str
    operation_id: str
    caller_run_id: str
    workflow_id: str
    workflow_name: str
    assistant_id: str
    thread_id: str
    run_id: str
    cancel_on_caller_termination: bool


class WorkflowRunHandle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    workflow_id: str
    assistant_id: str
    thread_id: str
    run_id: str
    status: WorkflowRunStatus


class WorkflowRunSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = ""
    caller_run_id: str = ""
    workflow_id: str = ""
    workflow_name: str = ""
    assistant_id: str = ""
    thread_id: str = ""
    run_id: str
    status: WorkflowRunCheckStatus
    output: dict[str, Any] | None = None


def official_status(run: Mapping[str, Any]) -> WorkflowRunStatus:
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


async def search_run_call_relations(
    client: Any,
    lifecycle_id: str,
) -> list[WorkflowRunCallRelation]:
    relations: list[WorkflowRunCallRelation] = []
    offset = 0
    while True:
        response = await client.store.search_items(
            workflow_run_calls_namespace(lifecycle_id),
            limit=100,
            offset=offset,
        )
        items = response.get("items", []) if isinstance(response, Mapping) else []
        relations.extend(
            WorkflowRunCallRelation.model_validate(item["value"])
            for item in items
        )
        if len(items) < 100:
            return relations
        offset += len(items)


def select_relations(
    relations: Sequence[WorkflowRunCallRelation],
    *,
    caller_run_id: str,
    run_ids: Sequence[str] | None = None,
) -> list[WorkflowRunCallRelation]:
    selected_ids = set(run_ids) if run_ids is not None else None
    return [
        relation
        for relation in relations
        if relation.caller_run_id == caller_run_id
        and (selected_ids is None or relation.run_id in selected_ids)
    ]


__all__ = [
    "ACTIVE_WORKFLOW_RUN_STATUSES",
    "TERMINAL_WORKFLOW_RUN_STATUSES",
    "WorkflowRunCallRelation",
    "WorkflowRunCheckStatus",
    "WorkflowRunHandle",
    "WorkflowRunSnapshot",
    "WorkflowRunStatus",
    "official_status",
    "relation_key",
    "search_run_call_relations",
    "select_relations",
    "workflow_run_calls_namespace",
]
