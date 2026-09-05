from __future__ import annotations

from typing import Literal, NoReturn
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from agent_shell.http_surface import http_surface, management_api_router
from agent_shell.api.errors import management_error
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
    n_jobs_per_worker: int = Field(strict=True, ge=1)
    recursion_limit: int = Field(strict=True, ge=1)
    max_concurrency: int | None = Field(default=None, strict=True, ge=1)
    debug_port: int | None = Field(default=None, strict=True, ge=1, le=65535)
    allow_remote: bool
    langsmith_tracing_enabled: bool
    langsmith_endpoint: str
    langsmith_project: str
    langsmith_workspace_id: str | None = None
    langsmith_api_key: OptionalSecretUpdate
    management_token: ManagementPasswordUpdate
    cors_origins: list[str]
    trusted_proxy_cidrs: list[str]


def _raise_settings_error(error: SystemSettingsError) -> NoReturn:
    raise management_error(
        error.status_code,
        code=error.code,
        message_key=error.message_key,
        message=str(error),
        message_args=error.message_args,
    ) from error


def _with_active_urls(payload: dict, request: Request) -> dict:
    entries = http_surface(request)["service_entries"]
    return {
        **payload,
        "active_management_url": entries["management_console_url"],
        "active_api_docs_url": entries["api_docs_url"],
        "active_studio_url": entries["langgraph_studio_url"],
    }


def build_system_settings_router(
    settings: SystemSettingsService,
) -> APIRouter:
    router = management_api_router()

    @router.get("/system/settings")
    async def get_system_settings(request: Request) -> dict:
        return _with_active_urls(settings.get(), request)

    @router.put("/system/settings")
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
        return _with_active_urls(result, request)

    return router
