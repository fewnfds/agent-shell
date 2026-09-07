from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response

from agent_shell.http_surface import management_api_router
from agent_shell.api.errors import management_error
from agent_shell.runtime.langgraph_lifecycle import (
    LangGraphLifecycleNotFound,
    LangGraphLifecycleService,
    LangGraphRunNotFound,
)


def _not_found(exc: LookupError):
    if isinstance(exc, LangGraphLifecycleNotFound):
        return management_error(
            404,
            code="workflow_lifecycle_not_found",
            message_key="errors.workflowLifecycleNotFound",
            message="The Workflow Lifecycle does not exist.",
        )
    return management_error(
        404,
        code="workflow_run_not_found",
        message_key="errors.workflowRunNotFound",
        message="The Workflow Run does not exist in this Lifecycle.",
    )


def build_runtime_monitoring_router(service: LangGraphLifecycleService) -> APIRouter:
    """Expose official Run, Graph, State, and history through a thin product route."""

    router = management_api_router()
    prefix = "/workflow-lifecycles/{lifecycle_id}/monitoring"

    async def read(call):
        try:
            return await call()
        except (LangGraphLifecycleNotFound, LangGraphRunNotFound) as exc:
            raise _not_found(exc) from exc

    @router.get(prefix + "/snapshot")
    async def snapshot(lifecycle_id: str):
        return await read(lambda: service.snapshot(lifecycle_id))

    @router.get(prefix + "/store")
    async def store(lifecycle_id: str):
        return await read(lambda: service.store(lifecycle_id))

    @router.get(prefix + "/download")
    async def download(lifecycle_id: str):
        exported = await read(lambda: service.export(lifecycle_id))
        return Response(
            content=exported.content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{exported.filename}"'
            },
        )

    @router.get(prefix + "/runs/{run_id}/graph")
    async def graph(lifecycle_id: str, run_id: str):
        return await read(lambda: service.graph(lifecycle_id, run_id))

    @router.get(prefix + "/runs/{run_id}/state")
    async def state(lifecycle_id: str, run_id: str):
        return await read(lambda: service.state(lifecycle_id, run_id))

    @router.get(prefix + "/runs/{run_id}/history")
    async def history(
        lifecycle_id: str,
        run_id: str,
        limit: int = Query(default=10, ge=1),
    ):
        return await read(
            lambda: service.history(lifecycle_id, run_id, limit=limit)
        )

    return router


__all__ = ["build_runtime_monitoring_router"]
