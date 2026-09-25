from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_shell.runtime.agent_compilation import (
    AgentResourceMaterializer,
    assemble_agent_middleware,
    materialize_patch_tool_calls_middleware,
    reported_error,
    validate_middleware_names,
    validate_model_visible_tool_names,
)
from agent_shell.runtime.capabilities import DeepAgentsWorkspace
from agent_shell.runtime.deepagents_compatibility import (
    EmptySystemMessageMiddleware,
)
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.limits import (
    ProviderErrorBoundaryMiddleware,
    ToolErrorBoundaryMiddleware,
)
from agent_shell.runtime.model_request_settings import (
    make_model_request_settings_middleware,
)
from agent_shell.runtime.model_call_archive import ModelCallArchiveMiddleware
from agent_shell.validation.assembly import (
    ResolvedSubagent,
    ResolvedSubagentEdge,
    SubagentNodeKey,
)

if TYPE_CHECKING:
    from agent_shell.runtime.diagnostics import RuntimeDiagnostics
    from agent_shell.storage.model_call_archive import ModelCallArchive


def build_subagent_specs(
    *,
    roots: tuple[ResolvedSubagentEdge, ...],
    nodes: dict[SubagentNodeKey, ResolvedSubagent],
    workspace: DeepAgentsWorkspace | None,
    materialize_resources: AgentResourceMaterializer,
    workflow_node_id: str | None = None,
    mapped_directory_paths_by_filesystem: Mapping[
        str, Mapping[str, Path]
    ] | None = None,
    initial_files: dict[str, Any] | None = None,
    runtime_diagnostics: RuntimeDiagnostics | None = None,
    model_call_archive: ModelCallArchive | None = None,
) -> list[dict[str, Any]]:
    """Project directly referenced Subagents to official SubAgent dictionaries."""

    return [
        _build_subagent_spec(
            nodes[edge.target_key],
            workspace=workspace,
            materialize_resources=materialize_resources,
            workflow_node_id=workflow_node_id,
            mapped_directory_paths_by_filesystem=(
                mapped_directory_paths_by_filesystem
            ),
            initial_files=initial_files,
            runtime_diagnostics=runtime_diagnostics,
            model_call_archive=model_call_archive,
        )
        for edge in roots
    ]


def _build_subagent_spec(
    node: ResolvedSubagent,
    *,
    workspace: DeepAgentsWorkspace | None,
    materialize_resources: AgentResourceMaterializer,
    workflow_node_id: str | None,
    mapped_directory_paths_by_filesystem: Mapping[
        str, Mapping[str, Path]
    ] | None,
    initial_files: dict[str, Any] | None,
    runtime_diagnostics: RuntimeDiagnostics | None,
    model_call_archive: ModelCallArchive | None,
) -> dict[str, Any]:
    subagent_resources = materialize_resources(
        node.references,
        node.blocks,
        filesystem_mode=node.filesystem_mode,
        scope="subagent",
        owner_id=node.key,
        owner_name=node.name,
        workflow_node_id=workflow_node_id,
        workspace=workspace,
        mapped_directory_paths_by_filesystem=(
            mapped_directory_paths_by_filesystem
        ),
        mcp_references=node.mcp_references,
    )
    if initial_files is not None and subagent_resources.workspace is not None:
        for path, value in subagent_resources.workspace.initial_files.items():
            previous = initial_files.get(path)
            if previous is not None and previous != value:
                raise AgentRuntimeError(
                    "filesystem_virtual_source_conflict",
                    f"Subagent virtual source conflicts at {path!r}.",
                    status_code=422,
                )
            initial_files[path] = value
    model_request_settings_middleware = None
    if subagent_resources.tool_choice is not None or subagent_resources.model_settings:
        model_request_settings_middleware = make_model_request_settings_middleware(
            tool_choice=subagent_resources.tool_choice,
            model_settings=subagent_resources.model_settings,
        )
    middleware = assemble_agent_middleware(
        foundation=subagent_resources.foundation_middleware,
        subagent=None,
        summarization=subagent_resources.summarization_middleware,
        patch_tool_calls=materialize_patch_tool_calls_middleware(),
        model_call_limit=subagent_resources.model_call_limit_middleware,
        tool_call_limit=subagent_resources.tool_call_limit_middleware,
        tool_error_boundary=ToolErrorBoundaryMiddleware(
            runtime_diagnostics=runtime_diagnostics,
        ),
        todo=subagent_resources.todo_middleware,
        model_request_settings=model_request_settings_middleware,
        provider_error_boundary=ProviderErrorBoundaryMiddleware(
            runtime_diagnostics=runtime_diagnostics,
        ),
        exception_retry=(
            subagent_resources.exception_retry.after_provider_boundary
            if subagent_resources.exception_retry is not None
            else ()
        ),
        model_call_archive=(
            ModelCallArchiveMiddleware(archive=model_call_archive)
            if model_call_archive is not None
            else None
        ),
        package=subagent_resources.package_middleware,
        empty_system_message=EmptySystemMessageMiddleware(),
    )

    try:
        validate_middleware_names(middleware, owner=f"Subagent {node.name}")
        validate_model_visible_tool_names(
            tools=subagent_resources.tools,
            middleware=middleware,
            owner=f"Subagent {node.name}",
        )
    except AgentRuntimeError as exc:
        raise reported_error(
            exc,
            scope="subagent",
            owner_id=node.key,
            owner_name=node.name,
            path="capability_refs",
        ) from exc

    spec: dict[str, Any] = {
        "name": node.name,
        "description": node.description,
        "system_prompt": subagent_resources.system_prompt or "",
        "model": subagent_resources.model,
        "tools": list(subagent_resources.tools),
        "middleware": middleware,
    }
    if subagent_resources.response_format is not None:
        spec["response_format"] = subagent_resources.response_format
    return spec
