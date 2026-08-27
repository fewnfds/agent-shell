from __future__ import annotations

from typing import Literal, NoReturn

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from agent_shell.api.errors import management_error
from agent_shell.storage.runtime_policy import RuntimePolicyStore
from agent_shell.system_settings import SystemSettingsError, SystemSettingsService


class ManagementPasswordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["preserve", "replace"]
    value: str | None = None

    @model_validator(mode="after")
    def validate_value(self) -> "ManagementPasswordUpdate":
        if self.operation == "replace" and not self.value:
            raise ValueError("replace requires a value")
        if self.operation != "replace" and self.value is not None:
            raise ValueError("value is accepted only for replace")
        return self


class OptionalSecretUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["keep", "replace", "clear"]
    value: SecretStr | None = None

    @model_validator(mode="after")
    def validate_value(self) -> "OptionalSecretUpdate":
        if self.operation == "replace" and (
            self.value is None or not self.value.get_secret_value()
        ):
            raise ValueError("replace requires a value")
        if self.operation != "replace" and self.value is not None:
            raise ValueError("value is accepted only for replace")
        return self


class SystemSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int
    allow_remote: bool
    langsmith_tracing_enabled: bool
    langsmith_endpoint: str
    langsmith_project: str
    langsmith_workspace_id: str | None = None
    langsmith_api_key: OptionalSecretUpdate
    management_token: ManagementPasswordUpdate
    cors_origins: list[str]
    trusted_proxy_cidrs: list[str]


class RuntimePolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_debug_capture_enabled: bool = Field(strict=True)
    chat_completion_body_bytes: int = Field(strict=True, ge=1)
    content_blocks: int = Field(strict=True, ge=1)
    decoded_block_bytes: int = Field(strict=True, ge=1)
    decoded_total_bytes: int = Field(strict=True, ge=1)
    media_output_bytes: int = Field(strict=True, ge=1)
    text_edit_bytes: int = Field(strict=True, ge=1)
    provider_timeout_seconds: int = Field(strict=True, ge=1)
    provider_connect_timeout_seconds: int = Field(strict=True, ge=1)
    provider_catalog_timeout_seconds: int = Field(strict=True, ge=1)


def _raise_settings_error(error: SystemSettingsError) -> NoReturn:
    raise management_error(
        error.status_code,
        code=error.code,
        message_key=error.message_key,
        message=str(error),
        message_args=error.message_args,
    ) from error


def _with_active_url(payload: dict, request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    return {**payload, "active_management_url": f"{base}/admin"}


def build_system_settings_router(
    settings: SystemSettingsService,
    runtime_policy: RuntimePolicyStore,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/system/settings")
    async def get_system_settings(request: Request) -> dict:
        return _with_active_url(settings.get(), request)

    @router.put("/api/system/settings")
    async def update_system_settings(
        payload: SystemSettingsUpdate,
        request: Request,
    ) -> dict:
        values = payload.model_dump()
        if payload.langsmith_api_key.value is not None:
            values["langsmith_api_key"]["value"] = (
                payload.langsmith_api_key.value.get_secret_value()
            )
        try:
            result = settings.update(values)
        except SystemSettingsError as exc:
            _raise_settings_error(exc)
        return _with_active_url(result, request)

    @router.get("/api/system/runtime-policy")
    async def get_runtime_policy() -> dict[str, object]:
        return runtime_policy.public()

    @router.put("/api/system/runtime-policy")
    async def update_runtime_policy(payload: RuntimePolicyUpdate) -> dict[str, object]:
        try:
            return runtime_policy.update(payload.model_dump())
        except ValueError as exc:
            raise management_error(
                422,
                code="runtime_policy_invalid",
                message_key="errors.systemSettingsInvalid",
                message=str(exc),
            ) from exc

    return router
