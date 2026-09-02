from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any, Protocol
from uuid import uuid4
from weakref import WeakValueDictionary

from langgraph.store.base import PutOp
from langgraph.store.sqlite import AsyncSqliteStore

from agent_shell.contracts import FilesystemBlock
from agent_shell.runtime.diagnostics import RuntimeDiagnosticContext, RuntimeDiagnostics
from agent_shell.runtime.input_messages import client_messages_sha
from agent_shell.storage.database import SQLiteDatabase, SQLiteFile
from agent_shell.storage.owned_paths import resolve_data_root_relative_path
from agent_shell.storage.runtime_managed_directories import RuntimeManagedDirectoryStore
from agent_shell.storage.runtime_monitoring import RuntimeMonitoringStore
from agent_shell.storage.runtime_registry import RuntimeRegistryStore
from agent_shell.workflow.catalog import node_type_spec
from agent_shell.workflow.contracts import (
    WorkflowGraphDocumentV1,
    workflow_document_sha256,
)


LIFECYCLE_NAMESPACE_ROOT = "workflow-lifecycle"
LIFECYCLE_INPUT_KEY = "request"
LIFECYCLE_FILESYSTEM_RECORD_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


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


class RuntimeCleanupHook(Protocol):
    async def lifecycle_changed(self, lifecycle_id: str) -> None: ...


