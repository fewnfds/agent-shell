from __future__ import annotations

from fastapi import APIRouter

from agent_shell.http_surface import management_api_router
from agent_shell.readiness import ReadinessService


def build_system_router(readiness: ReadinessService) -> APIRouter:
    router = management_api_router()

    @router.get("/health", openapi_extra={"security": []})
    async def health() -> dict[str, str]:
        return {"status": "ok", "runtime": "model_streaming"}

    @router.get("/readiness")
    async def readiness_report() -> dict[str, object]:
        return readiness.snapshot()

    return router
