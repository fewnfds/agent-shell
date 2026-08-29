from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4
from weakref import WeakValueDictionary

from langgraph.store.base import PutOp
from langgraph.store.sqlite import AsyncSqliteStore

from agent_shell.contracts import FilesystemBlock
from agent_shell.runtime.input_messages import client_messages_sha
from agent_shell.storage.database import SQLiteDatabase, SQLiteFile
from agent_shell.storage.owned_paths import resolve_data_root_relative_path
from agent_shell.storage.workflow_lifecycles import WorkflowLifecycleStore
from agent_shell.storage.workflow_run_history import WorkflowRunHistoryStore


LIFECYCLE_NAMESPACE_ROOT = "workflow-lifecycle"
LIFECYCLE_INPUT_KEY = "request"
LIFECYCLE_FILESYSTEM_RECORD_VERSION = 1


def lifecycle_input_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    if not lifecycle_id:
        raise ValueError("lifecycle_id must not be empty")
    return (LIFECYCLE_NAMESPACE_ROOT, lifecycle_id, "input")


def lifecycle_tasks_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    if not lifecycle_id:
        raise ValueError("lifecycle_id must not be empty")
    return (LIFECYCLE_NAMESPACE_ROOT, lifecycle_id, "tasks")


def lifecycle_invocations_namespace(
    lifecycle_id: str,
    run_id: str,
) -> tuple[str, str, str, str]:
    if not lifecycle_id:
        raise ValueError("lifecycle_id must not be empty")
    if not run_id:
        raise ValueError("run_id must not be empty")
    return (LIFECYCLE_NAMESPACE_ROOT, lifecycle_id, "invocations", run_id)


def lifecycle_filesystem_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    if not lifecycle_id:
        raise ValueError("lifecycle_id must not be empty")
    return (LIFECYCLE_NAMESPACE_ROOT, lifecycle_id, "filesystem")


