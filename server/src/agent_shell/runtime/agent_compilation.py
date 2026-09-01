from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from agent_shell.runtime.capabilities import DeepAgentsWorkspace
from agent_shell.runtime.capabilities.exception_retry import ExceptionRetryRuntime
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.validation.capability_assembly import FilesystemMode
from agent_shell.validation.models import ValidationIssue, ValidationReport
from agent_shell.validation.assembly import ResolvedMcpReference


def materialize_patch_tool_calls_middleware() -> Any:
    """Build the Deep Agents default middleware with its official trace policy."""

    from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware

    return PatchToolCallsMiddleware()


@dataclass(frozen=True, slots=True)
class MaterializedAgentProfile:
    model: Any
    model_provider: str
    model_name: str
    tool_choice: Any | None
    response_format: Any | None
    model_settings: dict[str, Any]
    exception_retry: ExceptionRetryRuntime | None
    system_prompt: str | None
    tools: tuple[Any, ...]
    middleware: tuple[Any, ...]
    package_middleware: tuple[Any, ...]
    extra_middleware: tuple[Any, ...]
    backend: Any | None
    skill_sources: tuple[str, ...]
    permissions: tuple[Any, ...]
    workspace: DeepAgentsWorkspace


class ProfileMaterializer(Protocol):
    def __call__(
        self,
        references: dict[str, str],
        selected_blocks: dict[str, dict[str, Any]],
        *,
        filesystem_mode: FilesystemMode,
        scope: str,
        owner_id: str,
        owner_name: str,
        workflow_node_id: str | None = None,
        workspace: DeepAgentsWorkspace | None = None,
        mapped_directory_paths_by_filesystem: Mapping[
            str, Mapping[str, Path]
        ] | None = None,
        disabled_capabilities: frozenset[str] = frozenset(),
        mcp_references: tuple[ResolvedMcpReference, ...] = (),
    ) -> MaterializedAgentProfile: ...


def configuration_error(
    code: str,
    message: str,
    *,
    status_code: int,
    scope: str,
    owner_id: str,
    owner_name: str,
    path: str,
    message_key: str = "validation.issue.runtime.configuration",
) -> AgentRuntimeError:
    report = ValidationReport(
        stage="request_assembly",
        issues=(
            ValidationIssue(
                code=code,
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                path=path,
                message=message,
                message_key=message_key,
                message_args={},
            ),
        ),
    )
    return AgentRuntimeError(
        code,
        report.issues[0].message,
        status_code=status_code,
        validation_report=report,
    )


def reported_error(
    error: AgentRuntimeError,
    *,
    scope: str,
    owner_id: str,
    owner_name: str,
    path: str,
) -> AgentRuntimeError:
    if error.validation_report is not None:
        return error
    return configuration_error(
        error.code,
        error.safe_message,
        status_code=error.status_code,
        scope=scope,
        owner_id=owner_id,
        owner_name=owner_name,
        path=path,
    )


def validate_model_visible_tool_names(
    *,
    tools: list[Any] | tuple[Any, ...],
    middleware: list[Any] | tuple[Any, ...],
    owner: str,
    default_tool_names: tuple[str, ...] = (),
) -> None:
    seen: dict[str, str] = {}

    def register_name(name: object, source: str) -> None:
        if not isinstance(name, str) or not name:
            return
        previous = seen.get(name)
        if previous is not None:
            raise AgentRuntimeError(
                "agent_tool_name_conflict",
                f"The selected {owner} exposes duplicate model-visible tool "
                f"name '{name}' from {previous} and {source}.",
                status_code=422,
            )
        seen[name] = source

    for name in default_tool_names:
        register_name(name, "Deep Agents default harness")
    for tool in tools:
        register_name(getattr(tool, "name", None), "direct tools")
    for item in middleware:
        for tool in getattr(item, "tools", ()) or ():
            register_name(getattr(tool, "name", None), type(item).__name__)


def validate_middleware_names(
    middleware: list[Any] | tuple[Any, ...],
    *,
    owner: str,
) -> None:
    seen: set[str] = set()
    for item in middleware:
        name = getattr(item, "name", None)
        if not isinstance(name, str) or not name:
            continue
        if name in seen:
            raise AgentRuntimeError(
                "agent_middleware_name_conflict",
                f"The selected {owner} contains duplicate runtime Middleware "
                f"name '{name}'. Rename or remove one of the conflicting items.",
                status_code=422,
            )
        seen.add(name)


def construct_deep_agent(
    constructor: dict[str, object],
    *,
    model_provider: str,
    model_name: str,
    scope: str,
    owner_id: str,
    owner_name: str,
    subject: str,
    path: str,
) -> Any:
    try:
        from agent_shell.runtime.deepagents_harness import (
            ensure_agent_shell_harness_profiles,
        )
        from deepagents import create_deep_agent

        ensure_agent_shell_harness_profiles(
            provider=model_provider,
            model=model_name,
        )
        return create_deep_agent(**constructor)
    except AgentRuntimeError as exc:
        raise reported_error(
            exc,
            scope=scope,
            owner_id=owner_id,
            owner_name=owner_name,
            path=path,
        ) from exc
    except Exception as exc:
        raise configuration_error(
            "agent_construction_failed",
            f"The selected {subject} could not be constructed.",
            status_code=422,
            scope=scope,
            owner_id=owner_id,
            owner_name=owner_name,
            path=path,
        ) from exc
