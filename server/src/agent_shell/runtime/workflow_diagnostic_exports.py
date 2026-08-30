from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import quote
import zipfile

from agent_shell.runtime.diagnostics import RuntimeDiagnostics
from agent_shell.runtime.workflow_checkpoints import WorkflowCheckpointService
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService


EXPORT_SECTIONS = frozenset(
    {
        "run_registry",
        "structural_events",
        "lifecycle_input",
        "agent_invocations",
        "model_requests",
        "background_tasks",
        "checkpoint_summaries",
        "store_summary",
        "diagnostic_summaries",
        "checkpoint_state",
        "store_payloads",
        "v3_event_streams",
    }
)
EXPORT_LIMITATIONS = (
    "This is a captured runtime snapshot, not a byte-exact replay.",
    "LangChain on_chat_model_start messages, tools, and invocation parameters are persisted under model-requests/.",
    "Provider-adapter network payloads and raw successful Provider HTTP responses are not separately persisted.",
    "The archive contains persisted runtime data available to the Run History owner.",
)


@dataclass(frozen=True, slots=True)
class WorkflowDiagnosticArchive:
    path: Path
    filename: str
    _export_root: Path = field(repr=False)

    def release(self) -> None:
        shutil.rmtree(self._export_root, ignore_errors=True)


class WorkflowDiagnosticCheckpointError(RuntimeError):
    def __init__(
        self,
        error: BaseException,
        *,
        lifecycle_id: str,
        run_id: str,
        checkpoint_thread_id: str,
    ) -> None:
        self.error = error
        self.lifecycle_id = lifecycle_id
        self.run_id = run_id
        self.checkpoint_thread_id = checkpoint_thread_id
        super().__init__("Workflow checkpoint data is unavailable.")


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


def _path_segment(value: object) -> str:
    segment = re.sub(r"[^A-Za-z0-9._-]", "_", str(value or ""))
    return segment if segment not in {"", ".", ".."} else "unknown"


def _write_model_request_files(
    root: Path,
    records: list[dict[str, object]],
) -> None:
    grouped: dict[str, list[dict[str, object]]] = {}
    for record in records:
        node_scope = _path_segment(
            record.get("workflow_node_id") or record.get("parent_agent_id")
        )
        agent_id = _path_segment(record.get("agent_id"))
        if record.get("agent_type") == "subagent":
            relative_path = f"subagents/{node_scope}/{agent_id}.jsonl"
        else:
            relative_path = f"main-agents/{node_scope}--{agent_id}.jsonl"
        grouped.setdefault(relative_path, []).append(record)

    owners: list[dict[str, object]] = []
    for relative_path, owner_records in sorted(grouped.items()):
        first = owner_records[0]
        _write_jsonl_file(root / relative_path, owner_records)
        owners.append(
            {
                "path": relative_path,
                "request_count": len(owner_records),
                "agent_type": first["agent_type"],
                "agent_id": first["agent_id"],
                "agent_name": first["agent_name"],
                "parent_agent_id": first.get("parent_agent_id", ""),
                "parent_agent_name": first.get("parent_agent_name", ""),
                "workflow_node_id": first.get("workflow_node_id", ""),
                "run_ids": sorted({str(item["run_id"]) for item in owner_records}),
            }
        )
    _write_json_file(
        root / "index.json",
        {
            "capture_layer": "langchain.on_chat_model_start",
            "request_count": len(records),
            "owners": owners,
        },
    )


