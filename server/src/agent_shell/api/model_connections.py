from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from agent_shell.http_surface import management_api_router
from agent_shell.api.errors import management_error
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.model_connections import (
    ModelConnectionNameConflictError,
    ModelResourceStore,
)
from agent_shell.configuration.identity import new_configuration_id


def build_model_connection_router(
    configuration: FileConfigRepository,
    block_store: BlockStore,
    resources: ModelResourceStore,
) -> APIRouter:
    router = management_api_router()

    def connection_or_404(connection_id: str) -> dict[str, Any]:
        value = resources.get_connection(connection_id)
        if value is None:
            raise management_error(
                404,
                code="model_connection_not_found",
                message_key="errors.modelConnectionNotFound",
                message="The model connection does not exist.",
            )
        return value

    def save_connection(connection_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return resources.save_connection(connection_id, payload)
        except ModelConnectionNameConflictError as exc:
            raise management_error(
                409,
                code="model_connection_name_conflict",
                message_key="errors.modelConnectionNameConflict",
                message="A model connection with this name already exists.",
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise management_error(
                422,
                code="model_connection_invalid",
                message_key="errors.modelConnectionInvalid",
                message="The model connection is invalid.",
            ) from exc

    def requirement_projection(requirement: dict[str, Any]) -> dict[str, Any]:
        connection_id = resources.get_binding(configuration.repository_id, str(requirement["id"]))
        return {
            **requirement,
            "binding": connection_id,
            "connection": resources.get_connection(connection_id) if connection_id else None,
        }

    @router.get("/model-connections")
    def list_model_connections() -> list[dict[str, Any]]:
        return resources.list_connections()

    @router.get("/model-connections/{connection_id}")
    def get_model_connection(connection_id: str) -> dict[str, Any]:
        return connection_or_404(connection_id)

    @router.post("/model-connections")
    def create_model_connection(payload: dict[str, Any]) -> dict[str, Any]:
        return save_connection(new_configuration_id(), payload)

    @router.put("/model-connections/{connection_id}")
    def update_model_connection(connection_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        connection_or_404(connection_id)
        return save_connection(connection_id, payload)

    @router.post("/model-connections/{connection_id}/copy")
    def copy_model_connection(connection_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        connection_or_404(connection_id)
        if set(payload) != {"name"} or not isinstance(payload.get("name"), str) or not payload["name"].strip():
            raise management_error(422, code="invalid_copy_request", message_key="errors.copyRequestInvalid", message="The copy request must contain a name.")
        name = payload["name"].strip()
        try:
            return resources.copy_connection(connection_id, name)
        except ModelConnectionNameConflictError as exc:
            raise management_error(
                409,
                code="model_connection_name_conflict",
                message_key="errors.modelConnectionNameConflict",
                message="A model connection with this name already exists.",
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise management_error(
                422,
                code="model_connection_invalid",
                message_key="errors.modelConnectionInvalid",
                message="The model connection is invalid.",
            ) from exc

    @router.delete("/model-connections/{connection_id}")
    def delete_model_connection(connection_id: str) -> dict[str, bool]:
        if not resources.delete_connection(connection_id):
            raise management_error(
                404,
                code="model_connection_not_found",
                message_key="errors.modelConnectionNotFound",
                message="The model connection does not exist.",
            )
        return {"ok": True}

    @router.get("/model-requirements")
    def list_model_requirements() -> list[dict[str, Any]]:
        requirements = block_store.list_blocks("model-requirement")
        return [requirement_projection(item) for item in requirements]

    @router.put("/model-requirements/{requirement_id}/binding")
    def bind_model_requirement(requirement_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        requirement = block_store.get_block("model-requirement", requirement_id)
        if requirement is None:
            raise management_error(
                404,
                code="model_requirement_not_found",
                message_key="errors.modelRequirementNotFound",
                message="The model requirement does not exist.",
            )
        if set(payload) != {"connection_id"}:
            raise management_error(422, code="model_binding_invalid", message_key="errors.modelBindingInvalid", message="The model binding must contain only connection_id.")
        connection_id = payload["connection_id"]
        if connection_id is not None and not isinstance(connection_id, str):
            raise management_error(422, code="model_binding_invalid", message_key="errors.modelBindingInvalid", message="The model binding is invalid.")
        if connection_id is not None:
            connection_or_404(connection_id)
        try:
            resources.set_binding(configuration.repository_id, requirement_id, connection_id)
        except KeyError as exc:
            raise management_error(
                404,
                code="model_connection_not_found",
                message_key="errors.modelConnectionNotFound",
                message="The model connection does not exist.",
            ) from exc
        return requirement_projection(requirement)

    return router
