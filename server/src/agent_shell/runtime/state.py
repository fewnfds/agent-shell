from __future__ import annotations

from functools import cache
from typing import Annotated, Any
from typing_extensions import TypedDict
from typing_extensions import NotRequired

from deepagents import DeepAgentState
from deepagents.middleware.filesystem import FilesystemState
from langchain.agents.middleware import AgentMiddleware
from pydantic import JsonValue, TypeAdapter


def merge_shared_vars(
    current: dict[str, JsonValue] | None,
    update: dict[str, JsonValue] | None,
) -> dict[str, JsonValue]:
    """Merge independent public variable patches across graph branches."""

    return {**(current or {}), **(update or {})}


class WorkflowTaskContext(TypedDict):
    command_node_id: str
    command_invocation_id: str
    task_id: str
    dispatch_key: str
    payload: dict[str, JsonValue]


class WorkflowTaskReference(TypedDict):
    command_node_id: str
    command_invocation_id: str
    task_id: str
    dispatch_key: str


class AgentInvocationRecord(TypedDict):
    invocation_id: str
    workflow_id: str
    workflow_node_id: str
    agent_id: str
    invoked_at: float | None
    result_ref: str
    workflow_task: NotRequired[WorkflowTaskReference]


class AgentInvocationArtifact(TypedDict):
    invocation_id: str
    workflow_id: str
    workflow_node_id: str
    agent_id: str
    invoked_at: float | None
    messages: list[Any]
    workflow_task: NotRequired[WorkflowTaskContext]


def _agent_invocation_slot(record: AgentInvocationRecord) -> tuple[str, ...]:
    workflow_task = record.get("workflow_task")
    if workflow_task is not None:
        return (
            "task",
            workflow_task["command_node_id"],
            workflow_task["task_id"],
        )
    workflow_node_id = record.get("workflow_node_id")
    if workflow_node_id:
        return ("node", workflow_node_id)
    return ("invocation", record["invocation_id"])


def merge_agent_invocations(
    current: dict[str, AgentInvocationRecord] | None,
    update: dict[str, AgentInvocationRecord] | None,
) -> dict[str, AgentInvocationRecord]:
    """Keep the latest reference for each logical Agent or Command task slot."""

    by_slot: dict[tuple[str, ...], AgentInvocationRecord] = {}
    order: list[tuple[str, ...]] = []
    for record in [*(current or {}).values(), *(update or {}).values()]:
        slot = _agent_invocation_slot(record)
        if slot not in by_slot:
            order.append(slot)
        by_slot[slot] = record
    return {
        by_slot[slot]["invocation_id"]: by_slot[slot]
        for slot in order
    }


class WorkflowState(TypedDict):
    """Workflow-owned channels; Agent conversations are provenance records."""

    shared_vars: NotRequired[Annotated[dict[str, JsonValue], merge_shared_vars]]
    agent_invocations: NotRequired[
        Annotated[
            dict[str, AgentInvocationRecord],
            merge_agent_invocations,
        ]
    ]
    files: FilesystemState.__annotations__["files"]


class WorkflowNodeInputState(WorkflowState):
    """Workflow node input plus an optional private Send payload."""

    workflow_task: NotRequired[WorkflowTaskContext]


@cache
def _workflow_state_update_adapter() -> TypeAdapter[Any]:
    return TypeAdapter(WorkflowState)


def validate_workflow_state_update(update: dict[str, Any]) -> dict[str, Any]:
    return _workflow_state_update_adapter().validate_python(update)


class AgentShellState(DeepAgentState, FilesystemState):
    """Private Agent state plus Shell-owned variables mapped by its wrapper."""

    shared_vars: NotRequired[Annotated[dict[str, JsonValue], merge_shared_vars]]
    workflow_task: NotRequired[WorkflowTaskContext]
    workflow_state_snapshot: NotRequired[dict[str, Any]]


class AgentShellStateMiddleware(AgentMiddleware[AgentShellState]):
    """Expose Shell-owned shared state keys to an official synchronous Subagent."""

    state_schema = AgentShellState


__all__ = [
    "AgentInvocationRecord",
    "AgentInvocationArtifact",
    "AgentShellState",
    "AgentShellStateMiddleware",
    "WorkflowState",
    "WorkflowNodeInputState",
    "WorkflowTaskContext",
    "WorkflowTaskReference",
    "merge_agent_invocations",
    "merge_shared_vars",
    "validate_workflow_state_update",
]
