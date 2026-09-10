from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from agent_shell.runtime.capabilities import DeepAgentsWorkspace
from agent_shell.runtime.capabilities.exception_retry import ExceptionRetryRuntime
from agent_shell.runtime.errors import AgentRuntimeError, describe_exception
from agent_shell.validation.capability_assembly import FilesystemMode
from agent_shell.validation.models import ValidationIssue, ValidationReport
from agent_shell.validation.assembly import ResolvedMcpReference


def materialize_patch_tool_calls_middleware() -> Any:
    """Build the Deep Agents default middleware with its official trace policy."""

    from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware

    return PatchToolCallsMiddleware()


@dataclass(frozen=True, slots=True)
class MaterializedAgentResources:
    model: Any
    tool_choice: Any | None
    response_format: Any | None
    model_settings: dict[str, Any]
    exception_retry: ExceptionRetryRuntime | None
    system_prompt: str | None
    tools: tuple[Any, ...]
    foundation_middleware: tuple[Any, ...]
    todo_middleware: Any | None
    summarization_middleware: Any | None
    model_call_limit_middleware: Any | None
    tool_call_limit_middleware: Any | None
    prompt_caching_middleware: Any | None
    package_middleware: tuple[Any, ...]
    backend: Any | None
    middleware_backend: Any | None
    workspace: DeepAgentsWorkspace | None


class AgentResourceMaterializer(Protocol):
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
        mcp_references: tuple[ResolvedMcpReference, ...] = (),
    ) -> MaterializedAgentResources: ...


def assemble_agent_middleware(
    *,
    foundation: Sequence[Any],
    subagent: Any | None,
    summarization: Any | None,
    patch_tool_calls: Any,
    model_call_limit: Any | None,
    tool_call_limit: Any | None,
    tool_error_boundary: Any,
    todo: Any | None,
    model_request_settings: Any | None,
    provider_error_boundary: Any,
    exception_retry: Sequence[Any] = (),
    initial_files: Any | None = None,
    package: Sequence[Any] = (),
    empty_system_message: Any | None = None,
    prompt_caching: Any | None = None,
) -> list[Any]:
    """Assemble the complete Agent Shell middleware stack in owned slots."""

    middleware = list(foundation)
    middleware.extend(
        item
        for item in (
            subagent,
            summarization,
            patch_tool_calls,
            model_call_limit,
            tool_call_limit,
            tool_error_boundary,
            todo,
            model_request_settings,
            provider_error_boundary,
        )
        if item is not None
    )
    middleware.extend(exception_retry)
    if initial_files is not None:
        middleware.append(initial_files)
    middleware.extend(package)
    if empty_system_message is not None:
        middleware.append(empty_system_message)
    if prompt_caching is not None:
        middleware.append(prompt_caching)
    return middleware


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
        describe_exception(error),
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


def construct_agent(
    constructor: dict[str, object],
    *,
    scope: str,
    owner_id: str,
    owner_name: str,
    subject: str,
    path: str,
) -> Any:
    try:
        from langchain.agents import create_agent as langchain_create_agent

        return langchain_create_agent(**constructor)
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
