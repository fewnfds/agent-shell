from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_shell.http_surface import management_api_router
from agent_shell.api.errors import management_error
from agent_shell.api.configuration_collections import (
    configuration_collection,
    configuration_collection_requested,
    matches_configuration_query,
)
from agent_shell.storage.agent_configs import AgentConfigStore
from agent_shell.storage.workflows import WorkflowStore
from agent_shell.configuration.identity import name_collision_key
from agent_shell.validation.models import ValidationReport, validation_failure_detail
from agent_shell.validation.service import ConfigurationValidationService


MAIN_AGENT_TABLE = "main_agents"
SUBAGENT_TABLE = "subagents"


class ConfigurationBulkDelete(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ids: list[str] | None = Field(default=None, min_length=1)
    q: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def select_ids_or_query(self) -> "ConfigurationBulkDelete":
        if (self.ids is None) == (self.q is None):
            raise ValueError("exactly one of ids or q is required")
        return self


def _raise_if_invalid(report: ValidationReport) -> None:
    if not report.valid:
        raise HTTPException(
            status_code=422,
            detail=validation_failure_detail(report),
        )


def _copy_name(payload: dict) -> str:
    if set(payload) != {"name"} or not isinstance(payload.get("name"), str):
        raise management_error(
            422,
            code="invalid_copy_request",
            message_key="errors.copyRequestInvalid",
            message="The copy request must contain only a configuration name.",
        )
    name = payload["name"].strip()
    if not name:
        raise management_error(
            422,
            code="configuration_name_required",
            message_key="errors.configurationNameRequired",
            message="The configuration name is required.",
        )
    return name


def _copy_component_name(payload: dict) -> str:
    if set(payload) != {"component_name"} or not isinstance(
        payload.get("component_name"), str
    ):
        raise management_error(
            422,
            code="invalid_copy_request",
            message_key="errors.copyRequestInvalid",
            message="The copy request must contain only a component name.",
        )
    component_name = payload["component_name"].strip()
    if not component_name:
        raise management_error(
            422,
            code="configuration_name_required",
            message_key="errors.configurationNameRequired",
            message="The component name is required.",
        )
    return component_name

def build_agent_config_router(
    config_store: AgentConfigStore,
    validation: ConfigurationValidationService,
    workflows: WorkflowStore | None = None,
) -> APIRouter:
    router = management_api_router()

    def reject_model_conflict(candidate: dict) -> None:
        if workflows is None or not candidate.get("is_model_entry"):
            return
        candidate_name = name_collision_key(str(candidate["name"]))
        conflict = any(
            workflow.get("is_model_entry")
            and name_collision_key(str(workflow["name"])) == candidate_name
            for workflow in workflows.list_items(enabled_only=True)
        )
        if conflict:
            raise management_error(
                409,
                code="model_name_conflict",
                message_key="errors.modelNameConflict",
                message="A model entry with this name already exists.",
            )

    @router.get("/main-agents")
    def list_main_agents(
        request: Request,
        view: Literal["full", "summary"] = "full",
        q: str | None = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int | None, Query(ge=1)] = None,
    ) -> list[dict] | dict:
        if not configuration_collection_requested(request.query_params):
            return config_store.list_items(MAIN_AGENT_TABLE)
        items = (
            config_store.list_items(MAIN_AGENT_TABLE)
            if view == "full"
            else config_store.list_item_summaries(MAIN_AGENT_TABLE)
        )
        return configuration_collection(
            items,
            repository_context=config_store.repository_context(),
            query=q,
            search_fields=("name", "id"),
            offset=offset,
            limit=limit,
        )

    @router.post("/main-agents/delete")
    def delete_main_agents(
        payload: ConfigurationBulkDelete,
    ) -> dict[str, int]:
        mutation_repository_id = config_store.repository_id()
        ids = (
            list(dict.fromkeys(payload.ids))
            if payload.ids is not None
            else [
                str(item["id"])
                for item in config_store.list_item_summaries(MAIN_AGENT_TABLE)
                if matches_configuration_query(item, payload.q or "", ("name", "id"))
            ]
        )
        if any(config_store.get_item(MAIN_AGENT_TABLE, item_id) is None for item_id in ids):
            raise management_error(
                404,
                code="main_agent_not_found",
                message_key="errors.mainAgentNotFound",
                message="A Main Agent configuration does not exist.",
            )
        return {
            "deleted": config_store.delete_items(
                MAIN_AGENT_TABLE,
                ids,
                expected_repository_id=mutation_repository_id,
            )
        }

    @router.get("/main-agents/{item_id}")
    def get_main_agent(item_id: str) -> dict:
        item = config_store.get_item(MAIN_AGENT_TABLE, item_id)
        if item is None:
            raise management_error(
                404,
                code="main_agent_not_found",
                message_key="errors.mainAgentNotFound",
                message="The Main Agent configuration does not exist.",
            )
        return item

    @router.post("/main-agents")
    def create_main_agent(payload: dict) -> dict:
        mutation_repository_id = config_store.repository_id()
        report, validated, _ = validation.validate_main_agent(
            payload,
            stage="main_agent_save",
        )
        _raise_if_invalid(report)
        assert validated is not None
        reject_model_conflict(validated)
        item_id = config_store.new_id()
        try:
            config_store.save_item(
                MAIN_AGENT_TABLE,
                item_id,
                validated,
                expected_repository_id=mutation_repository_id,
            )
        except ValueError as exc:
            raise management_error(
                409,
                code="configuration_name_conflict",
                message_key="errors.configurationNameConflict",
                message="A configuration with this name already exists.",
            ) from exc
        return config_store.get_item(MAIN_AGENT_TABLE, item_id)

    @router.post("/main-agents/{item_id}/copy")
    def copy_main_agent(item_id: str, payload: dict) -> dict:
        mutation_repository_id = config_store.repository_id()
        name = _copy_name(payload)
        source = config_store.get_item(MAIN_AGENT_TABLE, item_id)
        if source is None:
            raise management_error(
                404,
                code="main_agent_not_found",
                message_key="errors.mainAgentNotFound",
                message="The Main Agent configuration does not exist.",
            )
        candidate = dict(source)
        candidate["name"] = name
        report, validated, _ = validation.validate_main_agent(
            candidate,
            stage="main_agent_copy",
            owner_id=item_id,
            stored=True,
        )
        _raise_if_invalid(report)
        assert validated is not None
        reject_model_conflict(validated)
        copy_id = config_store.new_id()
        try:
            config_store.save_item(
                MAIN_AGENT_TABLE,
                copy_id,
                validated,
                expected_repository_id=mutation_repository_id,
            )
        except ValueError as exc:
            raise management_error(
                409,
                code="configuration_name_conflict",
                message_key="errors.configurationNameConflict",
                message="A configuration with this name already exists.",
            ) from exc
        return config_store.get_item(MAIN_AGENT_TABLE, copy_id)

    @router.put("/main-agents/{item_id}")
    def update_main_agent(item_id: str, payload: dict) -> dict:
        mutation_repository_id = config_store.repository_id()
        if config_store.get_item(MAIN_AGENT_TABLE, item_id) is None:
            raise management_error(
                404,
                code="main_agent_not_found",
                message_key="errors.mainAgentNotFound",
                message="The Main Agent configuration does not exist.",
            )
        report, validated, _ = validation.validate_main_agent(
            payload,
            stage="main_agent_save",
            owner_id=item_id,
        )
        _raise_if_invalid(report)
        assert validated is not None
        reject_model_conflict(validated)
        try:
            config_store.save_item(
                MAIN_AGENT_TABLE,
                item_id,
                validated,
                expected_repository_id=mutation_repository_id,
            )
        except ValueError as exc:
            raise management_error(
                409,
                code="configuration_name_conflict",
                message_key="errors.configurationNameConflict",
                message="A configuration with this name already exists.",
            ) from exc
        return config_store.get_item(MAIN_AGENT_TABLE, item_id)

    @router.delete("/main-agents/{item_id}")
    def delete_main_agent(item_id: str) -> dict[str, bool]:
        mutation_repository_id = config_store.repository_id()
        if config_store.get_item(MAIN_AGENT_TABLE, item_id) is None:
            raise management_error(
                404,
                code="main_agent_not_found",
                message_key="errors.mainAgentNotFound",
                message="The Main Agent configuration does not exist.",
            )
        config_store.delete_item(
            MAIN_AGENT_TABLE,
            item_id,
            expected_repository_id=mutation_repository_id,
        )
        return {"ok": True}

    @router.get("/subagents")
    def list_subagents(
        request: Request,
        view: Literal["full", "summary"] = "full",
        q: str | None = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int | None, Query(ge=1)] = None,
    ) -> list[dict] | dict:
        if not configuration_collection_requested(request.query_params):
            return config_store.list_items(SUBAGENT_TABLE)
        items = (
            config_store.list_items(SUBAGENT_TABLE)
            if view == "full"
            else config_store.list_item_summaries(SUBAGENT_TABLE)
        )
        return configuration_collection(
            items,
            repository_context=config_store.repository_context(),
            query=q,
            search_fields=("component_name", "name", "description", "id"),
            offset=offset,
            limit=limit,
        )

    @router.post("/subagents/delete")
    def delete_subagents(
        payload: ConfigurationBulkDelete,
    ) -> dict[str, int]:
        mutation_repository_id = config_store.repository_id()
        ids = (
            list(dict.fromkeys(payload.ids))
            if payload.ids is not None
            else [
                str(item["id"])
                for item in config_store.list_item_summaries(SUBAGENT_TABLE)
                if matches_configuration_query(
                    item,
                    payload.q or "",
                    ("component_name", "name", "description", "id"),
                )
            ]
        )
        for item_id in ids:
            if config_store.get_item(SUBAGENT_TABLE, item_id) is None:
                raise management_error(
                    404,
                    code="subagent_not_found",
                    message_key="errors.subagentNotFound",
                    message="A Subagent entity does not exist.",
                )
        return {
            "deleted": config_store.delete_items(
                SUBAGENT_TABLE,
                ids,
                expected_repository_id=mutation_repository_id,
            )
        }

    @router.get("/subagents/{item_id}")
    def get_subagent(item_id: str) -> dict:
        item = config_store.get_item(SUBAGENT_TABLE, item_id)
        if item is None:
            raise management_error(
                404,
                code="subagent_not_found",
                message_key="errors.subagentNotFound",
                message="The Subagent entity does not exist.",
            )
        return item

    @router.post("/subagents")
    def create_subagent(payload: dict) -> dict:
        mutation_repository_id = config_store.repository_id()
        report, validated = validation.validate_subagent(
            payload,
            stage="subagent_save",
        )
        _raise_if_invalid(report)
        assert validated is not None
        item_id = config_store.new_id()
        try:
            config_store.save_item(
                SUBAGENT_TABLE,
                item_id,
                validated,
                expected_repository_id=mutation_repository_id,
            )
        except ValueError as exc:
            raise management_error(
                409,
                code="configuration_name_conflict",
                message_key="errors.configurationNameConflict",
                message="A configuration with this name already exists.",
            ) from exc
        return config_store.get_item(SUBAGENT_TABLE, item_id)

    @router.post("/subagents/{item_id}/copy")
    def copy_subagent(item_id: str, payload: dict) -> dict:
        mutation_repository_id = config_store.repository_id()
        component_name = _copy_component_name(payload)
        source = config_store.get_item(SUBAGENT_TABLE, item_id)
        if source is None:
            raise management_error(
                404,
                code="subagent_not_found",
                message_key="errors.subagentNotFound",
                message="The Subagent entity does not exist.",
            )
        candidate = dict(source)
        candidate["component_name"] = component_name
        report, validated = validation.validate_subagent(
            candidate,
            stage="subagent_copy",
            stored=True,
        )
        _raise_if_invalid(report)
        assert validated is not None
        copy_id = config_store.new_id()
        try:
            config_store.save_item(
                SUBAGENT_TABLE,
                copy_id,
                validated,
                expected_repository_id=mutation_repository_id,
            )
        except ValueError as exc:
            raise management_error(
                409,
                code="configuration_name_conflict",
                message_key="errors.configurationNameConflict",
                message="A configuration with this name already exists.",
            ) from exc
        return config_store.get_item(SUBAGENT_TABLE, copy_id)

    @router.put("/subagents/{item_id}")
    def update_subagent(item_id: str, payload: dict) -> dict:
        mutation_repository_id = config_store.repository_id()
        if config_store.get_item(SUBAGENT_TABLE, item_id) is None:
            raise management_error(
                404,
                code="subagent_not_found",
                message_key="errors.subagentNotFound",
                message="The Subagent entity does not exist.",
            )
        report, validated = validation.validate_subagent(
            payload,
            stage="subagent_save",
            owner_id=item_id,
        )
        _raise_if_invalid(report)
        assert validated is not None
        try:
            config_store.save_item(
                SUBAGENT_TABLE,
                item_id,
                validated,
                expected_repository_id=mutation_repository_id,
            )
        except ValueError as exc:
            raise management_error(
                409,
                code="configuration_name_conflict",
                message_key="errors.configurationNameConflict",
                message="A configuration with this name already exists.",
            ) from exc
        return config_store.get_item(SUBAGENT_TABLE, item_id)

    @router.delete("/subagents/{item_id}")
    def delete_subagent(item_id: str) -> dict[str, bool]:
        mutation_repository_id = config_store.repository_id()
        if config_store.get_item(SUBAGENT_TABLE, item_id) is None:
            raise management_error(
                404,
                code="subagent_not_found",
                message_key="errors.subagentNotFound",
                message="The Subagent entity does not exist.",
            )
        config_store.delete_item(
            SUBAGENT_TABLE,
            item_id,
            expected_repository_id=mutation_repository_id,
        )
        return {"ok": True}

    return router
