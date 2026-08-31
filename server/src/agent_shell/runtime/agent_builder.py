from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from langchain.chat_models import init_chat_model
from langgraph.store.base import BaseStore
from pydantic import SecretStr

from agent_shell import __version__
from agent_shell.middleware_packages.runtime import MiddlewarePackageRuntime
from agent_shell.python_packages.dependencies import dependency_metadata
from agent_shell.capability_manifest import FILESYSTEM_TOOL_NAMES
from agent_shell.contracts import (
    AgentEventOutputBlock,
    FilesystemBlock,
    FilesystemToolsBlock,
    SkillBlock,
)
from agent_shell.provider_http import ProviderHttpClients, provider_http_timeout
from agent_shell.provider_secrets import ProviderCredentialError, ProviderSecretResolver
from agent_shell.runtime.capabilities import (
    DeepAgentsCapabilityError,
    DeepAgentsWorkspace,
    build_deepagents_capabilities,
)
from agent_shell.runtime.capabilities.exception_retry import (
    materialize_exception_retry,
    model_block_with_retry_overrides,
)
from agent_shell.runtime.capabilities.prompt_caching import (
    disabled_prompt_caching_middleware,
    materialize_prompt_caching_middleware,
)
from agent_shell.runtime.capabilities.summarization import (
    disabled_summarization_middleware,
    materialize_summarization_middleware,
)
from agent_shell.runtime.capabilities.todo_list import (
    disabled_todo_list_middleware,
    materialize_todo_list_middleware,
)
from agent_shell.runtime.agent_compilation import (
    MaterializedAgentProfile,
    configuration_error,
    construct_deep_agent,
    enable_deepagents_trace_inputs,
    materialize_patch_tool_calls_middleware,
    reported_error,
    validate_middleware_names,
    validate_model_visible_tool_names,
)
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.input_messages import validate_client_messages
from agent_shell.runtime.limits import (
    ProviderErrorBoundaryMiddleware,
    ToolErrorBoundaryMiddleware,
)
from agent_shell.runtime.model_request_settings import (
    make_model_request_settings_middleware,
)
from agent_shell.runtime.state import AgentShellState
from agent_shell.validation.capability_assembly import FilesystemMode
from agent_shell.validation.service import ConfigurationValidationService
from agent_shell.validation.assembly import StaticAssembly
from agent_shell.python_requirements import parse_python_requirements
from agent_shell.storage.runtime_policy import RUNTIME_POLICY_DEFAULTS, RuntimePolicyStore
from agent_shell.storage.model_connections import ModelResourceSnapshot, ModelResourceStore
from agent_shell.storage.mcp_connections import McpResourceSnapshot
from agent_shell.runtime.mcp import McpRunRuntime
from agent_shell.validation.assembly import ResolvedMcpReference
from agent_shell.tool_packages import ToolPackageRuntime


_OPENAI_COMPATIBLE_PROVIDERS = frozenset({"deepseek", "openai", "xai"})


def _build_chat_model(
    block: dict[str, Any],
    credential: str | None,
    provider_http_clients: ProviderHttpClients,
):
    provider = str(block["provider"])
    try:
        kwargs: dict[str, object] = {
            "base_url": block["base_url"],
            **dict(block["provider_settings"]),
        }
        if kwargs.get("streaming") is False:
            kwargs["disable_streaming"] = True
        if provider == "google_vertexai":
            if credential:
                raise ValueError(
                    "google_vertexai uses Application Default Credentials"
                )
        else:
            kwargs["api_key"] = SecretStr(
                credential or "agent-shell-no-credential"
            )
        if provider in _OPENAI_COMPATIBLE_PROVIDERS:
            timeout_factory = getattr(provider_http_clients, "timeout", None)
            kwargs.setdefault(
                "timeout",
                timeout_factory()
                if callable(timeout_factory)
                else provider_http_timeout(),
            )
            kwargs.update(
                {
                    "default_headers": {
                        "User-Agent": f"Agent-Shell/{__version__}",
                    },
                    "http_client": provider_http_clients.sync_client,
                    "http_async_client": provider_http_clients.async_client,
                }
            )
        if provider == "openai":
            # Chat Completions is the explicit default for arbitrary gateway URLs.
            kwargs.setdefault("use_responses_api", False)
        return init_chat_model(
            model=str(block["model"]),
            model_provider=provider,
            **kwargs,
        )
    except ImportError as exc:
        raise AgentRuntimeError(
            "model_provider_adapter_unavailable",
            "The selected LangChain Provider integration is not installed.",
            status_code=503,
        ) from exc
    except Exception as exc:
        raise AgentRuntimeError(
            "model_configuration_invalid",
            "The selected model configuration cannot construct its Provider adapter.",
            status_code=422,
        ) from exc