def _write_event_stream_files(
    root: Path,
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for record in records:
        method = str(record["method"])
        grouped.setdefault(method, []).append(record)

    channels: list[dict[str, object]] = []
    for method, method_records in sorted(grouped.items()):
        filename = f"{quote(method, safe='-_.')}.jsonl"
        _write_jsonl_file(root / filename, method_records)
        channels.append(
            {
                "method": method,
                "file": filename,
                "event_count": len(method_records),
                "first_seq": int(method_records[0]["seq"]),
                "last_seq": int(method_records[-1]["seq"]),
            }
        )
    return channels


def _event_stream_manifest(
    channels_by_run: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    return {
        "available": bool(channels_by_run),
        "api_version": "v3",
        "capture_condition": "workflow_debug_capture_enabled",
        "capture_point": "post_transformer_protocol_event",
        "directory": "event-streams/",
        "channels_by_run": channels_by_run,
    }


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


class WorkflowDiagnosticExportService:
    """Own temporary Workflow diagnostic archives and their cleanup."""

    def __init__(
        self,
        lifecycle_service: WorkflowLifecycleService,
        workflow_checkpoints: WorkflowCheckpointService,
        runtime_diagnostics: RuntimeDiagnostics,
        export_temp_root: Path,
    ) -> None:
        self._lifecycle = lifecycle_service
        self._checkpoints = workflow_checkpoints
        self._diagnostics = runtime_diagnostics
        self._export_temp_root = export_temp_root

    def _new_export(self) -> tuple[Path, Path, Path]:
        self._export_temp_root.mkdir(parents=True, exist_ok=True)
        export_root = Path(
            tempfile.mkdtemp(
                prefix="workflow-diagnostic-",
                dir=self._export_temp_root,
            )
        )
        return export_root, export_root / "content", export_root / "diagnostic.zip"

    def _diagnostics_for(
        self,
        lifecycle_id: str,
        *,
        run_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            dict(entry)
            for entry in self._diagnostics.snapshot()["entries"]
            if entry.get("lifecycle_id") == lifecycle_id
            and (run_id is None or entry.get("run_id") == run_id)
        ]

    def _diagnostic_details(
        self,
        diagnostics: list[dict[str, object]],
    ) -> list[tuple[Path, str]]:
        result: list[tuple[Path, str]] = []
        for entry in diagnostics:
            diagnostic_id = str(entry["diagnostic_id"])
            path = self._diagnostics.detail_path(diagnostic_id)
            if path is not None:
                result.append((path, f"diagnostics/{diagnostic_id}.log"))
        return result

    async def _checkpoint_history(
        self,
        checkpoint_thread_id: str,
        *,
        lifecycle_id: str,
        run_id: str,
    ) -> AsyncIterator[dict[str, object]]:
        try:
            async for item in self._checkpoints.iter_checkpoint_history(
                checkpoint_thread_id,
                include_state=True,
            ):
                yield item
        except Exception as exc:
            raise WorkflowDiagnosticCheckpointError(
                exc,
                lifecycle_id=lifecycle_id,
                run_id=run_id,
                checkpoint_thread_id=checkpoint_thread_id,
            ) from exc

    @staticmethod
    def _manifest(
        *,
        scope: str,
        captured_at: str,
        lifecycle_id: str,
        last_event_sequence: int,
        event_streams: dict[str, list[dict[str, object]]],
        details: dict[str, object],
    ) -> dict[str, object]:
        return {
            "format": "agent-shell-run-history-v3",
            "scope": scope,
            "captured_at": captured_at,
            "lifecycle_id": lifecycle_id,
            **details,
            "last_event_sequence": last_event_sequence,
            "includes": {
                key: bool(event_streams) if key == "v3_event_streams" else True
                for key in sorted(EXPORT_SECTIONS)
            },
            "event_streams": _event_stream_manifest(event_streams),
            "diagnostic_details_included": True,
            "limitations": list(EXPORT_LIMITATIONS),
        }

    async def _write_common_content(
        self,
        content_root: Path,
        *,
        lifecycle_id: str,
        run_id: str | None,
        metadata_files: dict[str, object],
        model_requests: list[dict[str, object]],
        diagnostics: list[dict[str, object]],
        store_summary: dict[str, object],
    ) -> None:
        for filename, value in metadata_files.items():
            await asyncio.to_thread(_write_json_file, content_root / filename, value)
        await asyncio.to_thread(
            _write_json_file,
            content_root / "input.json",
            await self._lifecycle.input_record(lifecycle_id),
        )
        await asyncio.to_thread(
            _write_jsonl_file,
            content_root / "agent-invocations.jsonl",
            await self._lifecycle.invocation_artifacts(
                lifecycle_id,
                run_id=run_id,
            ),
        )
        await asyncio.to_thread(
            _write_model_request_files,
            content_root / "model-requests",
            model_requests,
        )
        await asyncio.to_thread(
            _write_jsonl_file,
            content_root / "background-tasks.jsonl",
            await self._lifecycle.task_records(lifecycle_id, run_id=run_id),
        )
        await asyncio.to_thread(
            _write_json_file,
            content_root / "store-summary.json",
            store_summary,
        )
        await asyncio.to_thread(
            _write_jsonl_file,
            content_root / "store-payloads.jsonl",
            await self._lifecycle.store_records(lifecycle_id, run_id=run_id),
        )
        await asyncio.to_thread(
            _write_jsonl_file,
            content_root / "diagnostics.jsonl",
            diagnostics,
        )

    async def export_lifecycle(
        self,
        lifecycle_id: str,
        *,
        record: dict[str, object],
        summary: dict[str, object],
    ) -> WorkflowDiagnosticArchive:
        captured_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        runs = self._lifecycle.runs(lifecycle_id)
        model_requests = self._lifecycle.model_requests(lifecycle_id)
        diagnostics = self._diagnostics_for(lifecycle_id)
        store_summary = await self._lifecycle.artifact_summary(lifecycle_id)
        export_root, content_root, archive_path = self._new_export()
        try:
            last_event_sequence = await asyncio.to_thread(
                _write_event_pages,
                content_root / "events.jsonl",
                self._lifecycle,
                lifecycle_id,
                None,
            )
            event_streams: dict[str, list[dict[str, object]]] = {}
            for run in runs:
                run_id = str(run["run_id"])
                protocol_events = self._lifecycle.protocol_events(
                    lifecycle_id,
                    run_id=run_id,
                )
                if protocol_events:
                    event_streams[run_id] = await asyncio.to_thread(
                        _write_event_stream_files,
                        content_root / "event-streams" / _path_segment(run_id),
                        protocol_events,
                    )
                checkpoint_thread_id = run.get("checkpoint_thread_id")
                if checkpoint_thread_id is None:
                    continue
                await _write_async_jsonl_file(
                    content_root / "checkpoints" / f"{run_id}.jsonl",
                    self._checkpoint_history(
                        str(checkpoint_thread_id),
                        lifecycle_id=lifecycle_id,
                        run_id=run_id,
                    ),
                )
            manifest = self._manifest(
                scope="lifecycle",
                captured_at=captured_at,
                lifecycle_id=lifecycle_id,
                last_event_sequence=last_event_sequence,
                event_streams=event_streams,
                details={
                    "lifecycle_status": record.get("lifecycle_status", "active"),
                    "observation_status": summary["observation_status"],
                },
            )
            await self._write_common_content(
                content_root,
                lifecycle_id=lifecycle_id,
                run_id=None,
                metadata_files={
                    "manifest.json": manifest,
                    "lifecycle.json": summary,
                    "runs.json": runs,
                },
                model_requests=model_requests,
                diagnostics=diagnostics,
                store_summary=store_summary,
            )
            await asyncio.to_thread(
                _build_zip,
                content_root,
                archive_path,
                self._diagnostic_details(diagnostics),
            )
        except BaseException:
            shutil.rmtree(export_root, ignore_errors=True)
            raise
        return WorkflowDiagnosticArchive(
            path=archive_path,
            filename=f"agent-shell-lifecycle-{lifecycle_id}.zip",
            _export_root=export_root,
        )

    async def export_run(
        self,
        lifecycle_id: str,
        *,
        run: dict[str, object],
    ) -> WorkflowDiagnosticArchive:
        run_id = str(run["run_id"])
        model_requests = self._lifecycle.model_requests(
            lifecycle_id,
            run_id=run_id,
        )
        diagnostics = self._diagnostics_for(lifecycle_id, run_id=run_id)
        export_root, content_root, archive_path = self._new_export()
        try:
            last_event_sequence = await asyncio.to_thread(
                _write_event_pages,
                content_root / "events.jsonl",
                self._lifecycle,
                lifecycle_id,
                run_id,
            )
            protocol_events = self._lifecycle.protocol_events(
                lifecycle_id,
                run_id=run_id,
            )
            event_stream_channels = (
                await asyncio.to_thread(
                    _write_event_stream_files,
                    content_root / "event-streams",
                    protocol_events,
                )
                if protocol_events
                else []
            )
            event_streams = (
                {run_id: event_stream_channels} if event_stream_channels else {}
            )
            checkpoint_path = content_root / "checkpoints.jsonl"
            checkpoint_thread_id = run.get("checkpoint_thread_id")
            if checkpoint_thread_id is not None:
                await _write_async_jsonl_file(
                    checkpoint_path,
                    self._checkpoint_history(
                        str(checkpoint_thread_id),
                        lifecycle_id=lifecycle_id,
                        run_id=run_id,
                    ),
                )
            else:
                await asyncio.to_thread(
                    checkpoint_path.parent.mkdir,
                    parents=True,
                    exist_ok=True,
                )
                await asyncio.to_thread(checkpoint_path.write_bytes, b"")
            manifest = self._manifest(
                scope="run",
                captured_at=datetime.now(timezone.utc).isoformat(
                    timespec="milliseconds"
                ),
                lifecycle_id=lifecycle_id,
                last_event_sequence=last_event_sequence,
                event_streams=event_streams,
                details={
                    "run_id": run_id,
                    "run_status": run["status"],
                    "observation_status": run["observation_status"],
                    "checkpoint_thread_id": checkpoint_thread_id,
                },
            )
            await self._write_common_content(
                content_root,
                lifecycle_id=lifecycle_id,
                run_id=run_id,
                metadata_files={
                    "manifest.json": manifest,
                    "run.json": run,
                },
                model_requests=model_requests,
                diagnostics=diagnostics,
                store_summary=await self._lifecycle.artifact_summary(lifecycle_id),
            )
            await asyncio.to_thread(
                _build_zip,
                content_root,
                archive_path,
                self._diagnostic_details(diagnostics),
            )
        except BaseException:
            shutil.rmtree(export_root, ignore_errors=True)
            raise
        return WorkflowDiagnosticArchive(
            path=archive_path,
            filename=f"agent-shell-run-{run_id}.zip",
            _export_root=export_root,
        )


__all__ = [
    "WorkflowDiagnosticArchive",
    "WorkflowDiagnosticCheckpointError",
    "WorkflowDiagnosticExportService",
]
