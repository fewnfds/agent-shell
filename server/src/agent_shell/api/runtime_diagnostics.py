from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from agent_shell.runtime.diagnostics import RuntimeDiagnostics


class RuntimeDiagnosticsRetentionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_limit: int = Field(ge=1)


def build_runtime_diagnostics_router(
    diagnostics: RuntimeDiagnostics,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/runtime-diagnostics")
    async def get_runtime_diagnostics() -> dict[str, object]:
        return diagnostics.settings()

    @router.put("/api/runtime-diagnostics/retention")
    async def update_runtime_diagnostics_retention(
        payload: RuntimeDiagnosticsRetentionUpdate,
    ) -> dict[str, object]:
        return diagnostics.set_retention_limit(payload.retention_limit)

    return router
