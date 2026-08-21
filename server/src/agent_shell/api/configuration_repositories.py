from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from agent_shell.api.errors import management_error
from agent_shell.python_packages.dependencies import (
    dependency_metadata,
    read_package_requirements,
)
from agent_shell.registries.errors import ResourceScanError
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.validation.repository import RepositoryValidationService


class RepositoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)


def _restart_required(packages_root: Path, runtime_root: Path) -> bool:
    if not packages_root.exists():
        return False
    for adapter in packages_root.iterdir():
        if not adapter.is_dir():
            continue
        for folder in adapter.iterdir():
            if not folder.is_dir():
                continue
            try:
                requirements = read_package_requirements(folder)
            except ResourceScanError:
                continue
            metadata = dependency_metadata(folder.name, requirements, runtime_root)
            if metadata["dependency_status"] == "restart_required":
                return True
    return False


def build_configuration_repository_router(
    repository: FileConfigRepository,
    validation: RepositoryValidationService,
    *,
    runtime_root: Path,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/configuration-repositories")
    async def list_repositories() -> dict[str, object]:
        return {
            "active_id": repository.repository_id,
            "repositories": repository.list_repositories(),
        }

    @router.post("/api/configuration-repositories")
    async def create_repository(payload: RepositoryCreate) -> dict[str, object]:
        try:
            return repository.create_repository(payload.name)
        except ValueError as exc:
            raise management_error(
                409,
                code="configuration_repository_conflict",
                message_key="errors.configurationRepositoryConflict",
                message=str(exc),
            ) from exc

    @router.post("/api/configuration-repositories/{repository_id}/activate")
    async def activate_repository(repository_id: str) -> dict[str, object]:
        try:
            active = repository.switch_repository(repository_id)
        except ValueError as exc:
            raise management_error(
                422,
                code="configuration_repository_invalid",
                message_key="errors.configurationRepositoryInvalid",
                message=str(exc),
            ) from exc
        report = validation.validate_repository()
        return {
            **active,
            "restart_required": _restart_required(
                repository.python_package_instances_root, runtime_root
            ),
            "validation": report.as_dict(),
        }

    return router


__all__ = ["build_configuration_repository_router"]
