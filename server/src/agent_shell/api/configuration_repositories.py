from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from agent_shell.http_surface import management_api_router
from agent_shell.configuration.identity import ConfigurationName
from agent_shell.api.errors import management_error
from agent_shell.mcp_tools.publication import McpToolPublicationService
from agent_shell.configuration.repository_management import (
    ConfigurationRepositoryManagementService,
)
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.file_config import ActiveRepositoryDeleteError
from agent_shell.validation.models import ValidationReport
from agent_shell.validation.repository import RepositoryValidationService


class RepositoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ConfigurationName


class RepositoryCopy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ConfigurationName


def build_configuration_repository_router(
    repository: FileConfigRepository,
    management: ConfigurationRepositoryManagementService,
    validation: RepositoryValidationService,
    mcp_tool_publication: McpToolPublicationService,
) -> APIRouter:
    router = management_api_router()

    @router.get("/configuration-repositories")
    def list_repositories() -> dict[str, object]:
        return {
            "active_id": repository.repository_id,
            "repositories": repository.list_repositories(),
        }

    @router.post("/configuration-repositories")
    def create_repository(payload: RepositoryCreate) -> dict[str, object]:
        try:
            return repository.create_repository(payload.name)
        except ValueError as exc:
            raise management_error(
                409,
                code="configuration_repository_conflict",
                message_key="errors.configurationRepositoryConflict",
                message=str(exc),
            ) from exc

    @router.post("/configuration-repositories/{repository_id}/activate")
    async def activate_repository(repository_id: str) -> dict[str, object]:
        def activate() -> tuple[dict[str, object], ValidationReport]:
            try:
                active = repository.switch_repository(repository_id)
            except ValueError as exc:
                raise management_error(
                    422,
                    code="configuration_repository_invalid",
                    message_key="errors.configurationRepositoryInvalid",
                    message=str(exc),
                ) from exc
            return active, validation.validate_repository()

        active, report = await asyncio.to_thread(activate)
        try:
            await mcp_tool_publication.reconcile(include_empty=True)
        except Exception as exc:
            raise management_error(
                502,
                code="mcp_tool_publication_failed",
                message_key="errors.mcpToolPublicationFailed",
                message=(
                    "The published MCP Tool Assistants could not be "
                    "synchronized."
                ),
            ) from exc
        return {
            **active,
            "restart_required": management.active_repository_restart_required(),
            "validation": report.as_dict(),
        }

    @router.post("/configuration-repositories/{repository_id}/copy")
    def copy_repository(
        repository_id: str,
        payload: RepositoryCopy,
    ) -> dict[str, object]:
        try:
            return management.copy(repository_id, payload.name)
        except ValueError as exc:
            raise management_error(
                409,
                code="configuration_repository_conflict",
                message_key="errors.configurationRepositoryConflict",
                message=str(exc),
            ) from exc

    @router.get("/configuration-repositories/{repository_id}/download")
    def download_repository(repository_id: str) -> Response:
        try:
            content, filename = management.export(repository_id)
        except ValueError as exc:
            raise management_error(
                404,
                code="configuration_repository_not_found",
                message_key="errors.configurationRepositoryNotFound",
                message=str(exc),
            ) from exc
        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    @router.delete("/configuration-repositories/{repository_id}")
    def delete_repository(repository_id: str) -> dict[str, bool]:
        try:
            management.delete(repository_id)
        except ActiveRepositoryDeleteError as exc:
            raise management_error(
                409,
                code="active_configuration_repository_delete_forbidden",
                message_key="errors.activeConfigurationRepositoryDeleteForbidden",
                message=str(exc),
            ) from exc
        except ValueError as exc:
            raise management_error(
                404,
                code="configuration_repository_not_found",
                message_key="errors.configurationRepositoryNotFound",
                message=str(exc),
            ) from exc
        return {"ok": True}

    return router


__all__ = ["build_configuration_repository_router"]
