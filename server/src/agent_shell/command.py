from __future__ import annotations

from collections.abc import Awaitable, Mapping, Sequence
from copy import deepcopy
from typing import Any, Callable

from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_shell.configuration.identity import ConfigurationName
from agent_shell.mcp.contracts import McpReference
from agent_shell.python_packages.contracts import PythonPackageReference
from agent_shell.runtime.context import WorkflowRuntimeContext


CommandCallable = Callable[
    [dict[str, Any], Runtime[WorkflowRuntimeContext]],
    Awaitable[Command[Any]],
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


class CommandError(RuntimeError):
    """Safe wrapper for user-authored Command failures."""


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


def _normalize_goto(
    goto: Any,
    target_map: Mapping[str, str],
) -> str | list[str] | tuple[()]:
    if goto == ():
        return ()
    values = [goto] if isinstance(goto, str) else list(goto)
    if any(not isinstance(target, str) for target in values):
        raise ValueError("command goto accepts only Workflow Node IDs or END")

    allowed_graph_targets = frozenset(target_map.values())
    normalized: list[str] = []
    unknown: list[str] = []
    for target in values:
        if target in target_map:
            normalized.append(target_map[target])
        elif target == END and END in allowed_graph_targets:
            normalized.append(END)
        else:
            unknown.append(target)
    if unknown:
        raise ValueError(
            "command goto targets without a matching Workflow edge: "
            + ", ".join(sorted(set(unknown)))
        )
    if isinstance(goto, str):
        return normalized[0]
    return normalized


async def run_command(
    command: CommandCallable,
    *,
    state: Mapping[str, Any],
    runtime: Runtime[WorkflowRuntimeContext],
    target_map: Mapping[str, str],
) -> Command[Any]:
    """Run and validate the official Command returned by an extension."""

    from agent_shell.runtime.state import WorkflowState, validate_workflow_state_update

    try:
        result = await command(
            state=_detached(state),
            runtime=runtime,
        )
        if not isinstance(result, Command):
            raise TypeError("command must return langgraph.types.Command")
        if result.graph is not None:
            raise ValueError("command graph routing is not supported")
        if result.resume is not None:
            raise ValueError("command resume is not supported")

        raw_update = result.update
        if raw_update is None:
            update: dict[str, Any] = {}
        elif isinstance(raw_update, Mapping):
            update = _detached(raw_update)
        else:
            raise TypeError("command update must be a Workflow State mapping")
        unsupported = sorted(set(update) - frozenset(WorkflowState.__annotations__))
        if unsupported:
            raise ValueError(
                "command returned unsupported Workflow State fields: "
                + ", ".join(unsupported)
            )
        validated_update = validate_workflow_state_update(update)
        goto = _normalize_goto(result.goto, target_map)
        return Command(update=validated_update or None, goto=goto)
    except Exception as exc:
        raise CommandError("command failed") from exc


__all__ = [
    "CommandBlock",
    "CommandCallable",
    "CommandError",
    "run_command",
]
