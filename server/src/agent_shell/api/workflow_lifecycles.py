from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import tempfile
import zipfile

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from agent_shell.api.errors import management_error
from agent_shell.runtime.background_tasks import (
    ACTIVE_BACKGROUND_STATUSES,
    BackgroundTaskManager,
)
from agent_shell.runtime.diagnostics import RuntimeDiagnostics
from agent_shell.runtime.workflow_checkpoints import WorkflowCheckpointService
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService


EXPORT_SECTIONS = frozenset(
    {
        "run_registry",
        "structural_events",
        "lifecycle_input",
        "agent_invocations",
        "background_tasks",
        "checkpoint_summaries",
        "store_summary",
        "diagnostic_summaries",
        "checkpoint_state",
        "store_payloads",
    }
)


def _json_default(value: object) -> object:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except (TypeError, ValueError):
            pass
    return str(value)


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=_json_default,
    ) + "\n"


def _json_line(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")


def _write_json_file(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json(value), encoding="utf-8")


def _write_jsonl_file(path: Path, values: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        for value in values:
            stream.write(_json_line(value))


def _write_event_pages(
    path: Path,
    lifecycle_service: WorkflowLifecycleService,
    lifecycle_id: str,
    run_id: str | None,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    after_sequence = 0
    with path.open("wb") as stream:
        while True:
            page = lifecycle_service.events(
                lifecycle_id,
                run_id=run_id,
                after_sequence=after_sequence,
                limit=5000,
            )
            for event in page:
                stream.write(_json_line(event))
            if not page:
                return after_sequence
            after_sequence = int(page[-1]["sequence"])
            if len(page) < 5000:
                return after_sequence


def _append_bytes(path: Path, payload: bytes) -> None:
    with path.open("ab") as stream:
        stream.write(payload)


async def _write_async_jsonl_file(
    path: Path,
    values: AsyncIterator[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, b"")
    chunk = bytearray()
    async for value in values:
        chunk.extend(_json_line(value))
        if len(chunk) >= 1024 * 1024:
            await asyncio.to_thread(_append_bytes, path, bytes(chunk))
            chunk.clear()
    if chunk:
        await asyncio.to_thread(_append_bytes, path, bytes(chunk))


def _build_zip(
    content_root: Path,
    archive_path: Path,
    diagnostic_details: list[tuple[Path, str]],
) -> None:
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for path in sorted(content_root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(content_root).as_posix())
        for path, archive_name in diagnostic_details:
            archive.write(path, archive_name)


def _diagnostic_file_response(
    archive_path: Path,
    export_root: Path,
    filename: str,
) -> FileResponse:
    return FileResponse(
        archive_path,
        filename=filename,
        media_type="application/zip",
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(
            shutil.rmtree,
            export_root,
            ignore_errors=True,
        ),
    )


def build_workflow_lifecycle_router(
    lifecycle_service: WorkflowLifecycleService,
    background_tasks: BackgroundTaskManager,
    workflow_checkpoints: WorkflowCheckpointService,
    runtime_diagnostics: RuntimeDiagnostics,
    export_temp_root: Path,
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

    async def checkpoint_summaries(
        runs: list[dict[str, object]],
        *,
        limit: int | None = 100,
    ) -> dict[str, list[dict[str, object]]]:
        result: dict[str, list[dict[str, object]]] = {}
        for run in runs:
            if not run["checkpoint_available"]:
                continue
            result[str(run["run_id"])] = await workflow_checkpoints.checkpoint_history(
                str(run["thread_id"]),
                limit=limit,
            )
        return result

    async def summary(record: dict[str, object]) -> dict[str, object]:
        lifecycle_id = str(record["lifecycle_id"])
        tasks = await background_tasks.list(lifecycle_id)
        task_counts = Counter(task.runtime_status for task in tasks)
        runs = lifecycle_service.runs(lifecycle_id)
        run_summary = lifecycle_service.run_summary(lifecycle_id)
        if len(runs) < 1 + len(tasks):
            run_summary["observation_status"] = (
                "unavailable" if not runs else "partial"
            )
        checkpoint_count = 0
        for run in runs:
            if run["checkpoint_available"]:
                checkpoint_count += await workflow_checkpoints.checkpoint_count(
                    str(run["thread_id"])
                )
        filesystem = await lifecycle_service.filesystem_summary(lifecycle_id)
        return {
            **record,
            "lifecycle_status": record.get("lifecycle_status", "active"),
            "task_count": len(tasks),
            "active_task_count": sum(
                task_counts.get(status, 0) for status in ACTIVE_BACKGROUND_STATUSES
            ),
            "task_status_counts": dict(sorted(task_counts.items())),
            "checkpoint_count": checkpoint_count,
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

    def diagnostic_details(
        diagnostics: list[dict[str, object]],
    ) -> list[tuple[Path, str]]:
        result: list[tuple[Path, str]] = []
        for entry in diagnostics:
            diagnostic_id = str(entry["diagnostic_id"])
            path = runtime_diagnostics.detail_path(diagnostic_id)
            if path is not None:
                result.append((path, f"diagnostics/{diagnostic_id}.log"))
        return result

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
                await workflow_checkpoints.checkpoint_count(str(run["thread_id"]))
                if run["checkpoint_available"]
                else 0
            ),
            "diagnostic_count": len(diagnostics),
        }

    @router.get("/api/workflow-lifecycles/{lifecycle_id}/download")
    async def download_workflow_lifecycle(
        lifecycle_id: str,
    ) -> FileResponse:
        record = await require_lifecycle(lifecycle_id)
        captured_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        runs = lifecycle_service.runs(lifecycle_id)
        diagnostics = diagnostics_for(lifecycle_id)
        summary_payload = await summary(record)
        store_summary = await lifecycle_service.artifact_summary(lifecycle_id)
        export_temp_root.mkdir(parents=True, exist_ok=True)
        export_root = Path(
            tempfile.mkdtemp(prefix="workflow-diagnostic-", dir=export_temp_root)
        )
        content_root = export_root / "content"
        archive_path = export_root / "diagnostic.zip"
        try:
            last_event_sequence = await asyncio.to_thread(
                _write_event_pages,
                content_root / "events.jsonl",
                lifecycle_service,
                lifecycle_id,
                None,
            )
            for run in runs:
                if not run["checkpoint_available"]:
                    continue
                run_id = str(run["run_id"])
                await _write_async_jsonl_file(
                    content_root / "checkpoints" / f"{run_id}.jsonl",
                    workflow_checkpoints.iter_checkpoint_history(
                        str(run["thread_id"]),
                        include_state=True,
                    ),
                )
            manifest = {
                "format": "agent-shell-run-history-v2",
                "scope": "lifecycle",
                "captured_at": captured_at,
                "lifecycle_id": lifecycle_id,
                "lifecycle_status": record.get("lifecycle_status", "active"),
                "observation_status": summary_payload["observation_status"],
                "last_event_sequence": last_event_sequence,
                "includes": {key: True for key in sorted(EXPORT_SECTIONS)},
                "diagnostic_details_included": True,
                "limitations": [
                    "This is a captured runtime snapshot, not a byte-exact replay.",
                    "Final network-layer Provider requests and raw successful Provider HTTP responses are not separately persisted.",
                    "The archive contains persisted runtime data available to the Run History owner.",
                ],
            }
            await asyncio.to_thread(
                _write_json_file, content_root / "manifest.json", manifest
            )
            await asyncio.to_thread(
                _write_json_file, content_root / "lifecycle.json", summary_payload
            )
            await asyncio.to_thread(
                _write_json_file, content_root / "runs.json", runs
            )
            await asyncio.to_thread(
                _write_json_file,
                content_root / "input.json",
                await lifecycle_service.input_record(lifecycle_id),
            )
            await asyncio.to_thread(
                _write_jsonl_file,
                content_root / "agent-invocations.jsonl",
                await lifecycle_service.invocation_artifacts(lifecycle_id),
            )
            await asyncio.to_thread(
                _write_jsonl_file,
                content_root / "background-tasks.jsonl",
                await lifecycle_service.task_records(lifecycle_id),
            )
            await asyncio.to_thread(
                _write_json_file, content_root / "store-summary.json", store_summary
            )
            await asyncio.to_thread(
                _write_jsonl_file,
                content_root / "store-payloads.jsonl",
                await lifecycle_service.store_records(lifecycle_id),
            )
            await asyncio.to_thread(
                _write_jsonl_file, content_root / "diagnostics.jsonl", diagnostics
            )
            await asyncio.to_thread(
                _build_zip,
                content_root,
                archive_path,
                diagnostic_details(diagnostics),
            )
        except BaseException:
            shutil.rmtree(export_root, ignore_errors=True)
            raise
        return _diagnostic_file_response(
            archive_path,
            export_root,
            f"agent-shell-lifecycle-{lifecycle_id}.zip",
        )

    @router.get("/api/workflow-lifecycles/{lifecycle_id}/runs/{run_id}/download")
    async def download_workflow_run(
        lifecycle_id: str,
        run_id: str,
    ) -> FileResponse:
        await require_lifecycle(lifecycle_id)
        run = require_run(lifecycle_id, run_id)
        diagnostics = diagnostics_for(lifecycle_id, run_id=run_id)
        export_temp_root.mkdir(parents=True, exist_ok=True)
        export_root = Path(
            tempfile.mkdtemp(prefix="workflow-diagnostic-", dir=export_temp_root)
        )
        content_root = export_root / "content"
        archive_path = export_root / "diagnostic.zip"
        try:
            last_event_sequence = await asyncio.to_thread(
                _write_event_pages,
                content_root / "events.jsonl",
                lifecycle_service,
                lifecycle_id,
                run_id,
            )
            checkpoint_path = content_root / "checkpoints.jsonl"
            if run["checkpoint_available"]:
                await _write_async_jsonl_file(
                    checkpoint_path,
                    workflow_checkpoints.iter_checkpoint_history(
                        str(run["thread_id"]),
                        include_state=True,
                    ),
                )
            else:
                await asyncio.to_thread(
                    checkpoint_path.parent.mkdir, parents=True, exist_ok=True
                )
                await asyncio.to_thread(checkpoint_path.write_bytes, b"")
            manifest = {
                "format": "agent-shell-run-history-v2",
                "scope": "run",
                "captured_at": datetime.now(timezone.utc).isoformat(
                    timespec="milliseconds"
                ),
                "lifecycle_id": lifecycle_id,
                "run_id": run_id,
                "run_status": run["status"],
                "observation_status": run["observation_status"],
                "last_event_sequence": last_event_sequence,
                "checkpoint_available": run["checkpoint_available"],
                "includes": {key: True for key in sorted(EXPORT_SECTIONS)},
                "diagnostic_details_included": True,
                "limitations": [
                    "This is a captured runtime snapshot, not a byte-exact replay.",
                    "Final network-layer Provider requests and raw successful Provider HTTP responses are not separately persisted.",
                    "The archive contains persisted runtime data available to the Run History owner.",
                ],
            }
            await asyncio.to_thread(
                _write_json_file, content_root / "manifest.json", manifest
            )
            await asyncio.to_thread(
                _write_json_file, content_root / "run.json", run
            )
            await asyncio.to_thread(
                _write_json_file,
                content_root / "input.json",
                await lifecycle_service.input_record(lifecycle_id),
            )
            await asyncio.to_thread(
                _write_jsonl_file,
                content_root / "agent-invocations.jsonl",
                await lifecycle_service.invocation_artifacts(
                    lifecycle_id, run_id=run_id
                ),
            )
            await asyncio.to_thread(
                _write_jsonl_file,
                content_root / "background-tasks.jsonl",
                await lifecycle_service.task_records(lifecycle_id, run_id=run_id),
            )
            await asyncio.to_thread(
                _write_json_file,
                content_root / "store-summary.json",
                await lifecycle_service.artifact_summary(lifecycle_id),
            )
            await asyncio.to_thread(
                _write_jsonl_file,
                content_root / "store-payloads.jsonl",
                await lifecycle_service.store_records(lifecycle_id, run_id=run_id),
            )
            await asyncio.to_thread(
                _write_jsonl_file, content_root / "diagnostics.jsonl", diagnostics
            )
            await asyncio.to_thread(
                _build_zip,
                content_root,
                archive_path,
                diagnostic_details(diagnostics),
            )
        except BaseException:
            shutil.rmtree(export_root, ignore_errors=True)
            raise
        return _diagnostic_file_response(
            archive_path,
            export_root,
            f"agent-shell-run-{run_id}.zip",
        )

    @router.delete("/api/workflow-lifecycles/{lifecycle_id}")
    async def delete_workflow_lifecycle(
        lifecycle_id: str,
        delete_dynamic_directories: bool = Query(default=False),
    ) -> dict[str, object]:
        async with lifecycle_service.exclusive_mutation(lifecycle_id):
            record = await require_lifecycle(lifecycle_id)
            tasks = await background_tasks.list_for_cleanup(lifecycle_id)
            runs = lifecycle_service.runs(lifecycle_id)
            if record.get("parent_status") == "running" or any(
                task.runtime_status in ACTIVE_BACKGROUND_STATUSES for task in tasks
            ):
                raise management_error(
                    409,
                    code="workflow_lifecycle_active",
                    message_key="errors.workflowLifecycleActive",
                    message="A Workflow lifecycle with an active run cannot be deleted.",
                )
            await lifecycle_service.mark_deleting(lifecycle_id)
            thread_ids = {
                str(run["thread_id"])
                for run in runs
                if run["checkpoint_available"]
            }
            thread_ids.add(str(record.get("parent_thread_id", "")))
            thread_ids.discard("")
            for thread_id in thread_ids:
                await workflow_checkpoints.purge_thread(thread_id)
            await lifecycle_service.delete(
                lifecycle_id,
                delete_dynamic_directories=delete_dynamic_directories,
            )
        return {
            "ok": True,
            "deleted_thread_count": len(thread_ids),
            "deleted_dynamic_directories": delete_dynamic_directories,
        }

    return router


__all__ = ["build_workflow_lifecycle_router"]
