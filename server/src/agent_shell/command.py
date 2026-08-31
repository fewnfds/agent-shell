from __future__ import annotations

from collections.abc import Awaitable, Collection, Mapping, Sequence
from copy import deepcopy
from typing import Annotated, Any, Callable

from langgraph.runtime import Runtime
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
)

from agent_shell.configuration.identity import ConfigurationName
from agent_shell.mcp.contracts import McpReference
from agent_shell.python_packages.contracts import PythonPackageReference
from agent_shell.runtime.context import WorkflowRuntimeContext


BranchKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True),
    Field(min_length=1, max_length=64),
]
DispatchKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True),
    Field(min_length=1, max_length=64),
]
_TaskId = Annotated[
    str,
    StringConstraints(strip_whitespace=True),
    Field(min_length=1, max_length=128),
]
CommandCallable = Callable[
    [dict[str, Any], Runtime[WorkflowRuntimeContext]],
    Awaitable[Any],
]


class CommandBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: ConfigurationName
    python_package: PythonPackageReference
    mcp_refs: list[McpReference] = Field(default_factory=list)

    @field_validator("mcp_refs")
    @classmethod
    def unique_mcp_requirements(
        cls,
        values: list[McpReference],
    ) -> list[McpReference]:
        requirement_ids = [item.requirement_id for item in values]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("Command mcp_refs must not contain duplicates")
        return values


class _CommandNodeDispatch(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    task_id: _TaskId
    dispatch_key: DispatchKey
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class _CommandNodeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activate: list[BranchKey] = Field(default_factory=list)
    dispatch: list[_CommandNodeDispatch] = Field(default_factory=list)
    update: dict[str, Any] = Field(default_factory=dict)

    @field_validator("activate")
    @classmethod
    def unique_branches(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("activated command branches must be unique")
        return values

    @field_validator("dispatch")
    @classmethod
    def unique_task_ids(
        cls,
        values: list[_CommandNodeDispatch],
    ) -> list[_CommandNodeDispatch]:
        task_ids = [item.task_id for item in values]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("command dispatch task IDs must be unique")
        return values


class CommandError(RuntimeError):
    """Safe wrapper for user-authored routing failures."""


def _detached(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _detached(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_detached(item) for item in value]
    if isinstance(value, list):
        return [_detached(item) for item in value]
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_detached(item) for item in value]
    return deepcopy(value)


def _state_delta(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    from agent_shell.runtime.state import WorkflowState

    allowed = frozenset(WorkflowState.__annotations__)
    unexpected = sorted(set(after) - allowed)
    if unexpected:
        raise ValueError(
            "command modified unsupported Workflow State fields: "
            + ", ".join(unexpected)
        )
    deleted = sorted(set(before) - set(after))
    if deleted:
        raise ValueError(
            "command cannot delete Workflow State channels: " + ", ".join(deleted)
        )
    return {
        key: value
        for key, value in after.items()
        if key not in before or before[key] != value
    }


async def run_command(
    command: CommandCallable,
    *,
    state: Mapping[str, Any],
    runtime: Runtime[WorkflowRuntimeContext],
    allowed_branches: Collection[str],
    allowed_dispatch_keys: Collection[str] = (),
) -> _CommandNodeResult:
    from agent_shell.runtime.state import WorkflowState, validate_workflow_state_update

    original_state = _detached(state)
    script_state = _detached(state)
    try:
        value = await command(
            state=script_state,
            runtime=runtime,
        )
        result = _CommandNodeResult.model_validate(value)
        mutation_update = _state_delta(original_state, script_state)
        update = {**mutation_update, **result.update}
        unsupported_updates = sorted(
            set(update) - frozenset(WorkflowState.__annotations__)
        )
        if unsupported_updates:
            raise ValueError(
                "command returned unsupported Workflow State fields: "
                + ", ".join(unsupported_updates)
            )
        update = validate_workflow_state_update(update)
        activate = result.activate
        unknown = sorted(set(activate) - set(allowed_branches))
        if unknown:
            raise ValueError(
                "command activated branches without a matching Workflow edge: "
                + ", ".join(unknown)
            )
        unknown_dispatches = sorted(
            {item.dispatch_key for item in result.dispatch}
            - set(allowed_dispatch_keys)
        )
        if unknown_dispatches:
            raise ValueError(
                "command dispatched tasks without a matching Workflow edge: "
                + ", ".join(unknown_dispatches)
            )
        return _CommandNodeResult(
            activate=activate,
            dispatch=result.dispatch,
            update=update,
        )
    except Exception as exc:
        raise CommandError("command failed") from exc


__all__ = [
    "BranchKey",
    "CommandBlock",
    "CommandCallable",
    "CommandError",
    "DispatchKey",
    "run_command",
]