class WorkflowLifecycleService:
    """Own official Lifecycle Store data and application runtime persistence."""

    def __init__(
        self,
        database: SQLiteDatabase,
        *,
        store_database: SQLiteFile,
        data_root: Path | None = None,
        runtime_diagnostics: RuntimeDiagnostics | None = None,
    ) -> None:
        if database.path.resolve() == store_database.path.resolve():
            raise ValueError(
                "the Workflow Store must use a dedicated SQLite database file"
            )
        self._database_path = database.path
        self._store_database_path = store_database.path
        self._registry = RuntimeRegistryStore(database)
        self._monitoring = RuntimeMonitoringStore(database)
        self._managed_directories = RuntimeManagedDirectoryStore(database)
        self._runtime_diagnostics = runtime_diagnostics
        self._data_root = (
            data_root.resolve()
            if data_root is not None
            else self._database_path.resolve().parent.parent
        )
        self._context: AbstractAsyncContextManager[AsyncSqliteStore] | None = None
        self._store: AsyncSqliteStore | None = None
        self._cleanup_hook: RuntimeCleanupHook | None = None
        self._filesystem_lock = asyncio.Lock()
        self._mutation_locks: WeakValueDictionary[str, asyncio.Lock] = (
            WeakValueDictionary()
        )

    @property
    def store(self) -> AsyncSqliteStore:
        if self._store is None:
            raise RuntimeError("the Workflow lifecycle Store is not started")
        return self._store

    @property
    def registry(self) -> RuntimeRegistryStore:
        return self._registry

    @property
    def monitoring(self) -> RuntimeMonitoringStore:
        return self._monitoring

    @property
    def managed_directories(self) -> RuntimeManagedDirectoryStore:
        return self._managed_directories

    def set_cleanup_hook(self, hook: RuntimeCleanupHook) -> None:
        self._cleanup_hook = hook

    def set_runtime_diagnostics(self, diagnostics: RuntimeDiagnostics) -> None:
        self._runtime_diagnostics = diagnostics

    async def start(self) -> None:
        context = AsyncSqliteStore.from_conn_string(str(self._store_database_path))
        store: AsyncSqliteStore | None = None
        try:
            store = await context.__aenter__()
            await store.setup()
            self._store = store
        except BaseException as exc:
            self._store = None
            if store is not None:
                await context.__aexit__(type(exc), exc, exc.__traceback__)
            raise
        self._context = context

    async def close(self) -> None:
        if self._context is not None:
            await self._context.__aexit__(None, None, None)
        self._context = None
        self._store = None

    def _diagnostic_context(
        self,
        *,
        lifecycle_id: str,
        run_id: str,
        workflow_id: str = "",
        workflow_name: str = "",
    ) -> RuntimeDiagnosticContext:
        return RuntimeDiagnosticContext(
            lifecycle_id=lifecycle_id,
            workflow_run_id=run_id,
            subject_kind="workflow",
            subject_id=workflow_id,
            subject_name=workflow_name,
        )

    def _observation_error(
        self,
        exc: BaseException,
        *,
        code: str,
        lifecycle_id: str,
        run_id: str,
        workflow_id: str = "",
        workflow_name: str = "",
    ) -> None:
        if self._runtime_diagnostics is None:
            return
        self._runtime_diagnostics.observation_error(
            exc,
            code=code,
            component="observability",
            context=self._diagnostic_context(
                lifecycle_id=lifecycle_id,
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
            ),
        )

    @staticmethod
    def _graph_artifact(
        document: WorkflowGraphDocumentV1,
        *,
        lifecycle_id: str,
        run_id: str,
        workflow_id: str,
        workflow_name: str,
        created_at: str,
    ) -> dict[str, object]:
        return {
            "lifecycle_id": lifecycle_id,
            "run_id": run_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "document_sha": workflow_document_sha256(document),
            "document": document.model_dump(mode="json"),
            "created_at": created_at,
        }

    def _initialize_monitoring(
        self,
        *,
        record: dict[str, object],
        document: WorkflowGraphDocumentV1,
    ) -> None:
        lifecycle_id = str(record["lifecycle_id"])
        run_id = str(record["run_id"])
        workflow_id = str(record.get("workflow_id") or record.get("target_id") or "")
        workflow_name = str(
            record.get("workflow_name") or record.get("target_name") or ""
        )
        created_at = str(record["created_at"])
        runtime_kinds = {
            spec.runtime_kind
            for node in document.definition.nodes
            if (spec := node_type_spec(node.type, node.type_version)) is not None
        }
        try:
            self._monitoring.initialize_run(
                lifecycle_id=lifecycle_id,
                run_id=run_id,
                has_executable_nodes=bool(
                    runtime_kinds & {"agent_wrapper", "command_node"}
                ),
                has_model_nodes="agent_wrapper" in runtime_kinds,
                has_command_nodes="command_node" in runtime_kinds,
                created_at=created_at,
            )
        except Exception as exc:
            self._observation_error(
                exc,
                code="runtime_monitoring_registration_failed",
                lifecycle_id=lifecycle_id,
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
            )
            return
        try:
            self._monitoring.save_graph(
                self._graph_artifact(
                    document,
                    lifecycle_id=lifecycle_id,
                    run_id=run_id,
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    created_at=created_at,
                )
            )
        except Exception as exc:
            try:
                self._monitoring.mark_partition(run_id, "graph", "partial")
            except Exception:
                pass
            self._observation_error(
                exc,
                code="runtime_graph_record_failed",
                lifecycle_id=lifecycle_id,
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
            )

    async def create(
        self,
        messages: list[dict[str, Any]],
        *,
        request_id: str,
        run_id: str,
        checkpoint_thread_id: str | None,
        workflow_id: str,
        workflow_name: str,
        workflow_document: WorkflowGraphDocumentV1,
        monitoring_capture_enabled: bool,
    ) -> str:
        lifecycle_id = str(uuid4())
        created_at = _now()
        messages_sha = client_messages_sha(messages)
        metadata = {
            "request_id": request_id,
            "parent_run_id": run_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "created_at": created_at,
        }
        await self.store.aput(
            lifecycle_input_namespace(lifecycle_id),
            LIFECYCLE_INPUT_KEY,
            {
                "messages": deepcopy(messages),
                "messages_sha": messages_sha,
                "metadata": metadata,
            },
            index=False,
        )
        root_run = {
            "run_id": run_id,
            "lifecycle_id": lifecycle_id,
            "request_id": request_id,
            "checkpoint_thread_id": checkpoint_thread_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "run_depth": 0,
            "created_at": created_at,
        }
        try:
            self._registry.create_lifecycle(
                {
                    "lifecycle_id": lifecycle_id,
                    "request_id": request_id,
                    "root_run_id": run_id,
                    "workflow_id": workflow_id,
                    "workflow_name": workflow_name,
                    "created_at": created_at,
                    "monitoring_capture_enabled": monitoring_capture_enabled,
                    "messages_sha": messages_sha,
                    "message_count": len(messages),
                },
                root_run,
            )
        except BaseException:
            await self.store.adelete(
                lifecycle_input_namespace(lifecycle_id),
                LIFECYCLE_INPUT_KEY,
            )
            raise
        if monitoring_capture_enabled:
            self._initialize_monitoring(record=root_run, document=workflow_document)
        return lifecycle_id

    def register_run(
        self,
        record: dict[str, object],
        *,
        workflow_document: WorkflowGraphDocumentV1,
    ) -> None:
        created_at = str(record.get("created_at") or _now())
        stored = {**record, "created_at": created_at}
        lifecycle = self._registry.get_lifecycle(str(record["lifecycle_id"]))
        if lifecycle is None:
            raise RuntimeError("the Workflow Lifecycle registry record does not exist")
        self._registry.create_run(stored)
        if lifecycle["monitoring_capture_enabled"]:
            self._initialize_monitoring(record=stored, document=workflow_document)

    def start_run(self, run_id: str) -> bool:
        record = self._registry.get_run(run_id)
        if record is None:
            raise RuntimeError("the Workflow Run registry record does not exist")
        return self._registry.start_run(run_id, started_at=_now())

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        error_code: str = "",
        finish_reason: str = "",
        usage: dict[str, int] | None = None,
    ) -> bool:
        record = self._registry.get_run(run_id)
        if record is None:
            raise RuntimeError("the Workflow Run registry record does not exist")
        finished_at = _now()
        effective_usage = usage or {}
        updated = self._registry.finish_run(
            run_id,
            status=status,
            finished_at=finished_at,
            finish_reason=finish_reason,
            error_code=error_code,
            usage=effective_usage,
        )
        if not updated:
            return False
        try:
            if self._monitoring.status(run_id) is not None:
                self._monitoring.finish_run(
                    run_id,
                    interrupted=status == "interrupted",
                )
        except Exception as exc:
            self._observation_error(
                exc,
                code="runtime_monitoring_finalize_failed",
                lifecycle_id=str(record["lifecycle_id"]),
                run_id=run_id,
            )
        return True

    async def lifecycle_changed(self, lifecycle_id: str) -> None:
        if self._cleanup_hook is not None:
            await self._cleanup_hook.lifecycle_changed(lifecycle_id)

    def interrupt_active_runs(self) -> list[dict[str, object]]:
        finished_at = _now()
        interrupted = self._registry.interrupt_active(finished_at=finished_at)
        for record in interrupted:
            run_id = str(record["run_id"])
            try:
                if self._monitoring.status(run_id) is not None:
                    self._monitoring.finish_run(run_id, interrupted=True)
            except Exception as exc:
                self._observation_error(
                    exc,
                    code="runtime_monitoring_recovery_failed",
                    lifecycle_id=str(record["lifecycle_id"]),
                    run_id=run_id,
                )
        return interrupted

    def reconcile_terminal_monitoring(self) -> None:
        """Mark crash-window monitoring writers partial for terminal Runs."""

        try:
            self._monitoring.reconcile_node_attempts(finished_at=_now())
        except Exception as exc:
            self._observation_error(
                exc,
                code="runtime_monitoring_recovery_failed",
                lifecycle_id="",
                run_id="",
            )

        for lifecycle in self._registry.list_all_lifecycles():
            lifecycle_id = str(lifecycle["lifecycle_id"])
            for record in self._registry.list_runs(lifecycle_id):
                if record["status"] in {"pending", "running"}:
                    continue
                run_id = str(record["run_id"])
                try:
                    status = self._monitoring.status(run_id)
                    if status is None or "capturing" not in {
                        status["graph"],
                        status["node"],
                        status["protocol"],
                        status["model"],
                        status["command"],
                    }:
                        continue
                    self._monitoring.finish_run(run_id, interrupted=True)
                except Exception as exc:
                    self._observation_error(
                        exc,
                        code="runtime_monitoring_recovery_failed",
                        lifecycle_id=lifecycle_id,
                        run_id=run_id,
                    )

    def append_protocol_event(
        self,
        lifecycle_id: str,
        run_id: str,
        event: Mapping[str, object],
    ) -> None:
        status = self._monitoring.status(run_id)
        if status is None or status["protocol"] != "capturing":
            return
        self._monitoring.append_protocol_event(
            lifecycle_id=lifecycle_id,
            run_id=run_id,
            event=event,
        )

    def start_node_attempt(self, record: dict[str, object]) -> bool:
        lifecycle_id = str(record["lifecycle_id"])
        run_id = str(record["run_id"])
        try:
            status = self._monitoring.status(run_id)
            if status is None or status["node"] != "capturing":
                return False
            return self._monitoring.start_node_attempt(record)
        except Exception as exc:
            try:
                self._monitoring.mark_partition(run_id, "node", "partial")
            except Exception:
                pass
            self._observation_error(
                exc,
                code="runtime_node_attempt_record_failed",
                lifecycle_id=lifecycle_id,
                run_id=run_id,
            )
            raise

    def finish_node_attempt(
        self,
        run_id: str,
        invocation_id: str,
        attempt: int,
        *,
        status: str,
        error_code: str = "",
    ) -> bool:
        try:
            monitoring = self._monitoring.status(run_id)
            if monitoring is None or monitoring["node"] != "capturing":
                return False
            return self._monitoring.finish_node_attempt(
                run_id,
                invocation_id,
                attempt,
                status=status,
                finished_at=_now(),
                error_code=error_code,
            )
        except Exception as exc:
            record = self._registry.get_run(run_id)
            try:
                self._monitoring.mark_partition(run_id, "node", "partial")
            except Exception:
                pass
            self._observation_error(
                exc,
                code="runtime_node_attempt_record_failed",
                lifecycle_id=str(record["lifecycle_id"]) if record else "",
                run_id=run_id,
            )
            raise

    def start_model_request(self, record: dict[str, object]) -> bool:
        run_id = str(record["run_id"])
        status = self._monitoring.status(run_id)
        if status is None or status["model"] != "capturing":
            return False
        return self._monitoring.start_model_request(record)

    def finish_model_request(
        self,
        model_run_id: str,
        *,
        status: str,
        error_code: str = "",
        usage: Mapping[str, int] | None = None,
    ) -> bool:
        return self._monitoring.finish_model_request(
            model_run_id,
            status=status,
            finished_at=_now(),
            error_code=error_code,
            usage=usage,
        )

    def append_command_observation(self, record: dict[str, object]) -> None:
        lifecycle_id = str(record["lifecycle_id"])
        run_id = str(record["run_id"])
        try:
            status = self._monitoring.status(run_id)
            if status is None or status["command"] != "capturing":
                return
            self._monitoring.append_command_observation(record)
        except Exception as exc:
            try:
                self._monitoring.mark_partition(run_id, "command", "partial")
            except Exception:
                pass
            self._observation_error(
                exc,
                code="runtime_command_observation_record_failed",
                lifecycle_id=lifecycle_id,
                run_id=run_id,
            )
            raise

    def mark_monitoring_partial(self, run_id: str, partition: str) -> None:
        self._monitoring.mark_partition(run_id, partition, "partial")

    def runs(self, lifecycle_id: str) -> list[dict[str, object]]:
        return self._registry.list_runs(lifecycle_id)

    def run(self, run_id: str) -> dict[str, object] | None:
        return self._registry.get_run(run_id)

    def run_summary(self, lifecycle_id: str) -> dict[str, object]:
        summary = self._registry.summary(lifecycle_id)
        lifecycle = self._registry.get_lifecycle(lifecycle_id)
        capture_enabled = bool(
            lifecycle is not None
            and lifecycle["monitoring_capture_enabled"]
        )
        statuses = [
            self._monitoring.status(str(run["run_id"]))
            for run in self._registry.list_runs(lifecycle_id)
        ]
        captured = [status for status in statuses if status is not None]
        has_partial = any(
            "partial" in {
                status["graph"],
                status["node"],
                status["protocol"],
                status["model"],
                status["command"],
            }
            for status in captured
        )
        has_capturing = any(
            "capturing" in {
                status["graph"],
                status["node"],
                status["protocol"],
                status["model"],
                status["command"],
            }
            for status in captured
        )
        if not capture_enabled:
            observation_status = "not_captured"
        elif len(captured) != len(statuses) or has_partial:
            observation_status = "partial"
        elif has_capturing:
            observation_status = "capturing"
        else:
            observation_status = "available"
        summary["observation_status"] = observation_status
        return summary

    @asynccontextmanager
    async def exclusive_mutation(self, lifecycle_id: str) -> AsyncIterator[None]:
        if not lifecycle_id:
            raise ValueError("lifecycle_id must not be empty")
        lock = self._mutation_locks.get(lifecycle_id)
        if lock is None:
            lock = asyncio.Lock()
            self._mutation_locks[lifecycle_id] = lock
        async with lock:
            yield

    async def input_record(self, lifecycle_id: str) -> dict[str, Any] | None:
        item = await self.store.aget(
            lifecycle_input_namespace(lifecycle_id),
            LIFECYCLE_INPUT_KEY,
        )
        return deepcopy(item.value) if item is not None else None

    async def agent_invocation_artifact(
        self,
        lifecycle_id: str,
        run_id: str,
        invocation_id: str,
    ) -> dict[str, Any] | None:
        """Read one exact artifact through the Lifecycle Store owner."""

        item = await self.store.aget(
            lifecycle_invocations_namespace(lifecycle_id, run_id),
            invocation_id,
        )
        return deepcopy(item.value) if item is not None else None

    async def messages(self, lifecycle_id: str) -> list[dict[str, Any]]:
        record = await self.input_record(lifecycle_id)
        messages = record.get("messages") if record is not None else None
        if not isinstance(messages, list):
            raise RuntimeError("the Workflow lifecycle input does not exist")
        return deepcopy(messages)

    async def _search_all(self, namespace: tuple[str, ...]) -> list[Any]:
        items: list[Any] = []
        offset = 0
        while True:
            page = await self.store.asearch(namespace, limit=100, offset=offset)
            items.extend(page)
            if len(page) < 100:
                return items
            offset += len(page)

    async def delete_store_records(self, lifecycle_id: str) -> int:
        items = await self._search_all((LIFECYCLE_NAMESPACE_ROOT, lifecycle_id))
        if items:
            await self.store.abatch(
                [PutOp(tuple(item.namespace), item.key, None) for item in items]
            )
        return len(items)

    async def list_records_page(
        self,
        *,
        limit: int,
        offset: int,
        query: str = "",
    ) -> tuple[list[dict[str, Any]], int]:
        records, total = self._registry.list_lifecycles(
            limit=limit,
            offset=offset,
            query=query,
        )
        return [deepcopy(record) for record in records], total

    async def matching_record_ids(self, *, query: str = "") -> list[str]:
        return self._registry.list_matching_ids(query=query)

    async def record(self, lifecycle_id: str) -> dict[str, Any] | None:
        record = self._registry.get_lifecycle(lifecycle_id)
        return deepcopy(record) if record is not None else None

    async def filesystem_summary(self, lifecycle_id: str) -> dict[str, int]:
        items = await self._search_all(lifecycle_filesystem_namespace(lifecycle_id))
        route_count = 0
        for item in items:
            mappings = item.value.get("mappings")
            if isinstance(mappings, list):
                route_count += len(mappings)
        managed = self._managed_directories.list_for_lifecycle(lifecycle_id)
        return {
            "filesystem_count": len(items),
            "route_count": route_count,
            "dynamic_directory_count": sum(
                1 for item in managed if item["released_at"] is None
            ),
        }

    async def delete_managed_directories(self, lifecycle_id: str) -> int:
        deleted = 0
        for record in self._managed_directories.list_for_lifecycle(lifecycle_id):
            if record["released_at"] is not None:
                continue
            target = Path(str(record["resolved_target"])).resolve()
            root = Path(str(record["configured_root"])).resolve()
            if target.parent != root or target.name != f"lifecycle-{lifecycle_id}":
                raise RuntimeError("the managed dynamic directory target is invalid")
            if target.exists():
                await asyncio.to_thread(shutil.rmtree, target)
                deleted += 1
            self._managed_directories.mark_released(
                lifecycle_id,
                str(record["filesystem_id"]),
                str(record["virtual_path"]),
                released_at=_now(),
            )
        return deleted

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
        if not filesystem_id:
            raise ValueError("filesystem_id must not be empty")
        namespace = lifecycle_filesystem_namespace(lifecycle_id)
        async with self._filesystem_lock:
            stored = await self.store.aget(namespace, filesystem_id)
            if stored is not None:
                mappings = stored.value.get("mappings")
                if not isinstance(mappings, list):
                    raise RuntimeError(
                        "the Workflow lifecycle filesystem record is invalid"
                    )
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
            created_at = _now()
            for virtual_path, local_path, path_origin, lifecycle_mode in configured_mappings:
                root = self._configured_mapping_root(local_path, path_origin)
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
                canonical_target = target.resolve()
                canonical = str(canonical_target).casefold()
                if canonical in resolved_targets:
                    raise ValueError("resolved mapped local directories must be unique")
                resolved_targets.add(canonical)
                resolved[virtual_path] = canonical_target
                records.append(
                    {
                        "virtual_path": virtual_path,
                        "resolved_local_path": str(canonical_target),
                        "configured_root": str(root),
                        "path_origin": path_origin,
                        "lifecycle_mode": lifecycle_mode,
                    }
                )
                if lifecycle_mode == "dynamic":
                    self._managed_directories.register(
                        {
                            "lifecycle_id": lifecycle_id,
                            "filesystem_id": filesystem_id,
                            "virtual_path": virtual_path,
                            "configured_root": str(root),
                            "resolved_target": str(canonical_target),
                            "created_at": created_at,
                        }
                    )
                    canonical_target.mkdir(exist_ok=True)
            await self.store.aput(
                namespace,
                filesystem_id,
                {
                    "version": LIFECYCLE_FILESYSTEM_RECORD_VERSION,
                    "filesystem_id": filesystem_id,
                    "mappings": records,
                    "created_at": created_at,
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
