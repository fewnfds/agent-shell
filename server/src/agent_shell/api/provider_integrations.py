from __future__ import annotations

from fastapi import APIRouter

from agent_shell.provider_integrations import provider_catalog


def build_provider_integrations_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/model-providers")
    async def list_model_providers() -> dict[str, object]:
        return provider_catalog()

    return router
