from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from agent_shell.api.errors import management_error
from agent_shell.runtime.runtime_cleanup import (
    RuntimeCleanupCoordinator,
    RuntimeLifecycleActiveError,
)
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService


class WorkflowLifecycleBulkDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    delete_dynamic_directories: bool = False


def build_workflow_lifecycle_router(
    lifecycle_service: WorkflowLifecycleService,
    runtime_cleanup: RuntimeCleanupCoordinator,
) -> APIRouter:
    """Expose the trustworthy catalog while the monitoring read model is built."""

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
            **await lifecycle_service.filesystem_summary(lifecycle_id),
        }

    def generic_detail_unavailable():
        return management_error(
            503,
            code="runtime_monitoring_read_model_unavailable",
            message_key="errors.runtimeMonitoringReadModelUnavailable",
            message=(
                "This generic lifecycle detail or archive endpoint is not "
                "available."
            ),
        )

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

    @router.get("/api/workflow-lifecycles/{lifecycle_id}")
    async def get_workflow_lifecycle(lifecycle_id: str) -> dict[str, object]:
        await require_lifecycle(lifecycle_id)
        raise generic_detail_unavailable()

    @router.get("/api/workflow-lifecycles/{lifecycle_id}/events")
    async def list_workflow_lifecycle_events(lifecycle_id: str) -> dict[str, object]:
        await require_lifecycle(lifecycle_id)
        raise generic_detail_unavailable()

    @router.get("/api/workflow-lifecycles/{lifecycle_id}/runs/{run_id}")
    async def get_workflow_run(
        lifecycle_id: str,
        run_id: str,
    ) -> dict[str, object]:
        await require_lifecycle(lifecycle_id)
        run = lifecycle_service.run(run_id)
        if run is None or run["lifecycle_id"] != lifecycle_id:
            raise management_error(
                404,
                code="workflow_run_not_found",
                message_key="errors.workflowRunNotFound",
                message="The Workflow Run does not exist in this lifecycle.",
            )
        raise generic_detail_unavailable()

    @router.get("/api/workflow-lifecycles/{lifecycle_id}/download")
    async def download_workflow_lifecycle(lifecycle_id: str) -> dict[str, object]:
        await require_lifecycle(lifecycle_id)
        raise generic_detail_unavailable()

    @router.get("/api/workflow-lifecycles/{lifecycle_id}/runs/{run_id}/download")
    async def download_workflow_run(
        lifecycle_id: str,
        run_id: str,
    ) -> dict[str, object]:
        await require_lifecycle(lifecycle_id)
        run = lifecycle_service.run(run_id)
        if run is None or run["lifecycle_id"] != lifecycle_id:
            raise management_error(
                404,
                code="workflow_run_not_found",
                message_key="errors.workflowRunNotFound",
                message="The Workflow Run does not exist in this lifecycle.",
            )
        raise generic_detail_unavailable()

    async def delete_one(
        lifecycle_id: str,
        *,
        delete_dynamic_directories: bool,
    ) -> dict[str, int]:
        await require_lifecycle(lifecycle_id)
        try:
            return await runtime_cleanup.delete(
                lifecycle_id,
                delete_managed_directories=delete_dynamic_directories,
            )
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
        delete_dynamic_directories: bool = Query(default=False),
    ) -> dict[str, object]:
        result = await delete_one(
            lifecycle_id,
            delete_dynamic_directories=delete_dynamic_directories,
        )
        return {
            "ok": True,
            "deleted_checkpoint_thread_count": result["checkpoint_thread_count"],
            "deleted_dynamic_directory_count": result["managed_directory_count"],
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
        directory_count = 0
        for lifecycle_id in lifecycle_ids:
            try:
                result = await delete_one(
                    lifecycle_id,
                    delete_dynamic_directories=payload.delete_dynamic_directories,
                )
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
            directory_count += result["managed_directory_count"]
        return {
            "matched": len(lifecycle_ids),
            "deleted": deleted,
            "skipped_active": skipped_active,
            "deleted_checkpoint_thread_count": checkpoint_count,
            "deleted_dynamic_directory_count": directory_count,
        }

    return router


__all__ = ["build_workflow_lifecycle_router"]
