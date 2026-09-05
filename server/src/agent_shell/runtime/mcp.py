from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Mapping
from uuid import uuid4

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from agent_shell.mcp.contracts import McpReference
from agent_shell.mcp.installation import McpInstallationError
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.storage.mcp_connections import (
    McpResourceSnapshot,
    McpSecretReferenceMissingError,
)

if TYPE_CHECKING:
    from agent_shell.validation.assembly import ResolvedMcpReference


def _selection_tools(
    reference: McpReference,
    discovered: Mapping[str, BaseTool],
) -> tuple[BaseTool, ...]:
    selection = reference.tool_selection
    if selection.mode == "all":
        return tuple(discovered.values())
    missing = [name for name in selection.tools if name not in discovered]
    if missing:
        raise AgentRuntimeError(
            "mcp_tool_selection_missing",
            "The selected MCP Connection does not publish every configured Tool: "
            + ", ".join(missing),
            status_code=409,
        )
    return tuple(discovered[name] for name in selection.tools)


@dataclass(frozen=True, slots=True)
class _DiscoveredServer:
    requirement_id: str
    namespace: str
    tools: Mapping[str, BaseTool]


class McpRunRuntime:
    """One Workflow Run's stateless adapter client and discovery result."""

    def __init__(
        self,
        client: MultiServerMCPClient,
        servers: Mapping[str, _DiscoveredServer],
    ) -> None:
        self.__client = client
        self.__servers = dict(servers)

    @classmethod
    async def discover(
        cls,
        resources: McpResourceSnapshot,
        repository_id: str,
        references: Iterable[ResolvedMcpReference],
    ) -> "McpRunRuntime | None":
        by_requirement: dict[str, ResolvedMcpReference] = {}
        for item in references:
            requirement_id = str(item.requirement.get("id", ""))
            by_requirement.setdefault(requirement_id, item)
        if not by_requirement:
            return None

        connections: dict[str, dict[str, Any]] = {}
        requirement_by_namespace: dict[str, str] = {}
        for requirement_id, item in by_requirement.items():
            namespace = str(item.requirement.get("namespace", ""))
            previous = requirement_by_namespace.get(namespace)
            if previous is not None and previous != requirement_id:
                raise AgentRuntimeError(
                    "mcp_namespace_conflict",
                    f"MCP requirements expose the same namespace: {namespace}",
                    status_code=409,
                )
            connection_id = resources.get_binding(repository_id, requirement_id)
            if not connection_id:
                raise AgentRuntimeError(
                    "mcp_requirement_unbound",
                    "An attached MCP requirement is not bound to an MCP Connection.",
                    status_code=409,
                )
            try:
                connection = await asyncio.to_thread(
                    resources.resolve_connection,
                    connection_id,
                )
            except KeyError as exc:
                raise AgentRuntimeError(
                    "mcp_requirement_unbound",
                    "An attached MCP requirement is bound to a missing MCP Connection.",
                    status_code=409,
                ) from exc
            except McpSecretReferenceMissingError as exc:
                raise AgentRuntimeError(
                    "mcp_connection_secret_missing",
                    "An attached MCP Connection is missing a required secret value.",
                    status_code=409,
                ) from exc
            except McpInstallationError as exc:
                raise AgentRuntimeError(
                    exc.code,
                    str(exc),
                    status_code=409,
                ) from exc
            if connection["transport"] == "http":
                connection["transport"] = "streamable_http"
            connections[namespace] = connection
            requirement_by_namespace[namespace] = requirement_id

        client = MultiServerMCPClient(
            connections,
            tool_name_prefix=True,
        )
        namespaces = tuple(connections)
        try:
            discovered_lists = await asyncio.gather(
                *(client.get_tools(server_name=namespace) for namespace in namespaces)
            )
        except Exception as exc:
            raise AgentRuntimeError(
                "mcp_discovery_failed",
                "An attached MCP Connection could not discover its Tools.",
                status_code=502,
            ) from exc

        servers: dict[str, _DiscoveredServer] = {}
        for namespace, tools in zip(namespaces, discovered_lists, strict=True):
            prefix = namespace + "_"
            by_raw_name: dict[str, BaseTool] = {}
            for tool in tools:
                visible_name = getattr(tool, "name", "")
                if not isinstance(visible_name, str) or not visible_name.startswith(prefix):
                    raise AgentRuntimeError(
                        "mcp_tool_name_invalid",
                        "The MCP adapter returned a Tool without the required namespace prefix.",
                        status_code=502,
                    )
                raw_name = visible_name[len(prefix):]
                if not raw_name or raw_name in by_raw_name:
                    raise AgentRuntimeError(
                        "mcp_tool_name_conflict",
                        "An MCP Connection published duplicate or empty Tool names.",
                        status_code=409,
                    )
                by_raw_name[raw_name] = tool
            requirement_id = requirement_by_namespace[namespace]
            servers[requirement_id] = _DiscoveredServer(
                requirement_id=requirement_id,
                namespace=namespace,
                tools=by_raw_name,
            )

        runtime = cls(client, servers)
        for item in references:
            runtime.tools_for((item,))
        return runtime

    def tools_for(
        self,
        references: Iterable[ResolvedMcpReference],
    ) -> tuple[BaseTool, ...]:
        selected: list[BaseTool] = []
        for item in references:
            requirement_id = str(item.requirement.get("id", ""))
            server = self.__servers.get(requirement_id)
            if server is None:
                raise AgentRuntimeError(
                    "mcp_requirement_unavailable",
                    "An attached MCP requirement is unavailable in this Workflow Run.",
                    status_code=409,
                )
            reference = McpReference.model_validate(item.reference)
            selected.extend(_selection_tools(reference, server.tools))
        return tuple(selected)

    def commands_for(
        self,
        references: Iterable[ResolvedMcpReference],
    ) -> "McpCommands":
        allowed: dict[str, tuple[_DiscoveredServer, tuple[BaseTool, ...]]] = {}
        for item in references:
            requirement_id = str(item.requirement.get("id", ""))
            server = self.__servers[requirement_id]
            reference = McpReference.model_validate(item.reference)
            allowed[server.namespace] = (
                server,
                _selection_tools(reference, server.tools),
            )
        return McpCommands(self, allowed)

    async def _resources(
        self,
        namespace: str,
        *,
        uris: str | list[str] | None = None,
    ) -> list[Any]:
        return await self.__client.get_resources(namespace, uris=uris)

    async def _prompt(
        self,
        namespace: str,
        prompt_name: str,
        *,
        arguments: dict[str, Any] | None = None,
    ) -> list[Any]:
        return await self.__client.get_prompt(
            namespace,
            prompt_name,
            arguments=arguments,
        )


