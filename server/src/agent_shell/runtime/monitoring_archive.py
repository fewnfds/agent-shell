from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Literal, TypeVar
from zipfile import ZIP_DEFLATED, ZipFile

from agent_shell.runtime.monitoring_read_service import (
    MonitoringLifecycleNotFound,
    MonitoringReadService,
)
from agent_shell.storage.runtime_monitoring_queries import (
    RuntimeMonitoringQueryStore,
)


ArchiveScope = Literal["lifecycle", "run"]
ARCHIVE_SCHEMA = "agent-shell.runtime-monitoring-archive.v1"

# This bounds each SQLite read and JSONL append. The keyset loop keeps reading
# through the frozen high-water mark, so it is not an output limit.
_READ_BATCH_ROWS = 1000
_BlockingResult = TypeVar("_BlockingResult")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _filename_segment(value: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9._-]", "_", value)
    return segment if segment not in {"", ".", ".."} else "unknown"


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _json_line(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _create_jsonl(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def _append_jsonl(path: Path, values: Iterable[object]) -> None:
    with path.open("ab") as stream:
        for value in values:
            stream.write(_json_line(value))


def _zip_directory(source: Path, destination: Path) -> None:
    with ZipFile(
        destination,
        "w",
        compression=ZIP_DEFLATED,
        allowZip64=True,
    ) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())


async def _finish_cancelled_worker(worker: asyncio.Task[Any]) -> None:
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            continue
        except BaseException:
            break
    if not worker.cancelled():
        try:
            worker.result()
        except BaseException:
            pass


async def _run_blocking(
    call: Callable[..., _BlockingResult],
    /,
    *args: Any,
    **kwargs: Any,
) -> _BlockingResult:
    worker = asyncio.create_task(asyncio.to_thread(call, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        await _finish_cancelled_worker(worker)
        raise


async def _create_temporary_root(parent: Path) -> Path:
    await _run_blocking(parent.mkdir, parents=True, exist_ok=True)
    worker = asyncio.create_task(
        asyncio.to_thread(
            tempfile.mkdtemp,
            prefix=".runtime-monitoring-archive-",
            dir=parent,
        )
    )
    try:
        return Path(await asyncio.shield(worker))
    except asyncio.CancelledError:
        await _finish_cancelled_worker(worker)
        if not worker.cancelled():
            try:
                created = Path(worker.result())
            except BaseException:
                pass
            else:
                await _run_blocking(shutil.rmtree, created, ignore_errors=True)
        raise


@dataclass(frozen=True, slots=True)
class RuntimeMonitoringArchive:
    path: Path
    filename: str
    _temporary_root: Path = field(repr=False)

    def release(self) -> None:
        shutil.rmtree(self._temporary_root, ignore_errors=True)


class RuntimeMonitoringArchiveService:
    """Materialize one bounded download from existing monitoring owners."""

    def __init__(
        self,
        reads: MonitoringReadService,
        queries: RuntimeMonitoringQueryStore,
        temporary_root: Path,
    ) -> None:
        self._reads = reads
        self._queries = queries
        self._temporary_root = temporary_root

    async def prepare_lifecycle(
        self,
        lifecycle_id: str,
    ) -> RuntimeMonitoringArchive:
        return await self._prepare(
            lifecycle_id,
            scope="lifecycle",
            run_id=None,
        )

    async def prepare_run(
        self,
        lifecycle_id: str,
        run_id: str,
    ) -> RuntimeMonitoringArchive:
        return await self._prepare(
            lifecycle_id,
            scope="run",
            run_id=run_id,
        )

    async def _prepare(
        self,
        lifecycle_id: str,
        *,
        scope: ArchiveScope,
        run_id: str | None,
    ) -> RuntimeMonitoringArchive:
        snapshot = await self._reads.application_query(
            lambda: self._reads.snapshot(
                lifecycle_id,
                scope=scope,
                selector_id=run_id,
            )
        )
        runs = snapshot["runs"]
        assert isinstance(runs, list)
        run_ids = [str(run["run_id"]) for run in runs]
        high_waters = await self._reads.application_query(
            lambda: self._queries.archive_high_waters(lifecycle_id, run_ids)
        )
        cut_at = _now()

        export_root = await _create_temporary_root(self._temporary_root)
        content_root = export_root / "content"
        archive_path = export_root / "archive.zip"
        identity = run_id if scope == "run" and run_id is not None else lifecycle_id
        prepared = RuntimeMonitoringArchive(
            path=archive_path,
            filename=(
                f"runtime-monitoring-{scope}-{_filename_segment(identity)}.zip"
            ),
            _temporary_root=export_root,
        )

        try:
            await _run_blocking(
                _write_json,
                content_root / "lifecycle.json",
                {
                    "read_at": snapshot["read_at"],
                    "lifecycle": snapshot["lifecycle"],
                    "summary": snapshot["summary"],
                    "forest": snapshot["forest"],
                },
            )
            run_manifests: list[dict[str, object]] = []
            for index, run in enumerate(runs, start=1):
                assert isinstance(run, dict)
                run_manifest = await self._write_run(
                    content_root,
                    directory=f"runs/{index:04d}",
                    lifecycle_id=lifecycle_id,
                    run=run,
                    snapshot_read_at=str(snapshot["read_at"]),
                    high_waters=high_waters[str(run["run_id"])],
                )
                run_manifests.append(run_manifest)

            exists = await self._reads.application_query(
                lambda: self._queries.lifecycle(lifecycle_id)
            )
            if exists is None or exists.get("lifecycle_status") in {
                "deleting",
                "purge_pending",
            }:
                raise MonitoringLifecycleNotFound(lifecycle_id)

            completed_at = _now()
            await _run_blocking(
                _write_json,
                content_root / "manifest.json",
                {
                    "schema": ARCHIVE_SCHEMA,
                    "scope": scope,
                    "created_at": cut_at,
                    "completed_at": completed_at,
                    "lifecycle_id": lifecycle_id,
                    "selected_run_id": run_id,
                    "active_snapshot": any(
                        run.get("status") in {"pending", "running"}
                        for run in runs
                    ),
                    "snapshot_semantics": (
                        "Run membership and record sequences are bounded at "
                        "archive start; mutable rows, State, and Store artifacts "
                        "retain their own read times."
                    ),
                    "runs": run_manifests,
                },
            )
            await _run_blocking(_zip_directory, content_root, archive_path)
            return prepared
        except BaseException:
            await _run_blocking(prepared.release)
            raise

    async def _write_run(
        self,
        content_root: Path,
        *,
        directory: str,
        lifecycle_id: str,
        run: dict[str, object],
        snapshot_read_at: str,
        high_waters: dict[str, int],
    ) -> dict[str, object]:
        run_id = str(run["run_id"])
        run_root = content_root / directory
        await _run_blocking(
            _write_json,
            run_root / "run.json",
            {"read_at": snapshot_read_at, "run": run},
        )

        graph = await self._reads.application_query(
            lambda: self._reads.graph(lifecycle_id, run_id)
        )
        await _run_blocking(_write_json, run_root / "graph.json", graph)

        invocation_nodes: dict[str, tuple[int, str]] = {}
        node_availability = self._partition_availability(run, "node")
        resources: dict[str, dict[str, object]] = {
            "graph": {
                "path": f"{directory}/graph.json",
                "availability": graph["availability"],
                "read_at": graph["read_at"],
            }
        }
        partitions = (
            ("node", "node-attempts.jsonl"),
            ("protocol", "protocol-events.jsonl"),
            ("model", "model-requests.jsonl"),
            ("command", "command-observations.jsonl"),
        )
        for partition, filename in partitions:
            result, partition_invocations = await self._write_partition(
                run_root / filename,
                lifecycle_id=lifecycle_id,
                run_id=run_id,
                partition=partition,
                through_sequence=high_waters[partition],
                source_availability=self._partition_availability(run, partition),
            )
            result["path"] = f"{directory}/{filename}"
            resources[partition] = result
            if partition == "node":
                invocation_nodes = partition_invocations
                node_availability = str(result["availability"])

        state = await self._reads.latest_state(lifecycle_id, run_id)
        await _run_blocking(_write_json, run_root / "state.json", state)
        resources["state"] = {
            "path": f"{directory}/state.json",
            "availability": state["availability"],
            "read_at": state["read_at"],
        }

        agent_index = await self._write_agent_invocations(
            run_root / "agent-invocations",
            directory=f"{directory}/agent-invocations",
            lifecycle_id=lifecycle_id,
            run_id=run_id,
            graph=graph,
            invocation_nodes=invocation_nodes,
            node_availability=node_availability,
            run_status=str(run["status"]),
        )
        resources["agent_invocations"] = {
            "path": f"{directory}/agent-invocations/index.json",
            "availability": agent_index["availability"],
            "count": len(agent_index["items"]),
        }
        return {
            "run_id": run_id,
            "directory": directory,
            "status": run["status"],
            "high_water": high_waters,
            "resources": resources,
        }

    async def _write_partition(
        self,
        path: Path,
        *,
        lifecycle_id: str,
        run_id: str,
        partition: str,
        through_sequence: int,
        source_availability: str,
    ) -> tuple[dict[str, object], dict[str, tuple[int, str]]]:
        await _run_blocking(_create_jsonl, path)
        after_sequence = 0
        count = 0
        read_failed = False
        invocation_nodes: dict[str, tuple[int, str]] = {}
        while after_sequence < through_sequence:
            try:
                items = await self._reads.application_query(
                    lambda: self._archive_batch(
                        lifecycle_id,
                        run_id,
                        partition=partition,
                        after_sequence=after_sequence,
                        through_sequence=through_sequence,
                    )
                )
            except Exception:
                read_failed = True
                break
            if not items:
                break
            await _run_blocking(_append_jsonl, path, items)
            count += len(items)
            if partition == "node":
                for item in items:
                    invocation_id = str(item["invocation_id"])
                    invocation_nodes.setdefault(
                        invocation_id,
                        (int(item["sequence"]), str(item["workflow_node_id"])),
                    )
            next_sequence = int(items[-1]["sequence"])
            if next_sequence <= after_sequence:
                raise RuntimeError("archive keyset query did not advance")
            after_sequence = next_sequence

        availability = source_availability
        if read_failed:
            availability = "partial" if count else "unavailable"
        return (
            {
                "availability": availability,
                "count": count,
                "through_sequence": through_sequence,
            },
            invocation_nodes,
        )

    def _archive_batch(
        self,
        lifecycle_id: str,
        run_id: str,
        *,
        partition: str,
        after_sequence: int,
        through_sequence: int,
    ) -> list[dict[str, object]]:
        arguments = {
            "after_sequence": after_sequence,
            "through_sequence": through_sequence,
            "batch_size": _READ_BATCH_ROWS,
        }
        if partition == "node":
            return self._queries.archive_node_attempts(
                lifecycle_id,
                run_id,
                **arguments,
            )
        if partition == "protocol":
            return self._queries.archive_protocol_events(
                lifecycle_id,
                run_id,
                **arguments,
            )
        if partition == "model":
            return self._queries.archive_model_requests(
                lifecycle_id,
                run_id,
                **arguments,
            )
        if partition == "command":
            return self._queries.archive_command_observations(
                lifecycle_id,
                run_id,
                **arguments,
            )
        raise ValueError("unknown runtime monitoring archive partition")

    async def _write_agent_invocations(
        self,
        root: Path,
        *,
        directory: str,
        lifecycle_id: str,
        run_id: str,
        graph: dict[str, object],
        invocation_nodes: dict[str, tuple[int, str]],
        node_availability: str,
        run_status: str,
    ) -> dict[str, object]:
        agent_node_ids = self._agent_node_ids(graph)
        records: list[dict[str, object]] = []
        selected = sorted(
            (
                (sequence, invocation_id, node_id)
                for invocation_id, (sequence, node_id) in invocation_nodes.items()
                if node_id in agent_node_ids
            ),
            key=lambda item: (item[0], item[1]),
        )
        for index, (_sequence, invocation_id, node_id) in enumerate(
            selected,
            start=1,
        ):
            filename = f"{index:04d}.json"
            try:
                response = await self._reads.agent_invocation(
                    lifecycle_id,
                    run_id,
                    invocation_id,
                )
            except Exception:
                response = {
                    "availability": "unavailable",
                    "read_at": _now(),
                    "workflow_node_id": node_id,
                    "artifact": None,
                }
            await _run_blocking(_write_json, root / filename, response)
            records.append(
                {
                    "invocation_id": invocation_id,
                    "workflow_node_id": node_id,
                    "path": f"{directory}/{filename}",
                    "availability": response["availability"],
                    "read_at": response["read_at"],
                }
            )

        availability = self._agent_index_availability(
            graph_availability=str(graph["availability"]),
            has_agent_nodes=bool(agent_node_ids),
            node_availability=node_availability,
            records=records,
            run_status=run_status,
        )
        index = {
            "availability": availability,
            "read_at": _now(),
            "items": records,
        }
        await _run_blocking(_write_json, root / "index.json", index)
        return index

    @staticmethod
    def _partition_availability(run: dict[str, object], partition: str) -> str:
        monitoring = run.get("monitoring")
        if not isinstance(monitoring, dict):
            return "partial"
        return str(monitoring[partition])

    @staticmethod
    def _agent_node_ids(graph: dict[str, object]) -> set[str]:
        graph_record = graph.get("graph")
        document = (
            graph_record.get("document")
            if isinstance(graph_record, dict)
            else None
        )
        definition = document.get("definition") if isinstance(document, dict) else None
        nodes = definition.get("nodes") if isinstance(definition, dict) else None
        return {
            str(node["id"])
            for node in nodes or ()
            if isinstance(node, dict)
            and node.get("type") == "agent"
            and node.get("id")
        }

    @staticmethod
    def _agent_index_availability(
        *,
        graph_availability: str,
        has_agent_nodes: bool,
        node_availability: str,
        records: list[dict[str, object]],
        run_status: str,
    ) -> str:
        if graph_availability == "unavailable":
            return "unavailable"
        if graph_availability == "partial":
            return "partial"
        if not has_agent_nodes:
            return "not_applicable"
        if node_availability == "unavailable":
            return "unavailable"
        if node_availability == "partial":
            return "partial"
        statuses = {str(record["availability"]) for record in records}
        if "unavailable" in statuses or "partial" in statuses:
            return "partial"
        if "pending" in statuses or (
            not records and run_status in {"pending", "running"}
        ):
            return "pending"
        return "available"


__all__ = [
    "ARCHIVE_SCHEMA",
    "RuntimeMonitoringArchive",
    "RuntimeMonitoringArchiveService",
]
