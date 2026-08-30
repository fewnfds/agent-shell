from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections import Counter
import math

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from starlette.background import BackgroundTask

from agent_shell.api.errors import management_error
from agent_shell.runtime.background_tasks import (
    ACTIVE_BACKGROUND_STATUSES,
    BackgroundTaskManager,
)
from agent_shell.runtime.diagnostics import RuntimeDiagnostics
from agent_shell.runtime.diagnostics import RuntimeDiagnosticContext
from agent_shell.runtime.workflow_checkpoints import WorkflowCheckpointService
from agent_shell.runtime.workflow_diagnostic_exports import (
    WorkflowDiagnosticCheckpointError,
    WorkflowDiagnosticExportService,
)
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService


class WorkflowLifecycleBulkDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    delete_dynamic_directories: bool = False


def build_workflow_lifecycle_router(
    lifecycle_service: WorkflowLifecycleService,
    background_tasks: BackgroundTaskManager,
    workflow_checkpoints: WorkflowCheckpointService,
    runtime_diagnostics: RuntimeDiagnostics,
    diagnostic_exports: WorkflowDiagnosticExportService,
) -> APIRouter:
    router = APIRouter()

    def diagnostics_for(
        lifecycle_id: str,
        *,
        run_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            dict(entry)
            for entry in runtime_diagnostics.snapshot()["entries"]
            if entry.get("lifecycle_id") == lifecycle_id
            and (run_id is None or entry.get("run_id") == run_id)
        ]

    def checkpoint_error(
        exc: BaseException,
        *,
        lifecycle_id: str,
        run_id: str = "",
        checkpoint_thread_id: str = "",
    ):
        runtime_diagnostics.observation_error(
            exc,
            code="workflow_checkpoint_query_failed",
            component="persistence",
            context=RuntimeDiagnosticContext(
                lifecycle_id=lifecycle_id,
                workflow_run_id=run_id,
                checkpoint_thread_id=checkpoint_thread_id or None,
                subject_kind="persistence",
                subject_name="Workflow Checkpointer",
            ),
        )
        return management_error(
            503,
            code="workflow_checkpointer_unavailable",
            message_key="errors.workflowCheckpointerUnavailable",
            message="Workflow checkpoint data is unavailable.",
        )

    async def checkpoint_count(
        checkpoint_thread_id: str,
        *,
        lifecycle_id: str,
        run_id: str,
    ) -> int:
        try:
            return await workflow_checkpoints.checkpoint_count(
                checkpoint_thread_id
            )
        except Exception as exc:
            raise checkpoint_error(
                exc,
                lifecycle_id=lifecycle_id,
                run_id=run_id,
                checkpoint_thread_id=checkpoint_thread_id,
            ) from exc

    async def checkpoint_history(
        checkpoint_thread_id: str,
        *,
        lifecycle_id: str,
        run_id: str,
        limit: int | None,
    ) -> list[dict[str, object]]:
        try:
            return await workflow_checkpoints.checkpoint_history(
                checkpoint_thread_id,
                limit=limit,
            )
        except Exception as exc:
            raise checkpoint_error(
                exc,
                lifecycle_id=lifecycle_id,
                run_id=run_id,
                checkpoint_thread_id=checkpoint_thread_id,
            ) from exc

    async def iter_checkpoint_history(
        checkpoint_thread_id: str,
        *,
        lifecycle_id: str,
        run_id: str,
        include_state: bool,
    ) -> AsyncIterator[dict[str, object]]:
        try:
            async for item in workflow_checkpoints.iter_checkpoint_history(
                checkpoint_thread_id,
                include_state=include_state,
            ):
                yield item
        except Exception as exc:
            raise checkpoint_error(
                exc,
                lifecycle_id=lifecycle_id,
                run_id=run_id,
                checkpoint_thread_id=checkpoint_thread_id,
            ) from exc

    async def purge_checkpoint_thread(
        checkpoint_thread_id: str,
        *,
        lifecycle_id: str,
    ) -> None:
        try:
            await workflow_checkpoints.purge_thread(checkpoint_thread_id)
        except Exception as exc:
            raise checkpoint_error(
                exc,
                lifecycle_id=lifecycle_id,
                checkpoint_thread_id=checkpoint_thread_id,
            ) from exc

    async def checkpoint_summaries(
        runs: list[dict[str, object]],
        *,
        limit: int | None = 100,
    ) -> dict[str, list[dict[str, object]]]:
        result: dict[str, list[dict[str, object]]] = {}
        for run in runs:
            checkpoint_thread_id = run.get("checkpoint_thread_id")
            if checkpoint_thread_id is None:
                continue
            run_id = str(run["run_id"])
            result[run_id] = await checkpoint_history(
                str(checkpoint_thread_id),
                lifecycle_id=str(run["lifecycle_id"]),
                run_id=run_id,
                limit=limit,
            )
        return result

    async def summary(record: dict[str, object]) -> dict[str, object]:
        lifecycle_id = str(record["lifecycle_id"])
        tasks, invalid_task_count = await background_tasks.list_for_history(
            lifecycle_id
        )
        task_count = len(tasks) + invalid_task_count
        task_counts = Counter(task.runtime_status for task in tasks)
        runs = lifecycle_service.runs(lifecycle_id)
        run_summary = lifecycle_service.run_summary(lifecycle_id)
        if invalid_task_count or len(runs) < 1 + task_count:
            run_summary["observation_status"] = (
                "unavailable" if not runs else "partial"
            )
        total_checkpoint_count = 0
        for run in runs:
            checkpoint_thread_id = run.get("checkpoint_thread_id")
            if checkpoint_thread_id is not None:
                total_checkpoint_count += await checkpoint_count(
                    str(checkpoint_thread_id),
                    lifecycle_id=lifecycle_id,
                    run_id=str(run["run_id"]),
                )
        filesystem = await lifecycle_service.filesystem_summary(lifecycle_id)
        return {
            **record,
            "lifecycle_status": record.get("lifecycle_status", "active"),
            "task_count": task_count,
            "invalid_task_count": invalid_task_count,
            "active_task_count": sum(
                task_counts.get(status, 0) for status in ACTIVE_BACKGROUND_STATUSES
            ),
            "task_status_counts": dict(sorted(task_counts.items())),
            "checkpoint_count": total_checkpoint_count,
            "store_item_count": await lifecycle_service.store_item_count(lifecycle_id),
            **run_summary,
            **filesystem,
        }

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

    def require_run(lifecycle_id: str, run_id: str) -> dict[str, object]:
        run = lifecycle_service.history.get_run(run_id)
        if run is None or run["lifecycle_id"] != lifecycle_id:
            raise management_error(
                404,
                code="workflow_run_not_found",
                message_key="errors.workflowRunNotFound",
                message="The Workflow Run does not exist in this lifecycle.",
            )
        return run

    async def cleanup_lifecycle(
        lifecycle_id: str,
        *,
        delete_dynamic_directories: bool,
        skip_active: bool,
        skip_missing: bool = False,
    ) -> tuple[str, int]:
        async with lifecycle_service.exclusive_mutation(lifecycle_id):
            record = await lifecycle_service.record(lifecycle_id)
            if record is None:
                if skip_missing:
                    return "missing", 0
                record = await require_lifecycle(lifecycle_id)
            tasks = await background_tasks.list_for_cleanup(lifecycle_id)
            runs = lifecycle_service.runs(lifecycle_id)
            if record.get("parent_status") == "running" or any(
                task.runtime_status in ACTIVE_BACKGROUND_STATUSES for task in tasks
            ):
                if skip_active:
                    return "active", 0
                raise management_error(
                    409,
                    code="workflow_lifecycle_active",
                    message_key="errors.workflowLifecycleActive",
                    message="A Workflow lifecycle with an active run cannot be deleted.",
                )
            await lifecycle_service.mark_deleting(lifecycle_id)
            checkpoint_thread_ids = {
                str(run["checkpoint_thread_id"])
                for run in runs
                if run.get("checkpoint_thread_id") is not None
            }
            for checkpoint_thread_id in checkpoint_thread_ids:
                await purge_checkpoint_thread(
                    checkpoint_thread_id,
                    lifecycle_id=lifecycle_id,
                )
            await lifecycle_service.delete(
                lifecycle_id,
                delete_dynamic_directories=delete_dynamic_directories,
            )
        return "deleted", len(checkpoint_thread_ids)

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
        record = await require_lifecycle(lifecycle_id)
        runs = lifecycle_service.runs(lifecycle_id)
        event_page = lifecycle_service.events(lifecycle_id, limit=1001)
        visible_events = event_page[:1000]
        return {
            **await summary(record),
            "runs": runs,
            "events": visible_events,
            "next_event_sequence": (
                int(visible_events[-1]["sequence"]) if visible_events else 0
            ),
            "event_has_more": len(event_page) > 1000,
            "artifacts": await lifecycle_service.artifact_summary(lifecycle_id),
            "checkpoints": await checkpoint_summaries(runs),
            "diagnostics": diagnostics_for(lifecycle_id),
        }

    @router.get("/api/workflow-lifecycles/{lifecycle_id}/events")
    async def list_workflow_lifecycle_events(
        lifecycle_id: str,
        run_id: str | None = Query(default=None),
        node_invocation_id: str | None = Query(default=None),
        event_type: str | None = Query(default=None),
        after_sequence: int = Query(default=0, ge=0),
        limit: int = Query(default=1000, ge=1),
    ) -> dict[str, object]:
        await require_lifecycle(lifecycle_id)
        if run_id is not None:
            require_run(lifecycle_id, run_id)
        page = lifecycle_service.events(
            lifecycle_id,
            run_id=run_id,
            node_invocation_id=node_invocation_id,
            event_type=event_type,
            after_sequence=after_sequence,
            limit=limit + 1,
        )
        items = page[:limit]
        return {
            "items": items,
            "next_after_sequence": int(items[-1]["sequence"]) if items else after_sequence,
            "has_more": len(page) > limit,
        }

    @router.get("/api/workflow-lifecycles/{lifecycle_id}/runs/{run_id}")
    async def get_workflow_run(lifecycle_id: str, run_id: str) -> dict[str, object]:
        await require_lifecycle(lifecycle_id)
        run = require_run(lifecycle_id, run_id)
        diagnostics = diagnostics_for(lifecycle_id, run_id=run_id)
        return {
            **run,
            "event_count": lifecycle_service.event_count(
                lifecycle_id,
                run_id=run_id,
            ),
            "checkpoint_count": (
                await checkpoint_count(
                    str(run["checkpoint_thread_id"]),
                    lifecycle_id=lifecycle_id,
                    run_id=run_id,
                )
                if run.get("checkpoint_thread_id") is not None
                else 0
            ),
            "diagnostic_count": len(diagnostics),
        }

    @router.get("/api/workflow-lifecycles/{lifecycle_id}/download")
    async def download_workflow_lifecycle(
        lifecycle_id: str,
    ) -> FileResponse:
        record = await require_lifecycle(lifecycle_id)
        try:
            archive = await diagnostic_exports.export_lifecycle(
                lifecycle_id,
                record=record,
                summary=await summary(record),
            )
        except WorkflowDiagnosticCheckpointError as exc:
            raise checkpoint_error(
                exc.error,
                lifecycle_id=exc.lifecycle_id,
                run_id=exc.run_id,
                checkpoint_thread_id=exc.checkpoint_thread_id,
            ) from exc
        return FileResponse(
            archive.path,
            filename=archive.filename,
            media_type="application/zip",
            headers={"Cache-Control": "no-store"},
            background=BackgroundTask(archive.release),
        )

    @router.get("/api/workflow-lifecycles/{lifecycle_id}/runs/{run_id}/download")
    async def download_workflow_run(
        lifecycle_id: str,
        run_id: str,
    ) -> FileResponse:
        await require_lifecycle(lifecycle_id)
        run = require_run(lifecycle_id, run_id)
        try:
            archive = await diagnostic_exports.export_run(
                lifecycle_id,
                run=run,
            )
        except WorkflowDiagnosticCheckpointError as exc:
            raise checkpoint_error(
                exc.error,
                lifecycle_id=exc.lifecycle_id,
                run_id=exc.run_id,
                checkpoint_thread_id=exc.checkpoint_thread_id,
            ) from exc
        return FileResponse(
            archive.path,
            filename=archive.filename,
            media_type="application/zip",
            headers={"Cache-Control": "no-store"},
            background=BackgroundTask(archive.release),
        )

    @router.delete("/api/workflow-lifecycles/{lifecycle_id}")
    async def delete_workflow_lifecycle(
        lifecycle_id: str,
        delete_dynamic_directories: bool = Query(default=False),
    ) -> dict[str, object]:
        _, deleted_checkpoint_thread_count = await cleanup_lifecycle(
            lifecycle_id,
            delete_dynamic_directories=delete_dynamic_directories,
            skip_active=False,
        )
        return {
            "ok": True,
            "deleted_checkpoint_thread_count": deleted_checkpoint_thread_count,
            "deleted_dynamic_directories": delete_dynamic_directories,
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
        deleted_checkpoint_thread_count = 0
        for lifecycle_id in lifecycle_ids:
            outcome, checkpoint_count = await cleanup_lifecycle(
                lifecycle_id,
                delete_dynamic_directories=payload.delete_dynamic_directories,
                skip_active=True,
                skip_missing=True,
            )
            if outcome == "deleted":
                deleted += 1
                deleted_checkpoint_thread_count += checkpoint_count
            elif outcome == "active":
                skipped_active += 1
        return {
            "matched": len(lifecycle_ids),
            "deleted": deleted,
            "skipped_active": skipped_active,
            "deleted_checkpoint_thread_count": deleted_checkpoint_thread_count,
            "deleted_dynamic_directories": payload.delete_dynamic_directories,
        }

    return router


__all__ = ["build_workflow_lifecycle_router"]
