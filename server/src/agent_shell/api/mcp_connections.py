from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import ValidationError

from agent_shell.api.errors import management_error
from agent_shell.configuration.identity import new_configuration_id
from agent_shell.mcp.importing import (
    mcp_import_preview,
    normalize_mcp_servers_import,
)
from agent_shell.mcp.installation import McpInstallationError
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.mcp_connections import (
    McpConnectionNameConflictError,
    McpResourceStore,
)


def build_mcp_connection_router(
    configuration: FileConfigRepository,
    block_store: BlockStore,
    resources: McpResourceStore,
) -> APIRouter:
    router = APIRouter()

    def connection_or_404(connection_id: str) -> dict[str, Any]:
        value = resources.get_connection(connection_id)
        if value is None:
            raise management_error(
                404,
                code="mcp_connection_not_found",
                message_key="errors.mcpConnectionNotFound",
                message="The MCP Connection does not exist.",
            )
        return value

    def invalid_connection(exc: Exception):
        return management_error(
            422,
            code="mcp_connection_invalid",
            message_key="errors.mcpConnectionInvalid",
            message="The MCP Connection is invalid.",
        )

    def save_connection(connection_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return resources.save_connection(connection_id, payload)
        except McpConnectionNameConflictError as exc:
            raise management_error(
                409,
                code="mcp_connection_name_conflict",
                message_key="errors.mcpConnectionNameConflict",
                message="An MCP Connection with this name already exists.",
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise invalid_connection(exc) from exc

    def requirement_projection(requirement: dict[str, Any]) -> dict[str, Any]:
        connection_id = resources.get_binding(
            configuration.repository_id,
            str(requirement["id"]),
        )
        return {
            **requirement,
            "binding": connection_id,
            "connection": resources.get_connection(connection_id) if connection_id else None,
        }

    @router.get("/api/mcp-connections")
    async def list_mcp_connections() -> list[dict[str, Any]]:
        return resources.list_connections()

    @router.post("/api/mcp-connections/import/preview")
    async def preview_mcp_connections_import(payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != {"document"}:
            raise management_error(
                422,
                code="mcp_import_invalid",
                message_key="errors.mcpImportInvalid",
                message="The MCP import request must contain only document.",
            )
        try:
            return mcp_import_preview(payload["document"])
        except (ValidationError, ValueError) as exc:
            raise management_error(
                422,
                code="mcp_import_invalid",
                message_key="errors.mcpImportInvalid",
                message="The MCP import document is invalid or unsupported.",
            ) from exc

    @router.post("/api/mcp-connections/import")
    async def import_mcp_connections(payload: dict[str, Any]) -> list[dict[str, Any]]:
        if set(payload).difference({"document", "value_sources"}) or "document" not in payload:
            raise management_error(
                422,
                code="mcp_import_invalid",
                message_key="errors.mcpImportInvalid",
                message="The MCP import request is invalid.",
            )
        try:
            connections = normalize_mcp_servers_import(
                payload["document"],
                value_sources=payload.get("value_sources"),
            )
            return resources.save_connections_atomic(
                [(new_configuration_id(), connection) for connection in connections]
            )
        except McpConnectionNameConflictError as exc:
            raise management_error(
                409,
                code="mcp_connection_name_conflict",
                message_key="errors.mcpConnectionNameConflict",
                message="An imported MCP Connection name already exists.",
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise management_error(
                422,
                code="mcp_import_invalid",
                message_key="errors.mcpImportInvalid",
                message="The MCP import document is invalid or unsupported.",
            ) from exc

    @router.get("/api/mcp-connections/{connection_id}")
    async def get_mcp_connection(connection_id: str) -> dict[str, Any]:
        return connection_or_404(connection_id)

    @router.post("/api/mcp-connections/{connection_id}/install")
    async def install_mcp_connection(connection_id: str) -> dict[str, Any]:
        connection = connection_or_404(connection_id)
        if connection.get("transport") != "stdio":
            raise management_error(
                422,
                code="mcp_installation_not_applicable",
                message_key="errors.mcpInstallationNotApplicable",
                message="Remote HTTP MCP connections do not require local installation.",
            )
        try:
            await run_in_threadpool(
                resources.install_connection,
                connection_id,
            )
            resolved = resources.resolve_connection(connection_id)
            client = MultiServerMCPClient({"installation_test": resolved})
            tools = await client.get_tools(server_name="installation_test")
        except McpInstallationError as exc:
            raise management_error(
                409,
                code=exc.code,
                message_key="errors.mcpInstallationFailed",
                message="The managed local MCP package could not be installed.",
            ) from exc
        except Exception as exc:
            raise management_error(
                502,
                code="mcp_connection_test_failed",
                message_key="errors.mcpConnectionTestFailed",
                message="The installed MCP Server could not complete Tool discovery.",
            ) from exc
        return {
            "connection": resources.get_connection(connection_id),
            "tools": [str(tool.name) for tool in tools],
        }

    @router.post("/api/mcp-connections")
    async def create_mcp_connection(payload: dict[str, Any]) -> dict[str, Any]:
        return save_connection(new_configuration_id(), payload)

    @router.put("/api/mcp-connections/{connection_id}")
    async def update_mcp_connection(connection_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        connection_or_404(connection_id)
        return save_connection(connection_id, payload)

    @router.post("/api/mcp-connections/{connection_id}/copy")
    async def copy_mcp_connection(connection_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        connection_or_404(connection_id)
        if set(payload) != {"name"} or not isinstance(payload.get("name"), str) or not payload["name"].strip():
            raise management_error(
                422,
                code="invalid_copy_request",
                message_key="errors.copyRequestInvalid",
                message="The copy request must contain a name.",
            )
        try:
            return resources.copy_connection(connection_id, payload["name"].strip())
        except McpConnectionNameConflictError as exc:
            raise management_error(
                409,
                code="mcp_connection_name_conflict",
                message_key="errors.mcpConnectionNameConflict",
                message="An MCP Connection with this name already exists.",
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise invalid_connection(exc) from exc

    @router.delete("/api/mcp-connections/{connection_id}")
    async def delete_mcp_connection(connection_id: str) -> dict[str, bool]:
        if not resources.delete_connection(connection_id):
            raise management_error(
                404,
                code="mcp_connection_not_found",
                message_key="errors.mcpConnectionNotFound",
                message="The MCP Connection does not exist.",
            )
        return {"ok": True}

    @router.get("/api/mcp-requirements")
    async def list_mcp_requirements() -> list[dict[str, Any]]:
        return [
            requirement_projection(item)
            for item in block_store.list_blocks("mcp-requirement")
        ]

    @router.put("/api/mcp-requirements/{requirement_id}/binding")
    async def bind_mcp_requirement(requirement_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        requirement = block_store.get_block("mcp-requirement", requirement_id)
        if requirement is None:
            raise management_error(
                404,
                code="mcp_requirement_not_found",
                message_key="errors.mcpRequirementNotFound",
                message="The MCP Requirement does not exist.",
            )
        if set(payload) != {"connection_id"} or (
            payload.get("connection_id") is not None
            and not isinstance(payload.get("connection_id"), str)
        ):
            raise management_error(
                422,
                code="mcp_binding_invalid",
                message_key="errors.mcpBindingInvalid",
                message="The MCP binding must contain only connection_id.",
            )
        connection_id = payload["connection_id"]
        if connection_id is not None:
            connection_or_404(connection_id)
        try:
            resources.set_binding(
                configuration.repository_id,
                requirement_id,
                connection_id,
            )
        except KeyError as exc:
            raise management_error(
                404,
                code="mcp_connection_not_found",
                message_key="errors.mcpConnectionNotFound",
                message="The MCP Connection does not exist.",
            ) from exc
        return requirement_projection(requirement)

    return router


__all__ = ["build_mcp_connection_router"]
