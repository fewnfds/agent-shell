from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_shell.api.errors import management_error
from agent_shell.contracts import MANAGED_COMPONENT_MODELS, ModelConnectionBlock
from agent_shell.storage.validation_settings import (
    MIN_VALIDATION_DEBOUNCE_MS,
    ConfigurationValidationSettingsStore,
)
from agent_shell.validation.service import ConfigurationValidationService
from agent_shell.validation.repository import RepositoryValidationService
from agent_shell.validation import report_from_validation_error
from agent_shell.validation.models import ValidationReport


class DraftValidationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["block", "main_agent", "model_connection", "subagent"]
    type: str = ""
    id: str = ""


class DraftValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: DraftValidationTarget
    payload: dict[str, Any]


class ConfigurationValidationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    debounce_ms: int = Field(
        ge=MIN_VALIDATION_DEBOUNCE_MS,
    )


def build_validation_router(
    validation: ConfigurationValidationService,
    repository_validation: RepositoryValidationService,
    settings: ConfigurationValidationSettingsStore,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/validation/repository")
    async def validate_repository() -> dict[str, object]:
        return repository_validation.validate_repository().as_dict()

    @router.get("/api/validation/settings")
    async def get_validation_settings() -> dict[str, int]:
        return settings.snapshot()

    @router.put("/api/validation/settings")
    async def update_validation_settings(
        payload: ConfigurationValidationSettingsUpdate,
    ) -> dict[str, int]:
        return settings.update(payload.debounce_ms)

    @router.post("/api/validation/draft")
    async def validate_draft(request: DraftValidationRequest) -> dict[str, object]:
        target = request.target
        if target.kind == "block":
            if target.type not in MANAGED_COMPONENT_MODELS:
                raise management_error(
                    422,
                    code="unknown_configuration_type",
                    message_key="errors.unknownConfigurationType",
                    message="The requested configuration type is not supported.",
                    message_args={"type": target.type},
                )
            report, _ = validation.validate_block(
                target.type,
                request.payload,
                stage="draft_validation",
                owner_id=target.id,
            )
        elif target.kind == "main_agent":
            report, _, _ = validation.validate_main_agent(
                request.payload,
                stage="draft_validation",
                owner_id=target.id,
            )
        elif target.kind == "subagent":
            report, _ = validation.validate_subagent(
                request.payload,
                stage="draft_validation",
                owner_id=target.id,
            )
        else:
            try:
                ModelConnectionBlock.model_validate(request.payload)
            except ValidationError as exc:
                report = report_from_validation_error(
                    exc,
                    stage="draft_validation",
                    scope="model_connection",
                    owner_id=target.id,
                    owner_name=str(request.payload.get("name", "")),
                )
            else:
                report = ValidationReport(stage="draft_validation")
        return report.as_dict()

    return router
