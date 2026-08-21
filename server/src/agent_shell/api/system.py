from __future__ import annotations

from fastapi import APIRouter

from agent_shell.readiness import ReadinessService


def build_system_router(readiness: ReadinessService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "runtime": "model_streaming"}

    @router.get("/api/readiness")
    async def readiness_report() -> dict[str, object]:
        return readiness.snapshot()

    return router
