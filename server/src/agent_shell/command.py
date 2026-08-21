from __future__ import annotations

from collections.abc import Awaitable, Collection, Mapping, Sequence
from copy import deepcopy
from typing import Annotated, Any, Callable

from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from agent_shell.python_packages.contracts import PythonPackageReference
from agent_shell.runtime.context import WorkflowRuntimeContext


BranchKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True),
    Field(min_length=1, max_length=64),
]
CommandCallable = Callable[
    [dict[str, Any], Runtime[WorkflowRuntimeContext]],
    Awaitable[Any],
]


class CommandBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Annotated[str, Field(min_length=1, max_length=120)]
    python_package: PythonPackageReference


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activate: list[BranchKey] = Field(default_factory=list)
    update: dict[str, Any] = Field(default_factory=dict)

    @field_validator("activate")
    @classmethod
    def unique_branches(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("activated command branches must be unique")
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
) -> CommandResult:
    from agent_shell.runtime.state import WorkflowState, validate_workflow_state_update

    original_state = _detached(state)
    script_state = _detached(state)
    try:
        value = await command(
            state=script_state,
            runtime=runtime,
        )
        result = CommandResult.model_validate(value)
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
        return CommandResult(activate=activate, update=update)
    except Exception as exc:
        raise CommandError("command failed") from exc


__all__ = [
    "BranchKey",
    "CommandBlock",
    "CommandCallable",
    "CommandError",
    "CommandResult",
    "run_command",
]
