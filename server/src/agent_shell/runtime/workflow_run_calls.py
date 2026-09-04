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


class WorkflowRunCallRelation(BaseModel):
    """Product metadata projected from one official Thread and Run."""

    model_config = ConfigDict(extra="forbid")

    lifecycle_id: str
    operation_id: str
    caller_run_id: str
    workflow_id: str
    workflow_name: str
    assistant_id: str
    thread_id: str
    run_id: str


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


async def search_lifecycle_runs(
    client: Any,
    lifecycle_id: str,
) -> list[WorkflowRunCallRelation]:
    if not lifecycle_id:
        raise ValueError("lifecycle_id must not be empty")
    relations: list[WorkflowRunCallRelation] = []
    offset = 0
    while True:
        threads = await client.threads.search(
            metadata={"lifecycle_id": lifecycle_id},
            limit=100,
            offset=offset,
        )
        for thread in threads:
            metadata = thread.get("metadata")
            thread_metadata = metadata if isinstance(metadata, Mapping) else {}
            run_offset = 0
            while True:
                runs = await client.runs.list(
                    str(thread["thread_id"]),
                    limit=100,
                    offset=run_offset,
                )
                for run in runs:
                    run_metadata_value = run.get("metadata")
                    run_metadata = (
                        run_metadata_value
                        if isinstance(run_metadata_value, Mapping)
                        else {}
                    )
                    relations.append(
                        WorkflowRunCallRelation(
                            lifecycle_id=lifecycle_id,
                            operation_id=str(
                                run_metadata.get(
                                    "operation_id",
                                    thread_metadata.get("operation_id", ""),
                                )
                                or ""
                            ),
                            caller_run_id=str(
                                run_metadata.get(
                                    "caller_run_id",
                                    thread_metadata.get("caller_run_id", ""),
                                )
                                or ""
                            ),
                            workflow_id=str(
                                run_metadata.get(
                                    "workflow_id",
                                    thread_metadata.get("workflow_id", ""),
                                )
                                or ""
                            ),
                            workflow_name=str(run_metadata.get("workflow_name", "") or ""),
                            assistant_id=str(run["assistant_id"]),
                            thread_id=str(thread["thread_id"]),
                            run_id=str(run["run_id"]),
                        )
                    )
                if len(runs) < 100:
                    break
                run_offset += len(runs)
        if len(threads) < 100:
            return relations
        offset += len(threads)


def select_relations(
    relations: Sequence[WorkflowRunCallRelation],
    *,
    run_ids: Sequence[str] | None = None,
) -> list[WorkflowRunCallRelation]:
    selected_ids = set(run_ids) if run_ids is not None else None
    return [
        relation
        for relation in relations
        if selected_ids is None or relation.run_id in selected_ids
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
    "search_lifecycle_runs",
    "select_relations",
]