class McpCommands:
    """Command-facing MCP facade restricted to one Command component's refs."""

    def __init__(
        self,
        runtime: McpRunRuntime,
        allowed: Mapping[str, tuple[_DiscoveredServer, tuple[BaseTool, ...]]],
    ) -> None:
        self.__runtime = runtime
        self.__allowed = dict(allowed)

    def available_tools(self) -> dict[str, tuple[str, ...]]:
        return {
            namespace: tuple(
                str(tool.name)[len(namespace) + 1:]
                for tool in tools
            )
            for namespace, (_server, tools) in self.__allowed.items()
        }

    def _server(self, namespace: str) -> _DiscoveredServer:
        value = self.__allowed.get(namespace)
        if value is None:
            raise ValueError(f"MCP namespace is not attached to this Command: {namespace}")
        return value[0]

    async def call_tool(
        self,
        namespace: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        server, tools = self.__allowed.get(namespace, (None, ()))
        if server is None:
            raise ValueError(f"MCP namespace is not attached to this Command: {namespace}")
        visible_name = f"{namespace}_{tool_name}"
        tool = next((item for item in tools if item.name == visible_name), None)
        if tool is None:
            raise ValueError(
                f"MCP Tool is not selected for this Command: {namespace}.{tool_name}"
            )
        return await tool.ainvoke(
            {
                "type": "tool_call",
                "name": visible_name,
                "args": arguments or {},
                "id": f"mcp-command-{uuid4()}",
            }
        )

    async def get_resources(
        self,
        namespace: str,
        *,
        uris: str | list[str] | None = None,
    ) -> list[Any]:
        self._server(namespace)
        return await self.__runtime._resources(namespace, uris=uris)

    async def get_prompt(
        self,
        namespace: str,
        prompt_name: str,
        *,
        arguments: dict[str, Any] | None = None,
    ) -> list[Any]:
        self._server(namespace)
        return await self.__runtime._prompt(
            namespace,
            prompt_name,
            arguments=arguments,
        )


__all__ = ["McpCommands", "McpRunRuntime"]
