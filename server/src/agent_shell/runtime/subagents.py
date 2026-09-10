from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

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
from agent_shell.validation.assembly import (
    ResolvedSubagent,
    ResolvedSubagentEdge,
    SubagentNodeKey,
)


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
) -> list[dict[str, Any]]:
    """Project direct children to Deep Agents' official SubAgent dictionaries."""

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
) -> dict[str, Any]:
    child = materialize_resources(
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
    if initial_files is not None and child.workspace is not None:
        for path, value in child.workspace.initial_files.items():
            previous = initial_files.get(path)
            if previous is not None and previous != value:
                raise AgentRuntimeError(
                    "filesystem_virtual_source_conflict",
                    f"Subagent virtual source conflicts at {path!r}.",
                    status_code=422,
                )
            initial_files[path] = value
    model_request_settings_middleware = None
    if child.tool_choice is not None or child.model_settings:
        model_request_settings_middleware = make_model_request_settings_middleware(
            tool_choice=child.tool_choice,
            model_settings=child.model_settings,
        )
    middleware = assemble_agent_middleware(
        foundation=child.foundation_middleware,
        subagent=None,
        summarization=child.summarization_middleware,
        patch_tool_calls=materialize_patch_tool_calls_middleware(),
        model_call_limit=child.model_call_limit_middleware,
        tool_call_limit=child.tool_call_limit_middleware,
        tool_error_boundary=ToolErrorBoundaryMiddleware(),
        todo=child.todo_middleware,
        model_request_settings=model_request_settings_middleware,
        provider_error_boundary=ProviderErrorBoundaryMiddleware(),
        exception_retry=(
            child.exception_retry.after_provider_boundary
            if child.exception_retry is not None
            else ()
        ),
        package=child.package_middleware,
        empty_system_message=EmptySystemMessageMiddleware(),
        prompt_caching=child.prompt_caching_middleware,
    )

    try:
        validate_middleware_names(middleware, owner=f"Subagent {node.name}")
        validate_model_visible_tool_names(
            tools=child.tools,
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
        "system_prompt": child.system_prompt or "",
        "model": child.model,
        "tools": list(child.tools),
        "middleware": middleware,
    }
    if child.response_format is not None:
        spec["response_format"] = child.response_format
    return spec
