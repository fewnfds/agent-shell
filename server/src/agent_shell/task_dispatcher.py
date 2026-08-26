from __future__ import annotations

from collections.abc import Awaitable, Collection, Mapping, Sequence
from copy import deepcopy
from typing import Annotated, Any, Callable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
)
from langgraph.runtime import Runtime

from agent_shell.configuration.identity import ConfigurationName
from agent_shell.python_packages.contracts import PythonPackageReference
from agent_shell.runtime.context import WorkflowRuntimeContext


DispatchKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True),
    Field(min_length=1, max_length=64),
]
TaskId = Annotated[
    str,
    StringConstraints(strip_whitespace=True),
    Field(min_length=1, max_length=128),
]
TaskDispatcherCallable = Callable[
    [dict[str, Any], Runtime[WorkflowRuntimeContext]],
    Awaitable[Any],
]


class TaskDispatcherBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: ConfigurationName
    python_package: PythonPackageReference


class TaskDispatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    task_id: TaskId
    dispatch_key: DispatchKey
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class TaskDispatcherResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[TaskDispatchItem] = Field(min_length=1)
    update: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tasks")
    @classmethod
    def unique_task_ids(
        cls,
        values: list[TaskDispatchItem],
    ) -> list[TaskDispatchItem]:
        task_ids = [item.task_id for item in values]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task dispatcher task IDs must be unique")
        return values


class TaskDispatcherError(RuntimeError):
    """Safe wrapper for user-authored task dispatcher failures."""


def _detached(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _detached(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_detached(item) for item in value]
    if isinstance(value, list):
        return [_detached(item) for item in value]
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_detached(item) for item in value]
    return deepcopy(value)


def _state_delta(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, Any]:
    from agent_shell.runtime.state import WorkflowState

    allowed = frozenset(WorkflowState.__annotations__)
    unexpected = sorted(set(after) - allowed)
    if unexpected:
        raise ValueError(
            "dispatcher modified unsupported Workflow State fields: "
            + ", ".join(unexpected)
        )
    deleted = sorted(set(before) - set(after))
    if deleted:
        raise ValueError(
            "dispatcher cannot delete Workflow State channels: "
            + ", ".join(deleted)
        )
    return {
        key: value
        for key, value in after.items()
        if key not in before or before[key] != value
    }


async def run_task_dispatcher(
    dispatch: TaskDispatcherCallable,
    *,
    state: Mapping[str, Any],
    runtime: Runtime[WorkflowRuntimeContext],
    allowed_dispatch_keys: Collection[str],
) -> TaskDispatcherResult:
    from agent_shell.runtime.state import WorkflowState, validate_workflow_state_update

    original_state = _detached(state)
    script_state = _detached(state)
    try:
        value = await dispatch(
            state=script_state,
            runtime=runtime,
        )
        result = TaskDispatcherResult.model_validate(value)
        mutation_update = _state_delta(original_state, script_state)
        update = {**mutation_update, **result.update}
        unsupported_updates = sorted(
            set(update) - frozenset(WorkflowState.__annotations__)
        )
        if unsupported_updates:
            raise ValueError(
                "dispatcher returned unsupported Workflow State fields: "
                + ", ".join(unsupported_updates)
            )
        update = validate_workflow_state_update(update)
        unknown = sorted(
            {item.dispatch_key for item in result.tasks}
            - set(allowed_dispatch_keys)
        )
        if unknown:
            raise ValueError(
                "dispatcher used keys without a matching Workflow edge: "
                + ", ".join(unknown)
            )
        return TaskDispatcherResult(tasks=result.tasks, update=update)
    except Exception as exc:
        raise TaskDispatcherError("task dispatcher failed") from exc


__all__ = [
    "DispatchKey",
    "TaskDispatchItem",
    "TaskDispatcherBlock",
    "TaskDispatcherCallable",
    "TaskDispatcherError",
    "TaskDispatcherResult",
    "run_task_dispatcher",
]
