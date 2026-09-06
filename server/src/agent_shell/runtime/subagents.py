from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agent_shell.capability_manifest import (
    ASYNC_SUBAGENT_TOOL_NAMES,
    FILESYSTEM_TOOL_NAMES,
)
from agent_shell.runtime.agent_assistants import main_agent_assistant_id
from agent_shell.runtime.agent_compilation import (
    ProfileMaterializer,
    materialize_patch_tool_calls_middleware,
    reported_error,
    validate_middleware_names,
    validate_model_visible_tool_names,
)
from agent_shell.runtime.capabilities import DeepAgentsWorkspace
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.limits import (
    ProviderErrorBoundaryMiddleware,
    ToolErrorBoundaryMiddleware,
)
from agent_shell.runtime.model_request_settings import (
    make_model_request_settings_middleware,
)
from agent_shell.validation.assembly import (
    ResolvedAsyncSubagent,
    ResolvedSubagent,
    ResolvedSubagentEdge,
    SubagentNodeKey,
)


def build_async_subagent_specs(
    references: tuple[ResolvedAsyncSubagent, ...],
) -> list[dict[str, str]]:
    """Project references to Deep Agents' official AsyncSubAgent dictionaries."""

    return [
        {
            "name": reference.name,
            "description": reference.description,
            "graph_id": main_agent_assistant_id(reference.main_agent_id),
        }
        for reference in references
    ]


def build_subagent_specs(
    *,
    roots: tuple[ResolvedSubagentEdge, ...],
    nodes: dict[SubagentNodeKey, ResolvedSubagent],
    workspace: DeepAgentsWorkspace,
    materialize_profile: ProfileMaterializer,
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
            materialize_profile=materialize_profile,
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
    workspace: DeepAgentsWorkspace,
    materialize_profile: ProfileMaterializer,
    workflow_node_id: str | None,
    mapped_directory_paths_by_filesystem: Mapping[
        str, Mapping[str, Path]
    ] | None,
    initial_files: dict[str, Any] | None,
) -> dict[str, Any]:
    child = materialize_profile(
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
        disabled_capabilities=node.disabled_capabilities,
        mcp_references=node.mcp_references,
    )
    if initial_files is not None:
        for path, value in child.workspace.initial_files.items():
            previous = initial_files.get(path)
            if previous is not None and previous != value:
                raise AgentRuntimeError(
                    "filesystem_virtual_source_conflict",
                    f"Subagent virtual source conflicts at {path!r}.",
                    status_code=422,
                )
            initial_files[path] = value
    middleware: list[Any] = [
        ToolErrorBoundaryMiddleware(),
        *child.middleware,
        materialize_patch_tool_calls_middleware(),
    ]
    if child.tool_choice is not None or child.model_settings:
        middleware.append(
            make_model_request_settings_middleware(
                tool_choice=child.tool_choice,
                model_settings=child.model_settings,
            )
        )
    middleware.extend(child.extra_middleware)
    middleware.append(ProviderErrorBoundaryMiddleware())
    if child.exception_retry is not None:
        middleware.extend(child.exception_retry.after_provider_boundary)
    middleware.extend(child.package_middleware)

    try:
        validate_middleware_names(middleware, owner=f"Subagent {node.name}")
        middleware_names = {getattr(item, "name", None) for item in middleware}
        validate_model_visible_tool_names(
            tools=child.tools,
            middleware=middleware,
            owner=f"Subagent {node.name}",
            default_tool_names=(
                ()
                if "FilesystemMiddleware" in middleware_names
                else FILESYSTEM_TOOL_NAMES
            ),
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
    if child.permissions:
        spec["permissions"] = list(child.permissions)
    return spec