@dataclass(frozen=True, slots=True)
class BuiltAgent:
    graph: Any
    input_state: dict[str, Any]
    event_output_id: str
    event_output_reference: dict[str, Any]
    agent_id: str
    agent_name: str
    subagent_profile_ids: dict[str, str]
    middleware_runtime: MiddlewarePackageRuntime
    tool_runtime: ToolPackageRuntime | None = None
    workspace: DeepAgentsWorkspace | None = None


class AgentBuilder:
    def __init__(
        self,
        secrets: ProviderSecretResolver,
        *,
        python_packages_dir: Path,
        runtime_dir: Path,
        skills_dir: Path,
        validation: ConfigurationValidationService,
        provider_http_clients: ProviderHttpClients,
        store: BaseStore,
        model_resources: ModelResourceStore | ModelResourceSnapshot | None = None,
        mcp_resources: McpResourceSnapshot | None = None,
        repository_id: str | None = None,
        runtime_policy: RuntimePolicyStore | None = None,
    ) -> None:
        self._secrets = secrets
        self._python_packages_dir = python_packages_dir
        self._runtime_dir = runtime_dir
        self._skills_dir = skills_dir
        self._validation = validation
        self._provider_http_clients = provider_http_clients
        self._runtime_policy = runtime_policy
        self._store = store
        self._model_resources = model_resources or getattr(secrets, "model_connections", None)
        self._repository_id = repository_id or getattr(secrets, "repository_id", "")
        self._mcp_resources = mcp_resources
        self._mcp_runtime: McpRunRuntime | None = None
        self._tool_runtime: ToolPackageRuntime | None = None
        self._middleware_runtime: MiddlewarePackageRuntime | None = None

    async def discover_mcp(
        self,
        references: tuple[ResolvedMcpReference, ...],
    ) -> McpRunRuntime | None:
        if self._mcp_resources is None:
            if references:
                raise AgentRuntimeError(
                    "mcp_runtime_unavailable",
                    "MCP runtime configuration is unavailable.",
                    status_code=500,
                )
            return None
        return await McpRunRuntime.discover(
            self._mcp_resources,
            self._repository_id,
            references,
        )

    def bind_mcp_runtime(self, runtime: McpRunRuntime | None) -> None:
        self._mcp_runtime = runtime

    async def close_failed_build(self) -> None:
        if self._tool_runtime is not None:
            await self._tool_runtime.close()
        if self._middleware_runtime is not None:
            await self._middleware_runtime.close()

    def script_dependency_metadata(
        self,
        component_type: str,
        component: dict[str, Any],
    ) -> dict[str, object]:
        return dependency_metadata(
            f"{component_type}:{component.get('id', '')}",
            parse_python_requirements(component.get("python_requirements", [])),
            self._runtime_dir,
        )

    def resolve(
        self,
        main_agent_id: str,
    ) -> StaticAssembly:
        report, assembly = self._validation.resolve_main_agent(main_agent_id)
        if not report.valid:
            issue = report.issues[0]
            if (
                issue.code == "configuration.reference_not_found"
                and issue.path == "id"
                and issue.message_args.get("expected_type") == "main_agent"
            ):
                status_code = 404
            elif issue.code in {
                "assembly.referenced_block_invalid",
                "assembly.tool_name_conflict",
            } or issue.code.startswith("contract."):
                status_code = 422
            else:
                status_code = 409
            raise AgentRuntimeError(
                issue.code,
                issue.message,
                status_code=status_code,
                validation_report=report,
            )
        assert assembly is not None
        return assembly

    def _materialize_profile(
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
    ) -> MaterializedAgentProfile:
        requirement_id = references.get("model-requirement")
        if not requirement_id or "model-requirement" not in selected_blocks:
            raise configuration_error(
                "model_requirement_unbound",
                "The Agent does not select a model requirement.",
                status_code=409,
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                path="capability_refs.model-requirement",
                message_key="validation.issue.modelRequirementUnbound",
            )
        connection_id = (
            self._model_resources.get_binding(self._repository_id, requirement_id)
            if self._model_resources is not None
            else None
        )
        if not connection_id:
            raise configuration_error(
                "model_requirement_unbound",
                "The model requirement is not bound to a local model connection.",
                status_code=409,
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                path="capability_refs.model-requirement",
                message_key="validation.issue.modelRequirementUnbound",
            )
        try:
            if self._model_resources is None:
                raise KeyError(connection_id)
            model_block = self._model_resources.resolve_connection(connection_id)
        except KeyError as exc:
            raise configuration_error(
                "model_requirement_unbound",
                "The model requirement is bound to a missing local model connection.",
                status_code=409,
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                path="capability_refs.model-requirement",
                message_key="validation.issue.modelRequirementUnbound",
            ) from exc
        exception_retry = selected_blocks.get("exception-retry")
        effective_model_block = (
            model_block_with_retry_overrides(model_block, exception_retry)
            if exception_retry is not None
            else model_block
        )
        credential = model_block.pop("credential", None)
        try:
            model = _build_chat_model(
                effective_model_block,
                credential,
                self._provider_http_clients,
            )
        except AgentRuntimeError as exc:
            raise reported_error(
                exc,
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                path="capability_refs.model-requirement",
            ) from exc
        except Exception as exc:
            raise configuration_error(
                "model_configuration_invalid",
                "The selected model configuration could not be constructed.",
                status_code=422,
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                path="capability_refs.model-requirement",
            ) from exc

        tools: list[Any] = []
        if self._tool_runtime is not None:
            try:
                tools.extend(self._tool_runtime.tools_for(owner_id))
            except AgentRuntimeError as exc:
                raise reported_error(
                    exc,
                    scope=scope,
                    owner_id=owner_id,
                    owner_name=owner_name,
                    path="tool_refs",
                ) from exc
        if mcp_references:
            if self._mcp_runtime is None:
                raise configuration_error(
                    "mcp_runtime_unavailable",
                    "The selected MCP requirements are unavailable in this Workflow Run.",
                    status_code=409,
                    scope=scope,
                    owner_id=owner_id,
                    owner_name=owner_name,
                    path="mcp_refs",
                )
            try:
                tools.extend(self._mcp_runtime.tools_for(mcp_references))
            except AgentRuntimeError as exc:
                raise reported_error(
                    exc,
                    scope=scope,
                    owner_id=owner_id,
                    owner_name=owner_name,
                    path="mcp_refs",
                ) from exc

        middleware: list[Any] = []
        todo = selected_blocks.get("todo-list")
        if todo is not None:
            try:
                middleware.append(materialize_todo_list_middleware(todo))
            except Exception as exc:
                raise configuration_error(
                    "middleware_materialization_failed",
                    "The selected Todo capability could not be constructed.",
                    status_code=422,
                    scope=scope,
                    owner_id=owner_id,
                    owner_name=owner_name,
                    path="capability_refs.todo-list",
                ) from exc

        elif "todo-list" in disabled_capabilities:
            middleware.append(disabled_todo_list_middleware())

        backend = None
        skill_sources: tuple[str, ...] = ()
        filesystem = selected_blocks.get("filesystem")
        filesystem_tools = selected_blocks.get("filesystem-tools")
        skill = selected_blocks.get("_filesystem-skill-package")
        try:
            if filesystem is None or filesystem_tools is None:
                raise DeepAgentsCapabilityError(
                    "Filesystem Backend and Filesystem Tools are required"
                )
            filesystem_block = FilesystemBlock.model_validate(
                {
                    key: value
                    for key, value in filesystem.items()
                    if key != "id"
                }
            )
            filesystem_tools_block = FilesystemToolsBlock.model_validate(
                {
                    key: value
                    for key, value in filesystem_tools.items()
                    if key != "id"
                }
            )
            skill_block = (
                SkillBlock.model_validate(
                    {key: value for key, value in skill.items() if key != "id"}
                )
                if skill is not None
                else None
            )
            deepagents = build_deepagents_capabilities(
                filesystem_block,
                skill_block,
                filesystem_tools=filesystem_tools_block,
                filesystem_mode=filesystem_mode,
                skills_dir=self._skills_dir,
                workspace=workspace,
                mapped_directory_paths=(
                    mapped_directory_paths_by_filesystem.get(
                        str(filesystem.get("id", ""))
                    )
                    if filesystem is not None
                    and mapped_directory_paths_by_filesystem is not None
                    else None
                ),
            )
        except DeepAgentsCapabilityError as exc:
            raise configuration_error(
                "middleware_materialization_failed",
                "The selected filesystem configuration or Skill package could not be constructed.",
                status_code=422,
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                path=(
                    "capability_refs.filesystem.skill_package_id"
                    if skill is not None
                    else "capability_refs.filesystem"
                ),
            ) from exc
        except Exception as exc:
            raise configuration_error(
                "middleware_materialization_failed",
                "The selected filesystem or Skill configuration is invalid.",
                status_code=422,
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                path=(
                    "capability_refs.filesystem.skill_package_id"
                    if skill is not None
                    else "capability_refs.filesystem"
                ),
            ) from exc
        backend = deepagents.backend
        middleware.extend(deepagents.middleware)
        skill_sources = deepagents.skill_sources

        extra_middleware: list[Any] = []
        summarization = selected_blocks.get("summarization")
        if summarization is not None:
            try:
                extra_middleware.append(
                    materialize_summarization_middleware(
                        summarization,
                        model=model,
                        backend=backend,
                    )
                )
            except Exception as exc:
                raise configuration_error(
                    "middleware_materialization_failed",
                    "The selected summarization configuration could not be constructed.",
                    status_code=422,
                    scope=scope,
                    owner_id=owner_id,
                    owner_name=owner_name,
                    path="capability_refs.summarization",
                ) from exc
        elif "summarization" in disabled_capabilities:
            extra_middleware.append(disabled_summarization_middleware())

        prompt_caching = selected_blocks.get("prompt-caching")
        if prompt_caching is not None:
            try:
                extra_middleware.append(
                    materialize_prompt_caching_middleware(prompt_caching)
                )
            except Exception as exc:
                raise configuration_error(
                    "middleware_materialization_failed",
                    "The selected prompt-caching configuration could not be constructed.",
                    status_code=422,
                    scope=scope,
                    owner_id=owner_id,
                    owner_name=owner_name,
                    path="capability_refs.prompt-caching",
                ) from exc
        elif "prompt-caching" in disabled_capabilities:
            extra_middleware.append(disabled_prompt_caching_middleware())

        package_middleware: tuple[Any, ...] = ()
        if self._middleware_runtime is not None:
            try:
                package_middleware = self._middleware_runtime.middleware_for(
                    owner_id,
                    context={
                        "config": dict(selected_blocks),
                        "blocks": dict(selected_blocks),
                        "references": dict(references),
                        "backend": backend,
                        "deepagents": deepagents,
                        "filesystem_mode": filesystem_mode,
                        "scope": scope,
                        "owner_id": owner_id,
                        "owner_name": owner_name,
                        "workflow_node_id": workflow_node_id,
                        "model": model,
                        "tools": tuple(tools),
                    },
                )
            except AgentRuntimeError as exc:
                raise reported_error(
                    exc,
                    scope=scope,
                    owner_id=owner_id,
                    owner_name=owner_name,
                    path="middleware_refs",
                ) from exc

        system_prompt = selected_blocks.get("system-prompt")
        exception_retry_runtime = (
            materialize_exception_retry(exception_retry)
            if exception_retry is not None
            else None
        )
        return MaterializedAgentProfile(
            model=model,
            model_provider=str(model_block["provider"]),
            model_name=str(model_block["model"]),
            tool_choice=model_block.get("tool_choice"),
            response_format=model_block.get("response_format"),
            model_settings=dict(model_block.get("model_settings") or {}),
            exception_retry=exception_retry_runtime,
            system_prompt=(
                system_prompt["system_prompt"] if system_prompt is not None else None
            ),
            tools=tuple(tools),
            middleware=tuple(middleware),
            package_middleware=package_middleware,
            extra_middleware=tuple(extra_middleware),
            backend=backend,
            skill_sources=skill_sources,
            permissions=deepagents.permissions,
            workspace=deepagents.workspace,
        )

    async def build(
        self,
        main_agent_id: str,
        raw_messages: object,
        *,
        request_id: str = "",
        workflow_node_id: str | None = None,
        workspace: DeepAgentsWorkspace | None = None,
        mapped_directory_paths_by_filesystem: Mapping[
            str, Mapping[str, Path]
        ] | None = None,
        workflow_debug_capture_enabled: bool = False,
    ) -> BuiltAgent:
        # Validate the immutable request snapshot before any selected user module
        # can be imported or any optional capability can be materialized.
        messages = validate_client_messages(
            raw_messages,
            self._runtime_policy.snapshot()
            if self._runtime_policy is not None
            else RUNTIME_POLICY_DEFAULTS,
        )
        assembly = self.resolve(main_agent_id)
        return await self.build_resolved(
            assembly,
            messages,
            request_id=request_id,
            workflow_node_id=workflow_node_id,
            workspace=workspace,
            mapped_directory_paths_by_filesystem=(
                mapped_directory_paths_by_filesystem
            ),
            workflow_debug_capture_enabled=workflow_debug_capture_enabled,
        )

    async def build_resolved(
        self,
        assembly: StaticAssembly,
        _messages: list[dict[str, Any]],
        *,
        request_id: str = "",
        workflow_node_id: str | None = None,
        workspace: DeepAgentsWorkspace | None = None,
        mapped_directory_paths_by_filesystem: Mapping[
            str, Mapping[str, Path]
        ] | None = None,
        workflow_debug_capture_enabled: bool = False,
    ) -> BuiltAgent:
        main_agent = assembly.main_agent
        references = assembly.references
        selected_blocks = assembly.blocks
        stored_event_output = selected_blocks["agent-event-output"]
        event_output = AgentEventOutputBlock.model_validate(
            {
                key: value
                for key, value in stored_event_output.items()
                if key != "id"
            }
        )
        resolved_subagents = assembly.subagents

        main_agent_id = str(main_agent["id"])
        main_agent_name = str(main_agent["name"])
        tool_runtime = ToolPackageRuntime.from_assembly(
            assembly,
            main_agent_id=main_agent_id,
            request_id=request_id,
            packages_dir=self._python_packages_dir,
            runtime_root=self._runtime_dir,
        )
        self._tool_runtime = tool_runtime
        middleware_runtime = MiddlewarePackageRuntime.from_assembly(
            assembly,
            main_agent_id=main_agent_id,
            request_id=request_id,
            packages_dir=self._python_packages_dir,
            runtime_root=self._runtime_dir,
        )
        self._middleware_runtime = middleware_runtime
        materialized = self._materialize_profile(
            references,
            selected_blocks,
            filesystem_mode=assembly.filesystem_mode,
            scope="main_agent",
            owner_id=main_agent_id,
            owner_name=main_agent_name,
            workflow_node_id=workflow_node_id,
            workspace=workspace,
            mapped_directory_paths_by_filesystem=(
                mapped_directory_paths_by_filesystem
            ),
            disabled_capabilities=assembly.disabled_capabilities,
            mcp_references=assembly.mcp_references,
        )
        enable_deepagents_trace_inputs(
            [*materialized.middleware, *materialized.extra_middleware],
            debug_capture=workflow_debug_capture_enabled,
        )
        constructor: dict[str, object] = {
            "model": materialized.model,
            "name": str(main_agent["name"]),
            "state_schema": AgentShellState,
            "context_schema": WorkflowRuntimeContext,
            "store": self._store,
        }
        if materialized.system_prompt is not None:
            constructor["system_prompt"] = materialized.system_prompt
        if materialized.tools:
            constructor["tools"] = list(materialized.tools)
        if materialized.response_format is not None:
            constructor["response_format"] = materialized.response_format
        if materialized.backend is not None:
            constructor["backend"] = materialized.backend
        if materialized.permissions:
            constructor["permissions"] = list(materialized.permissions)
        if materialized.skill_sources:
            constructor["skills"] = list(materialized.skill_sources)

        middleware = [
            ToolErrorBoundaryMiddleware(),
            *materialized.middleware,
            materialize_patch_tool_calls_middleware(
                debug_capture=workflow_debug_capture_enabled,
            ),
        ]
        if materialized.tool_choice is not None or materialized.model_settings:
            middleware.append(
                make_model_request_settings_middleware(
                    tool_choice=materialized.tool_choice,
                    model_settings=materialized.model_settings,
                )
            )
        input_state: dict[str, Any] = {
            "messages": [],
            "shared_vars": {},
        }

        compiled_subagents: list[dict[str, Any]] = []
        subagent_initial_files: dict[str, Any] = {}
        task_description_override: str | None = None
        if resolved_subagents:
            from agent_shell.runtime.subagents import build_subagent_specs

            compiled_subagents = build_subagent_specs(
                roots=resolved_subagents,
                nodes=assembly.subagent_nodes,
                workspace=materialized.workspace,
                materialize_profile=self._materialize_profile,
                workflow_node_id=workflow_node_id,
                mapped_directory_paths_by_filesystem=(
                    mapped_directory_paths_by_filesystem
                ),
                initial_files=subagent_initial_files,
                workflow_debug_capture_enabled=(
                    workflow_debug_capture_enabled
                ),
            )
            delegation_instruction = selected_blocks["subagent"][
                "instruction_override"
            ]
            task_description_override = selected_blocks["subagent"][
                "task_description_override"
            ]
            if delegation_instruction is not None:
                existing_prompt = str(constructor.get("system_prompt") or "")
                constructor["system_prompt"] = "\n\n".join(
                    part for part in (existing_prompt, delegation_instruction) if part
                )
            constructor["subagents"] = compiled_subagents

        middleware.extend(materialized.extra_middleware)
        exception_retry_runtime = materialized.exception_retry
        middleware.append(ProviderErrorBoundaryMiddleware())
        if exception_retry_runtime is not None:
            middleware.extend(exception_retry_runtime.after_provider_boundary)
        initial_files = dict(materialized.workspace.initial_files)
        for path, value in subagent_initial_files.items():
            previous = initial_files.get(path)
            if previous is not None and previous != value:
                raise configuration_error(
                    "filesystem_virtual_source_conflict",
                    f"Agent virtual source conflicts at {path!r}.",
                    status_code=422,
                    scope="main_agent",
                    owner_id=main_agent_id,
                    owner_name=main_agent_name,
                    path="capability_refs.filesystem",
                )
            initial_files[path] = value
        if initial_files or resolved_subagents:
            input_state["files"] = initial_files

        try:
            if compiled_subagents:
                from agent_shell.runtime.subagent_middleware import (
                    make_subagent_middleware_override,
                )

                replacement = make_subagent_middleware_override(
                    backend=materialized.backend,
                    subagents=compiled_subagents,
                    task_description=task_description_override,
                    middleware=(*middleware, *materialized.package_middleware),
                    state_schema=AgentShellState,
                    workflow_debug_capture_enabled=(
                        workflow_debug_capture_enabled
                    ),
                )
                if replacement is not None:
                    middleware.append(replacement)
            middleware.extend(materialized.package_middleware)
            validate_middleware_names(middleware, owner="Main Agent")
            main_agent_middleware_names = {
                getattr(item, "name", None) for item in middleware
            }
            validate_model_visible_tool_names(
                tools=materialized.tools,
                middleware=middleware,
                owner="Main Agent",
                default_tool_names=(
                    ()
                    if "FilesystemMiddleware" in main_agent_middleware_names
                    else FILESYSTEM_TOOL_NAMES
                )
                + (
                    ("task",)
                    if resolved_subagents
                    and "SubAgentMiddleware" not in main_agent_middleware_names
                    else ()
                ),
            )
        except AgentRuntimeError as exc:
            raise reported_error(
                exc,
                scope="main_agent",
                owner_id=main_agent_id,
                owner_name=main_agent_name,
                path="capability_refs",
            ) from exc

        if middleware:
            constructor["middleware"] = middleware

        graph = construct_deep_agent(
            constructor,
            model_provider=materialized.model_provider,
            model_name=materialized.model_name,
            scope="main_agent",
            owner_id=main_agent_id,
            owner_name=main_agent_name,
            subject="Main Agent",
            path="capability_refs",
        )

        return BuiltAgent(
            graph=graph,
            input_state=input_state,
            event_output_id=str(stored_event_output["id"]),
            event_output_reference=event_output.python_package.model_dump(mode="json"),
            agent_id=main_agent_id,
            agent_name=str(main_agent["name"]),
            subagent_profile_ids={
                node.name: node.key for node in assembly.subagent_nodes.values()
            },
            tool_runtime=tool_runtime,
            middleware_runtime=middleware_runtime,
            workspace=materialized.workspace,
        )