class WorkflowLifecycleService:
    """Own cross-run Lifecycle data and authoritative parent Run status."""

    def __init__(
        self,
        database: SQLiteDatabase,
        *,
        store_database: SQLiteFile,
        data_root: Path | None = None,
    ) -> None:
        if database.path.resolve() == store_database.path.resolve():
            raise ValueError(
                "the Workflow Store must use a dedicated SQLite database file"
            )
        self._database_path = database.path
        self._store_database_path = store_database.path
        self._index = WorkflowLifecycleStore(database)
        self._history = WorkflowRunHistoryStore(database)
        self._data_root = (
            data_root.resolve()
            if data_root is not None
            else self._database_path.resolve().parent.parent
        )
        self._context: AbstractAsyncContextManager[AsyncSqliteStore] | None = None
        self._store: AsyncSqliteStore | None = None
        self._filesystem_lock = asyncio.Lock()
        self._mutation_locks: WeakValueDictionary[str, asyncio.Lock] = (
            WeakValueDictionary()
        )

    @property
    def store(self) -> AsyncSqliteStore:
        if self._store is None:
            raise RuntimeError("the Workflow lifecycle Store is not started")
        return self._store

    async def start(self) -> None:
        context = AsyncSqliteStore.from_conn_string(str(self._store_database_path))
        store: AsyncSqliteStore | None = None
        try:
            store = await context.__aenter__()
            await store.setup()
            self._store = store
            await self._cancel_interrupted_parent_runs()
        except BaseException as exc:
            self._store = None
            if store is not None:
                await context.__aexit__(type(exc), exc, exc.__traceback__)
            raise
        self._context = context

    async def _cancel_interrupted_parent_runs(self) -> int:
        finished_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        self._history.interrupt_active(finished_at=finished_at)
        return self._index.cancel_running(finished_at=finished_at)

    async def close(self) -> None:
        if self._context is not None:
            await self._context.__aexit__(None, None, None)
        self._context = None
        self._store = None

    async def create(
        self,
        messages: list[dict[str, Any]],
        *,
        request_id: str,
        run_id: str,
        checkpoint_thread_id: str | None,
        workflow_id: str,
        workflow_name: str,
    ) -> str:
        lifecycle_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        metadata = {
            "request_id": request_id,
            "parent_run_id": run_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "created_at": created_at,
        }
        record = {
            "lifecycle_id": lifecycle_id,
            **metadata,
            "lifecycle_status": "active",
            "parent_status": "running",
            "messages_sha": client_messages_sha(messages),
            "message_count": len(messages),
        }
        await self.store.aput(
            lifecycle_input_namespace(lifecycle_id),
            LIFECYCLE_INPUT_KEY,
            {
                "messages": deepcopy(messages),
                "messages_sha": client_messages_sha(messages),
                "metadata": metadata,
            },
            index=False,
        )
        try:
            self._index.create(record)
        except BaseException:
            await self.store.adelete(
                lifecycle_input_namespace(lifecycle_id),
                LIFECYCLE_INPUT_KEY,
            )
            raise
        try:
            self._history.create_run(
                {
                    "run_id": run_id,
                    "lifecycle_id": lifecycle_id,
                    "request_id": request_id,
                    "checkpoint_thread_id": checkpoint_thread_id,
                    "run_kind": "workflow",
                    "target_id": workflow_id,
                    "target_name": workflow_name,
                    "run_depth": 0,
                    "created_at": created_at,
                },
                {
                    "lifecycle_id": lifecycle_id,
                    "run_id": run_id,
                    "occurred_at": created_at,
                    "event_type": "run",
                    "phase": "created",
                    "span_id": run_id,
                    "subject_kind": "run",
                    "subject_id": run_id,
                    "subject_name": workflow_name,
                    "status": "pending",
                },
            )
        except Exception:
            # Run history is an observation surface. The lifecycle itself remains
            # usable when its diagnostic index is temporarily unavailable.
            pass
        return lifecycle_id

    @property
    def history(self) -> WorkflowRunHistoryStore:
        return self._history

    def register_run(self, record: dict[str, object]) -> None:
        existing = self._history.get_run(str(record["run_id"]))
        if existing is not None:
            return
        created_at = str(record.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        self._history.create_run(
            {**record, "created_at": created_at},
            {
                "lifecycle_id": record["lifecycle_id"],
                "run_id": record["run_id"],
                "occurred_at": created_at,
                "event_type": "run",
                "phase": "created",
                "span_id": record["run_id"],
                "parent_span_id": record.get("parent_run_id"),
                "subject_kind": "run",
                "subject_id": record["run_id"],
                "subject_name": record["target_name"],
                "status": "pending",
            },
        )

    def start_run(self, run_id: str, *, status: str = "running") -> bool:
        record = self._history.get_run(run_id)
        if record is None:
            return False
        occurred_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        return self._history.start_run(
            run_id,
            {
                "lifecycle_id": str(record["lifecycle_id"]),
                "run_id": run_id,
                "occurred_at": occurred_at,
                "event_type": "run",
                "phase": "started",
                "span_id": run_id,
                "parent_span_id": record.get("parent_run_id"),
                "subject_kind": "run",
                "subject_id": run_id,
                "status": status,
            },
        )

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        error_code: str = "",
        finish_reason: str = "",
        usage: dict[str, int] | None = None,
    ) -> bool:
        record = self._history.get_run(run_id)
        if record is None:
            return False
        finished_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        phase = "cancelled" if status == "cancelled" else "failed" if status in {"failed", "interrupted"} else "completed"
        return self._history.finish_run(
            run_id,
            status=status,
            finished_at=finished_at,
            finish_reason=finish_reason,
            error_code=error_code,
            usage=usage or {},
            event={
                "lifecycle_id": record["lifecycle_id"],
                "run_id": run_id,
                "occurred_at": finished_at,
                "event_type": "run",
                "phase": phase,
                "span_id": run_id,
                "parent_span_id": record.get("parent_run_id"),
                "subject_kind": "run",
                "subject_id": run_id,
                "subject_name": record["target_name"],
                "status": status,
                "error_code": error_code,
                "usage": usage or {},
            },
        )

    def append_run_event(self, event: dict[str, object]) -> int:
        return self._history.append_event(event)

    def append_protocol_event(
        self,
        lifecycle_id: str,
        run_id: str,
        event: dict[str, object],
    ) -> None:
        self._history.append_protocol_event(lifecycle_id, run_id, event)

    def append_model_request(self, record: dict[str, object]) -> None:
        self._history.append_model_request(record)

    def mark_run_observation_partial(self, run_id: str) -> None:
        self._history.mark_partial(run_id)

    def runs(self, lifecycle_id: str) -> list[dict[str, object]]:
        return self._history.list_runs(lifecycle_id)

    def events(
        self,
        lifecycle_id: str,
        *,
        run_id: str | None = None,
        node_invocation_id: str | None = None,
        event_type: str | None = None,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> list[dict[str, object]]:
        return self._history.list_events(
            lifecycle_id,
            run_id=run_id,
            node_invocation_id=node_invocation_id,
            event_type=event_type,
            after_sequence=after_sequence,
            limit=limit,
        )

    def model_requests(
        self,
        lifecycle_id: str,
        *,
        run_id: str | None = None,
    ) -> list[dict[str, object]]:
        return self._history.list_model_requests(lifecycle_id, run_id=run_id)

    def protocol_events(
        self,
        lifecycle_id: str,
        *,
        run_id: str,
    ) -> list[dict[str, object]]:
        return self._history.list_protocol_events(lifecycle_id, run_id=run_id)

    def run_summary(self, lifecycle_id: str) -> dict[str, object]:
        return self._history.summary(lifecycle_id)

    def event_count(self, lifecycle_id: str, *, run_id: str | None = None) -> int:
        return self._history.count_events(lifecycle_id, run_id=run_id)

    @asynccontextmanager
    async def exclusive_mutation(self, lifecycle_id: str) -> AsyncIterator[None]:
        """Serialize mutations for one Lifecycle without blocking unrelated Runs."""

        if not lifecycle_id:
            raise ValueError("lifecycle_id must not be empty")
        lock = self._mutation_locks.get(lifecycle_id)
        if lock is None:
            lock = asyncio.Lock()
            self._mutation_locks[lifecycle_id] = lock
        async with lock:
            yield

    async def finish_parent(self, lifecycle_id: str, status: str) -> None:
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("invalid Workflow lifecycle parent status")
        async with self.exclusive_mutation(lifecycle_id):
            record = await self.record(lifecycle_id)
            if record is None:
                raise RuntimeError("the Workflow lifecycle does not exist")
            if record.get("lifecycle_status", "active") == "deleting":
                raise RuntimeError("the Workflow lifecycle is being deleted")
            updated = self._index.finish_parent(
                lifecycle_id,
                status=status,
                finished_at=datetime.now(timezone.utc).isoformat(
                    timespec="milliseconds"
                ),
            )
            if not updated:
                raise RuntimeError("the Workflow lifecycle does not exist")

    async def mark_deleting(self, lifecycle_id: str) -> dict[str, Any]:
        record = await self.record(lifecycle_id)
        if record is None:
            raise RuntimeError("the Workflow lifecycle does not exist")
        if record.get("lifecycle_status", "active") == "deleting":
            return record
        deleting = {
            **record,
            "lifecycle_status": "deleting",
            "deletion_started_at": datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ),
        }
        self._index.mark_deleting(
            lifecycle_id,
            started_at=str(deleting["deletion_started_at"]),
        )
        return deleting

    async def input_record(self, lifecycle_id: str) -> dict[str, Any] | None:
        item = await self.store.aget(
            lifecycle_input_namespace(lifecycle_id),
            LIFECYCLE_INPUT_KEY,
        )
        return deepcopy(item.value) if item is not None else None

    async def messages(self, lifecycle_id: str) -> list[dict[str, Any]]:
        record = await self.input_record(lifecycle_id)
        messages = record.get("messages") if record is not None else None
        if not isinstance(messages, list):
            raise RuntimeError("the Workflow lifecycle input does not exist")
        return deepcopy(messages)

    async def invocation_artifacts(
        self,
        lifecycle_id: str,
        *,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        namespace = (
            lifecycle_invocations_namespace(lifecycle_id, run_id)
            if run_id is not None
            else (LIFECYCLE_NAMESPACE_ROOT, lifecycle_id, "invocations")
        )
        items = await self._search_all(namespace)
        artifacts: list[dict[str, Any]] = []
        for item in items:
            value = item.value
            if not isinstance(value, dict):
                continue
            artifacts.append(
                {
                    "run_id": str(item.namespace[3])
                    if len(item.namespace) > 3
                    else "",
                    "key": str(item.key),
                    "artifact": deepcopy(value),
                }
            )
        return artifacts

    async def task_records(
        self,
        lifecycle_id: str,
        *,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        items = await self._search_all(lifecycle_tasks_namespace(lifecycle_id))
        records: list[dict[str, Any]] = []
        for item in items:
            value = item.value
            if not isinstance(value, dict):
                continue
            if run_id is not None and run_id not in {
                str(value.get("launcher_run_id", "")),
                str(value.get("child_run_id", "")),
            }:
                continue
            records.append(deepcopy(value))
        return records

    async def store_records(
        self,
        lifecycle_id: str,
        *,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        items = await self._search_all((LIFECYCLE_NAMESPACE_ROOT, lifecycle_id))
        records: list[dict[str, Any]] = []
        for item in items:
            namespace = tuple(str(part) for part in item.namespace)
            if run_id is not None and len(namespace) >= 4:
                if namespace[2] == "invocations" and namespace[3] != run_id:
                    continue
            records.append(
                {
                    "namespace": list(item.namespace),
                    "key": str(item.key),
                    "value": deepcopy(item.value),
                }
            )
        return records

    async def _search_all(self, namespace: tuple[str, ...]) -> list[Any]:
        items: list[Any] = []
        offset = 0
        while True:
            page = await self.store.asearch(namespace, limit=100, offset=offset)
            items.extend(page)
            if len(page) < 100:
                return items
            offset += len(page)

    async def list_records_page(
        self,
        *,
        limit: int,
        offset: int,
        query: str = "",
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one SQL-ordered page and its matching row count."""

        records, total = self._index.list_page(
            limit=limit,
            offset=offset,
            query=query,
        )
        return [deepcopy(record) for record in records], total

    async def matching_record_ids(self, *, query: str = "") -> list[str]:
        return self._index.list_matching_ids(query=query)

    async def record(self, lifecycle_id: str) -> dict[str, Any] | None:
        record = self._index.get(lifecycle_id)
        return deepcopy(record) if record is not None else None

    async def store_item_count(self, lifecycle_id: str) -> int:
        return len(
            await self._search_all((LIFECYCLE_NAMESPACE_ROOT, lifecycle_id))
        )

    async def artifact_summary(self, lifecycle_id: str) -> dict[str, object]:
        items = await self._search_all((LIFECYCLE_NAMESPACE_ROOT, lifecycle_id))
        namespaces: dict[str, int] = {}
        for item in items:
            parts = tuple(str(part) for part in item.namespace)
            kind = parts[2] if len(parts) > 2 else "unknown"
            namespaces[kind] = namespaces.get(kind, 0) + 1
        return {
            "item_count": len(items),
            "namespace_counts": dict(sorted(namespaces.items())),
            "payloads_included": False,
        }

    async def filesystem_summary(self, lifecycle_id: str) -> dict[str, int]:
        items = await self._search_all(lifecycle_filesystem_namespace(lifecycle_id))
        route_count = 0
        dynamic_directory_count = 0
        for item in items:
            mappings = item.value.get("mappings")
            if not isinstance(mappings, list):
                continue
            route_count += len(mappings)
            dynamic_directory_count += sum(
                1
                for mapping in mappings
                if isinstance(mapping, dict)
                and mapping.get("lifecycle_mode") == "dynamic"
            )
        return {
            "filesystem_count": len(items),
            "route_count": route_count,
            "dynamic_directory_count": dynamic_directory_count,
        }

    async def delete(
        self,
        lifecycle_id: str,
        *,
        delete_dynamic_directories: bool,
    ) -> bool:
        record = await self.record(lifecycle_id)
        if record is None:
            return False
        if record.get("lifecycle_status", "active") != "deleting":
            raise RuntimeError("the Workflow lifecycle is not marked for deletion")
        lifecycle_items = await self._search_all(
            (LIFECYCLE_NAMESPACE_ROOT, lifecycle_id)
        )
        if delete_dynamic_directories:
            for item in lifecycle_items:
                if tuple(item.namespace) != lifecycle_filesystem_namespace(
                    lifecycle_id
                ):
                    continue
                mappings = item.value.get("mappings")
                for mapping in mappings if isinstance(mappings, list) else ():
                    if (
                        not isinstance(mapping, dict)
                        or mapping.get("lifecycle_mode") != "dynamic"
                    ):
                        continue
                    target_value = mapping.get("resolved_local_path")
                    root_value = mapping.get("configured_root")
                    if not isinstance(target_value, str) or not isinstance(
                        root_value, str
                    ):
                        raise RuntimeError(
                            "the managed dynamic directory record is invalid"
                        )
                    target = Path(target_value).resolve()
                    root = Path(root_value).resolve()
                    if (
                        target.parent != root
                        or target.name != f"lifecycle-{lifecycle_id}"
                    ):
                        raise RuntimeError(
                            "the managed dynamic directory target is invalid"
                        )
                    if target.exists():
                        await asyncio.to_thread(shutil.rmtree, target)
        await self.store.abatch(
            [PutOp(tuple(item.namespace), item.key, None) for item in lifecycle_items]
        )
        # Run records/events are owned by this Lifecycle and are deleted with it.
        self._index.delete(lifecycle_id)
        return True

    def _configured_mapping_root(self, local_path: str, path_origin: str) -> Path:
        configured = Path(local_path)
        if path_origin == "absolute":
            if not configured.is_absolute():
                raise ValueError("absolute mapped local_path must be absolute")
            return configured.resolve()
        return resolve_data_root_relative_path(
            self._data_root,
            local_path,
            label="data-root-relative mapped local_path",
        )

    async def resolve_mapped_directories(
        self,
        lifecycle_id: str,
        filesystem_id: str,
        filesystem: FilesystemBlock,
    ) -> dict[str, Path]:
        """Resolve disk routes once per Lifecycle and Filesystem definition."""
        if not filesystem_id:
            raise ValueError("filesystem_id must not be empty")
        namespace = lifecycle_filesystem_namespace(lifecycle_id)
        async with self._filesystem_lock:
            stored = await self.store.aget(namespace, filesystem_id)
            if stored is not None:
                mappings = stored.value.get("mappings")
                if not isinstance(mappings, list):
                    raise RuntimeError("the Workflow lifecycle filesystem record is invalid")
                resolved: dict[str, Path] = {}
                for item in mappings:
                    if not isinstance(item, dict):
                        raise RuntimeError(
                            "the Workflow lifecycle filesystem record is invalid"
                        )
                    virtual_path = item.get("virtual_path")
                    local_path = item.get("resolved_local_path")
                    if not isinstance(virtual_path, str) or not isinstance(
                        local_path, str
                    ):
                        raise RuntimeError(
                            "the Workflow lifecycle filesystem record is invalid"
                        )
                    target = Path(local_path)
                    if item.get("lifecycle_mode") == "dynamic":
                        target.mkdir(exist_ok=True)
                    if not target.is_dir():
                        raise RuntimeError(
                            "a resolved Workflow lifecycle mapped directory is unavailable"
                        )
                    resolved[virtual_path] = target
                return resolved

            records: list[dict[str, str]] = []
            resolved: dict[str, Path] = {}
            resolved_targets: set[str] = set()
            configured_mappings = (
                [
                    (
                        mapping.virtual_path,
                        mapping.local_path,
                        mapping.path_origin,
                        mapping.lifecycle_mode,
                    )
                    for mapping in filesystem.mapped_directories
                ]
                if filesystem.backend_type == "composite"
                else [
                    (
                        "/",
                        filesystem.workspace.local_path,
                        filesystem.workspace.path_origin,
                        "fixed",
                    )
                ]
            )
            for virtual_path, local_path, path_origin, lifecycle_mode in configured_mappings:
                root = self._configured_mapping_root(
                    local_path,
                    path_origin,
                )
                if not root.is_dir():
                    raise ValueError(
                        "configured filesystem root must be an existing directory: "
                        f"{local_path}"
                    )
                target = (
                    root / f"lifecycle-{lifecycle_id}"
                    if lifecycle_mode == "dynamic"
                    else root
                )
                if lifecycle_mode == "dynamic":
                    target.mkdir(exist_ok=True)
                canonical = str(target.resolve()).casefold()
                if canonical in resolved_targets:
                    raise ValueError(
                        "resolved mapped local directories must be unique"
                    )
                resolved_targets.add(canonical)
                resolved[virtual_path] = target.resolve()
                records.append(
                    {
                        "virtual_path": virtual_path,
                        "resolved_local_path": str(target.resolve()),
                        "configured_root": str(root),
                        "path_origin": path_origin,
                        "lifecycle_mode": lifecycle_mode,
                    }
                )
            await self.store.aput(
                namespace,
                filesystem_id,
                {
                    "version": LIFECYCLE_FILESYSTEM_RECORD_VERSION,
                    "filesystem_id": filesystem_id,
                    "mappings": records,
                    "created_at": datetime.now(timezone.utc).isoformat(
                        timespec="milliseconds"
                    ),
                },
                index=False,
            )
            return resolved


__all__ = [
    "LIFECYCLE_INPUT_KEY",
    "LIFECYCLE_FILESYSTEM_RECORD_VERSION",
    "LIFECYCLE_NAMESPACE_ROOT",
    "WorkflowLifecycleService",
    "lifecycle_filesystem_namespace",
    "lifecycle_input_namespace",
    "lifecycle_invocations_namespace",
    "lifecycle_tasks_namespace",
]
