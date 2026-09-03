from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from starlette.background import BackgroundTask

from agent_shell.api.errors import management_error
from agent_shell.api.runtime_monitoring import monitoring_http_error
from agent_shell.runtime.monitoring_archive import (
    RuntimeMonitoringArchive,
    RuntimeMonitoringArchiveService,
)
from agent_shell.runtime.monitoring_read_service import MonitoringReadError
from agent_shell.runtime.runtime_cleanup import (
    RuntimeCleanupCoordinator,
    RuntimeLifecycleActiveError,
)
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService


class WorkflowLifecycleBulkDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""


def build_workflow_lifecycle_router(
    lifecycle_service: WorkflowLifecycleService,
    runtime_cleanup: RuntimeCleanupCoordinator,
    monitoring_archive: RuntimeMonitoringArchiveService,
) -> APIRouter:
    """Expose the Lifecycle catalog, archives, and cleanup actions."""

    router = APIRouter()

    async def require_lifecycle(lifecycle_id: str) -> dict[str, object]:
        record = await lifecycle_service.record(lifecycle_id)
        if record is None:
            raise management_error(
                404,
                code="workflow_lifecycle_not_found",
                message_key="errors.workflowLifecycleNotFound",
                message="The Workflow lifecycle does not exist.",
            )
        return record

    async def summary(record: dict[str, object]) -> dict[str, object]:
        lifecycle_id = str(record["lifecycle_id"])
        return {
            **record,
            **lifecycle_service.run_summary(lifecycle_id),
        }

    @router.get("/api/workflow-lifecycles")
    async def list_workflow_lifecycles(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1),
        query: str = Query(default=""),
    ) -> dict[str, object]:
        records, total = await lifecycle_service.list_records_page(
            limit=page_size,
            offset=(page - 1) * page_size,
            query=query,
        )
        return {
            "items": [await summary(record) for record in records],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if total else 1,
        }

    async def prepare_archive(call) -> RuntimeMonitoringArchive:
        try:
            return await call()
        except MonitoringReadError as exc:
            raise monitoring_http_error(exc) from exc
        except Exception as exc:
            raise management_error(
                500,
                code="runtime_monitoring_archive_failed",
                message_key="errors.runtimeMonitoringArchiveFailed",
                message="The runtime monitoring archive could not be created.",
            ) from exc

    def archive_response(archive: RuntimeMonitoringArchive) -> FileResponse:
        return FileResponse(
            archive.path,
            filename=archive.filename,
            media_type="application/zip",
            background=BackgroundTask(archive.release),
        )

    @router.get("/api/workflow-lifecycles/{lifecycle_id}/download")
    async def download_workflow_lifecycle(lifecycle_id: str) -> FileResponse:
        archive = await prepare_archive(
            lambda: monitoring_archive.prepare_lifecycle(lifecycle_id)
        )
        return archive_response(archive)

    @router.get("/api/workflow-lifecycles/{lifecycle_id}/runs/{run_id}/download")
    async def download_workflow_run(
        lifecycle_id: str,
        run_id: str,
    ) -> FileResponse:
        archive = await prepare_archive(
            lambda: monitoring_archive.prepare_run(lifecycle_id, run_id)
        )
        return archive_response(archive)

    async def delete_one(lifecycle_id: str) -> dict[str, int]:
        await require_lifecycle(lifecycle_id)
        try:
            return await runtime_cleanup.delete(lifecycle_id)
        except RuntimeLifecycleActiveError as exc:
            raise management_error(
                409,
                code="workflow_lifecycle_active",
                message_key="errors.workflowLifecycleActive",
                message=str(exc),
            ) from exc

    @router.delete("/api/workflow-lifecycles/{lifecycle_id}")
    async def delete_workflow_lifecycle(
        lifecycle_id: str,
    ) -> dict[str, object]:
        result = await delete_one(lifecycle_id)
        return {
            "ok": True,
            "deleted_checkpoint_thread_count": result["checkpoint_thread_count"],
        }

    @router.post("/api/workflow-lifecycles/delete")
    async def delete_workflow_lifecycles(
        payload: WorkflowLifecycleBulkDelete,
    ) -> dict[str, object]:
        lifecycle_ids = await lifecycle_service.matching_record_ids(
            query=payload.query,
        )
        deleted = 0
        skipped_active = 0
        checkpoint_count = 0
        for lifecycle_id in lifecycle_ids:
            try:
                result = await delete_one(lifecycle_id)
            except HTTPException as exc:
                detail = getattr(exc, "detail", {})
                if (
                    isinstance(detail, dict)
                    and detail.get("code") == "workflow_lifecycle_active"
                ):
                    skipped_active += 1
                    continue
                raise
            deleted += 1
            checkpoint_count += result["checkpoint_thread_count"]
        return {
            "matched": len(lifecycle_ids),
            "deleted": deleted,
            "skipped_active": skipped_active,
            "deleted_checkpoint_thread_count": checkpoint_count,
        }

    return router


__all__ = ["build_workflow_lifecycle_router"]
