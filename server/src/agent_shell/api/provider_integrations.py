from __future__ import annotations

from fastapi import APIRouter

from agent_shell.http_surface import management_api_router
from agent_shell.provider_integrations import provider_catalog


def build_provider_integrations_router() -> APIRouter:
    router = management_api_router()

    @router.get("/model-providers")
    def list_model_providers() -> dict[str, object]:
        return provider_catalog()

    return router
