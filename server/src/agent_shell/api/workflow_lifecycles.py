from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from agent_shell.http_surface import management_api_router
from agent_shell.api.errors import management_error
from agent_shell.runtime.langgraph_lifecycle import (
    LangGraphLifecycleActive,
    LangGraphLifecycleNotFound,
    LangGraphLifecycleService,
)
from agent_shell.storage.workflow_lifecycle_settings import (
    WorkflowLifecycleSettingsStore,
)


class WorkflowLifecycleBulkDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""


class WorkflowLifecycleSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retained_lifecycles: int = Field(strict=True, ge=0)


def build_workflow_lifecycle_router(
    service: LangGraphLifecycleService,
    settings: WorkflowLifecycleSettingsStore,
) -> APIRouter:
    """Expose Lifecycle grouping without owning a second Run registry."""

    router = management_api_router()

    @router.get("/workflow-lifecycles/settings")
    async def get_workflow_lifecycle_settings() -> dict[str, object]:
        return settings.public()

    @router.put("/workflow-lifecycles/settings")
    async def update_workflow_lifecycle_settings(
        payload: WorkflowLifecycleSettingsUpdate,
    ) -> dict[str, object]:
        result = settings.update(payload.retained_lifecycles)
        await service.enforce_retention()
        return result

    @router.get("/workflow-lifecycles")
    async def list_workflow_lifecycles(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1),
        query: str = Query(default=""),
    ) -> dict[str, object]:
        return await service.list_page(page=page, page_size=page_size, query=query)

    @router.delete("/workflow-lifecycles/{lifecycle_id}")
    async def delete_workflow_lifecycle(lifecycle_id: str) -> dict[str, object]:
        try:
            deleted_threads = await service.delete(lifecycle_id)
        except LangGraphLifecycleNotFound as exc:
            raise management_error(
                404,
                code="workflow_lifecycle_not_found",
                message_key="errors.workflowLifecycleNotFound",
                message="The Workflow Lifecycle does not exist.",
            ) from exc
        except LangGraphLifecycleActive as exc:
            raise management_error(
                409,
                code="workflow_lifecycle_active",
                message_key="errors.workflowLifecycleActive",
                message="An active Workflow Run still belongs to this Lifecycle.",
            ) from exc
        return {"ok": True, "deleted_thread_count": deleted_threads}

    @router.post("/workflow-lifecycles/delete")
    async def delete_workflow_lifecycles(
        payload: WorkflowLifecycleBulkDelete,
    ) -> dict[str, int]:
        return await service.delete_matching(payload.query)

    return router


__all__ = ["build_workflow_lifecycle_router"]
