from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field

from agent_shell.runtime.diagnostics import (
    RuntimeDiagnosticContext,
    RuntimeDiagnostics,
)
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.workflow_lifecycle import (
    WorkflowLifecycleService,
    lifecycle_tasks_namespace,
)
from agent_shell.workflow.contracts import (
    WorkflowGraphDocumentV1,
    workflow_document_sha256,
)


BackgroundTargetKind = Literal["workflow"]
BackgroundTaskStatus = Literal[
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancel_requested",
    "cancelled",
    "interrupted",
]
BackgroundCheckStatus = BackgroundTaskStatus | Literal["not_found"]

ACTIVE_BACKGROUND_STATUSES = frozenset(
    {"pending", "running", "cancel_requested"}
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class BackgroundTaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = 1
    task_id: str
    lifecycle_id: str
    runtime_instance_id: str
    request_id: str = ""
    launcher_run_id: str
    launcher_id: str
    operation_id: str
    target_kind: BackgroundTargetKind
    target_id: str
    target_name: str
    target_graph_sha: str = ""
    cancel_on_upstream_termination: bool
    child_run_id: str
    checkpoint_thread_id: str | None = None
    run_depth: int = Field(ge=0)
    status: BackgroundTaskStatus
    created_at: str
    started_at: str = ""
    finished_at: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str = ""


class BackgroundTaskHandle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = 1
    task_id: str
    lifecycle_id: str
    operation_id: str
    target_kind: BackgroundTargetKind
    target_id: str
    child_run_id: str
    checkpoint_thread_id: str | None = None
    cancel_on_upstream_termination: bool
    run_depth: int
    status: BackgroundTaskStatus


class BackgroundTaskSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = 1
    task_id: str
    lifecycle_id: str
    operation_id: str = ""
    runtime_status: BackgroundCheckStatus
    checked_at: str
    target_kind: BackgroundTargetKind | None = None
    target_id: str = ""
    target_name: str = ""
    child_run_id: str = ""
    checkpoint_thread_id: str | None = None
    cancel_on_upstream_termination: bool | None = None
    run_depth: int | None = None
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str = ""


@dataclass(frozen=True, slots=True)
class BackgroundChildIdentity:
    task_id: str
    child_run_id: str
    checkpoint_thread_id: str | None
    run_depth: int


class BackgroundExecution(Protocol):
    finish_reason: str

    @property
    def usage(self) -> dict[str, int]: ...

    def stream_text(self) -> AsyncIterator[str]: ...


BackgroundExecutionFactory = Callable[
    [BackgroundChildIdentity],
    Awaitable[BackgroundExecution],
]


class BackgroundTaskManager:
    """Run detached in-process work while Store remains the task authority."""

    def __init__(
        self,
        lifecycle: WorkflowLifecycleService,
        *,
        runtime_diagnostics: RuntimeDiagnostics | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._runtime_diagnostics = runtime_diagnostics
        self.runtime_instance_id = str(uuid4())
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._detached_tasks: set[asyncio.Task[None]] = set()
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def close(self) -> None:
        tasks = tuple({*self._tasks.values(), *self._detached_tasks})
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._detached_tasks.clear()
        self._started = False

    def create_detached_task(
        self,
        coroutine: Coroutine[Any, Any, None],
        *,
        name: str,
    ) -> asyncio.Task[None]:
        """Own an in-process continuation that has no background Run record."""

        if not self._started:
            raise RuntimeError("the Background Task Manager is not started")
        task = asyncio.create_task(coroutine, name=name)
        self._detached_tasks.add(task)
        task.add_done_callback(self._detached_tasks.discard)
        return task

    async def start_workflow(
        self,
        *,
        lifecycle_id: str,
        request_id: str,
        launcher_run_id: str,
        launcher_id: str,
        operation_id: str,
        caller_run_depth: int,
        target_id: str,
        target_name: str,
        target_document: WorkflowGraphDocumentV1,
        checkpoint_thread_id: str | None,
        cancel_on_upstream_termination: bool,
        execution_factory: BackgroundExecutionFactory,
    ) -> BackgroundTaskHandle:
        return await self._start(
            lifecycle_id=lifecycle_id,
            request_id=request_id,
            launcher_run_id=launcher_run_id,
            launcher_id=launcher_id,
            operation_id=operation_id,
            caller_run_depth=caller_run_depth,
            target_id=target_id,
            target_name=target_name,
            target_document=target_document,
            checkpoint_thread_id=checkpoint_thread_id,
            cancel_on_upstream_termination=cancel_on_upstream_termination,
            execution_factory=execution_factory,
        )

    async def _start(
        self,
        *,
        lifecycle_id: str,
        request_id: str,
        launcher_run_id: str,
        launcher_id: str,
        operation_id: str,
        caller_run_depth: int,
        target_id: str,
        target_name: str,
        target_document: WorkflowGraphDocumentV1,
        checkpoint_thread_id: str | None,
        cancel_on_upstream_termination: bool,
        execution_factory: BackgroundExecutionFactory,
    ) -> BackgroundTaskHandle:
        if not self._started:
            raise RuntimeError("the Background Task Manager is not started")
        normalized_operation_id = operation_id.strip()
        if not normalized_operation_id or len(normalized_operation_id) > 128:
            raise AgentRuntimeError(
                "background_operation_id_invalid",
                "Background operation_id must contain 1 to 128 characters.",
                status_code=422,
            )
        task_id = str(
            uuid5(
                NAMESPACE_URL,
                f"agent-shell:{lifecycle_id}:{launcher_run_id}:{normalized_operation_id}",
            )
        )
        async with self._lifecycle.exclusive_mutation(lifecycle_id):
            lifecycle = await self._lifecycle.record(lifecycle_id)
            if lifecycle is None:
                raise AgentRuntimeError(
                    "workflow_lifecycle_not_found",
                    "The Workflow lifecycle does not exist.",
                    status_code=409,
                )
            if lifecycle.get("lifecycle_status") != "active":
                raise AgentRuntimeError(
                    "workflow_lifecycle_deleting",
                    "The Workflow lifecycle is being deleted.",
                    status_code=409,
                )
            existing = await self._get(lifecycle_id, task_id)
            if existing is not None:
                if (
                    existing.operation_id != normalized_operation_id
                    or existing.target_id != target_id
                ):
                    raise AgentRuntimeError(
                        "background_operation_conflict",
                        "The background operation_id is already bound to another target.",
                        status_code=409,
                    )
                existing = await self._normalize_active(
                    existing,
                    checked_at=_now(),
                )
                return self._handle(existing)

            identity = BackgroundChildIdentity(
                task_id=task_id,
                child_run_id=str(uuid4()),
                checkpoint_thread_id=checkpoint_thread_id,
                run_depth=caller_run_depth + 1,
            )
            record = BackgroundTaskRecord(
                task_id=task_id,
                lifecycle_id=lifecycle_id,
                runtime_instance_id=self.runtime_instance_id,
                request_id=request_id,
                launcher_run_id=launcher_run_id,
                launcher_id=launcher_id,
                operation_id=normalized_operation_id,
                target_kind="workflow",
                target_id=target_id,
                target_name=target_name,
                target_graph_sha=workflow_document_sha256(target_document),
                cancel_on_upstream_termination=cancel_on_upstream_termination,
                child_run_id=identity.child_run_id,
                checkpoint_thread_id=identity.checkpoint_thread_id,
                run_depth=identity.run_depth,
                status="pending",
                created_at=_now(),
            )
            await self._put(record)
            try:
                self._lifecycle.register_run(
                    {
                        "run_id": record.child_run_id,
                        "lifecycle_id": record.lifecycle_id,
                        "request_id": record.request_id,
                        "checkpoint_thread_id": record.checkpoint_thread_id,
                        "run_kind": record.target_kind,
                        "target_id": record.target_id,
                        "target_name": record.target_name,
                        "parent_run_id": record.launcher_run_id,
                        "launcher_id": record.launcher_id,
                        "background_task_id": record.task_id,
                        "run_depth": record.run_depth,
                        "created_at": record.created_at,
                    },
                    workflow_document=target_document,
                )
            except BaseException:
                await self._delete(record.lifecycle_id, record.task_id)
                raise
            task = asyncio.create_task(
                self._run(record, identity, execution_factory),
                name=f"background-workflow:{task_id}",
            )
            self._tasks[task_id] = task
        await asyncio.sleep(0)
        return self._handle(record)

    async def check(
        self,
        lifecycle_id: str,
        task_ids: Sequence[str],
    ) -> list[BackgroundTaskSnapshot]:
        async with self._lifecycle.exclusive_mutation(lifecycle_id):
            return await self._check_locked(lifecycle_id, task_ids)

    async def _check_locked(
        self,
        lifecycle_id: str,
        task_ids: Sequence[str],
    ) -> list[BackgroundTaskSnapshot]:
        checked_at = _now()
        snapshots: list[BackgroundTaskSnapshot] = []
        for task_id in task_ids:
            record = await self._get(lifecycle_id, task_id)
            if record is None:
                snapshots.append(
                    BackgroundTaskSnapshot(
                        task_id=task_id,
                        lifecycle_id=lifecycle_id,
                        runtime_status="not_found",
                        checked_at=checked_at,
                        error_code="background_task_not_found",
                    )
                )
                continue
            record = await self._normalize_active(record, checked_at=checked_at)
            snapshots.append(self._snapshot(record, checked_at=checked_at))
        return snapshots

    async def list(
        self,
        lifecycle_id: str,
        *,
        statuses: frozenset[BackgroundTaskStatus] | None = None,
    ) -> list[BackgroundTaskSnapshot]:
        async with self._lifecycle.exclusive_mutation(lifecycle_id):
            return await self._list_locked(lifecycle_id, statuses=statuses)

    async def list_for_cleanup(
        self,
        lifecycle_id: str,
    ) -> list[BackgroundTaskSnapshot]:
        """List tasks while the caller holds this Lifecycle's mutation lock."""

        return await self._list_locked(lifecycle_id)

    async def _list_locked(
        self,
        lifecycle_id: str,
        *,
        statuses: frozenset[BackgroundTaskStatus] | None = None,
    ) -> list[BackgroundTaskSnapshot]:
        checked_at = _now()
        records = await self._records_locked(lifecycle_id)
        return await self._snapshots_locked(
            records,
            checked_at=checked_at,
            statuses=statuses,
        )

    async def _snapshots_locked(
        self,
        records: list[BackgroundTaskRecord],
        *,
        checked_at: str,
        statuses: frozenset[BackgroundTaskStatus] | None = None,
    ) -> list[BackgroundTaskSnapshot]:
        snapshots = []
        for record in sorted(records, key=lambda item: (item.created_at, item.task_id)):
            record = await self._normalize_active(record, checked_at=checked_at)
            if statuses is None or record.status in statuses:
                snapshots.append(self._snapshot(record, checked_at=checked_at))
        return snapshots

    async def _records_locked(
        self,
        lifecycle_id: str,
    ) -> list[BackgroundTaskRecord]:
        return [
            BackgroundTaskRecord.model_validate(value)
            for value in await self._record_values_locked(lifecycle_id)
        ]

    async def _record_values_locked(
        self,
        lifecycle_id: str,
    ) -> list[object]:
        values: list[object] = []
        offset = 0
        while True:
            items = await self._lifecycle.store.asearch(
                lifecycle_tasks_namespace(lifecycle_id),
                limit=100,
                offset=offset,
            )
            values.extend(item.value for item in items)
            if len(items) < 100:
                break
            offset += len(items)
        return values

    async def cancel_children_on_parent_termination(
        self,
        lifecycle_id: str,
        parent_run_id: str,
    ) -> None:
        async with self._lifecycle.exclusive_mutation(lifecycle_id):
            checked_at = _now()
            records = await self._records_locked(lifecycle_id)
            for record in records:
                if (
                    record.launcher_run_id != parent_run_id
                    or not record.cancel_on_upstream_termination
                ):
                    continue
                record = await self._normalize_active(record, checked_at=checked_at)
                if record.status not in ACTIVE_BACKGROUND_STATUSES:
                    continue
                live = self._tasks.get(record.task_id)
                if live is None or live.done():
                    continue
                if record.status != "cancel_requested":
                    record = record.model_copy(update={"status": "cancel_requested"})
                    await self._put(record)
                live.cancel()

    async def cancel(
        self,
        lifecycle_id: str,
        task_ids: Sequence[str],
    ) -> list[BackgroundTaskSnapshot]:
        async with self._lifecycle.exclusive_mutation(lifecycle_id):
            return await self._cancel_locked(lifecycle_id, task_ids)

    async def _cancel_locked(
        self,
        lifecycle_id: str,
        task_ids: Sequence[str],
    ) -> list[BackgroundTaskSnapshot]:
        checked_at = _now()
        snapshots: list[BackgroundTaskSnapshot] = []
        for task_id in task_ids:
            record = await self._get(lifecycle_id, task_id)
            if record is None:
                snapshots.append(
                    BackgroundTaskSnapshot(
                        task_id=task_id,
                        lifecycle_id=lifecycle_id,
                        runtime_status="not_found",
                        checked_at=checked_at,
                        error_code="background_task_not_found",
                    )
                )
                continue
            record = await self._normalize_active(record, checked_at=checked_at)
            if record.status in ACTIVE_BACKGROUND_STATUSES:
                live = self._tasks.get(task_id)
                if live is not None and not live.done():
                    if record.status != "cancel_requested":
                        record = record.model_copy(update={"status": "cancel_requested"})
                        await self._put(record)
                    live.cancel()
            snapshots.append(self._snapshot(record, checked_at=checked_at))
        return snapshots

    async def _normalize_active(
        self,
        record: BackgroundTaskRecord,
        *,
        checked_at: str,
    ) -> BackgroundTaskRecord:
        if record.status not in ACTIVE_BACKGROUND_STATUSES:
            return record
        live = self._tasks.get(record.task_id)
        if (
            record.runtime_instance_id == self.runtime_instance_id
            and live is not None
            and not live.done()
        ):
            return record
        record = record.model_copy(
            update={
                "status": "interrupted",
                "finished_at": checked_at,
                "error_code": "background_runtime_lost",
            }
        )
        try:
            await self._put(record)
        except Exception as exc:
            self._report_store_error(exc, record)
        try:
            self._lifecycle.finish_run(
                record.child_run_id,
                status="interrupted",
                error_code="background_runtime_lost",
            )
        except Exception as exc:
            self._report_registry_error(exc, record)
        return record

    async def _run(
        self,
        record: BackgroundTaskRecord,
        identity: BackgroundChildIdentity,
        execution_factory: BackgroundExecutionFactory,
    ) -> None:
        current = record
        try:
            current = current.model_copy(
                update={"status": "running", "started_at": _now()}
            )
            async with self._lifecycle.exclusive_mutation(record.lifecycle_id):
                await self._put(current)
            execution = await execution_factory(identity)
            await execution.execute()
            await self._finish(
                current,
                status="succeeded",
                result={
                    "finish_reason": execution.finish_reason,
                    "usage": execution.usage,
                },
            )
        except asyncio.CancelledError:
            await self._finish(
                current,
                status="cancelled",
                error_code="background_task_cancelled",
            )
            raise
        except AgentRuntimeError as exc:
            await self._finish(current, status="failed", error_code=exc.code)
        except Exception as exc:
            self._report_runtime_error(exc, current)
            await self._finish(
                current,
                status="failed",
                error_code="background_task_failed",
            )
        finally:
            self._tasks.pop(record.task_id, None)

    async def _finish(
        self,
        record: BackgroundTaskRecord,
        *,
        status: Literal["succeeded", "failed", "cancelled"],
        result: dict[str, Any] | None = None,
        error_code: str = "",
    ) -> None:
        terminal = record.model_copy(
            update={
                "status": status,
                "finished_at": _now(),
                "result": result or {},
                "error_code": error_code,
            }
        )
        try:
            async with self._lifecycle.exclusive_mutation(record.lifecycle_id):
                await self._put(terminal)
        except Exception as exc:
            self._report_store_error(exc, record)
        run_status = "completed" if status == "succeeded" else status
        usage = (result or {}).get("usage", {})
        try:
            self._lifecycle.finish_run(
                record.child_run_id,
                status=run_status,
                error_code=error_code,
                finish_reason=str((result or {}).get("finish_reason", "")),
                usage=usage if isinstance(usage, dict) else {},
            )
        except Exception as exc:
            self._report_registry_error(exc, record)
        await self._lifecycle.lifecycle_changed(record.lifecycle_id)

    async def _put(self, record: BackgroundTaskRecord) -> None:
        await self._lifecycle.store.aput(
            lifecycle_tasks_namespace(record.lifecycle_id),
            record.task_id,
            record.model_dump(mode="json"),
            index=False,
        )

    async def _delete(self, lifecycle_id: str, task_id: str) -> None:
        await self._lifecycle.store.adelete(
            lifecycle_tasks_namespace(lifecycle_id),
            task_id,
        )

    async def _get(
        self,
        lifecycle_id: str,
        task_id: str,
    ) -> BackgroundTaskRecord | None:
        item = await self._lifecycle.store.aget(
            lifecycle_tasks_namespace(lifecycle_id),
            task_id,
        )
        return (
            BackgroundTaskRecord.model_validate(item.value)
            if item is not None
            else None
        )

    @staticmethod
    def _handle(record: BackgroundTaskRecord) -> BackgroundTaskHandle:
        return BackgroundTaskHandle(
            task_id=record.task_id,
            lifecycle_id=record.lifecycle_id,
            operation_id=record.operation_id,
            target_kind=record.target_kind,
            target_id=record.target_id,
            child_run_id=record.child_run_id,
            checkpoint_thread_id=record.checkpoint_thread_id,
            cancel_on_upstream_termination=record.cancel_on_upstream_termination,
            run_depth=record.run_depth,
            status=record.status,
        )

    @staticmethod
    def _snapshot(
        record: BackgroundTaskRecord,
        *,
        checked_at: str,
    ) -> BackgroundTaskSnapshot:
        return BackgroundTaskSnapshot(
            task_id=record.task_id,
            lifecycle_id=record.lifecycle_id,
            operation_id=record.operation_id,
            runtime_status=record.status,
            checked_at=checked_at,
            target_kind=record.target_kind,
            target_id=record.target_id,
            target_name=record.target_name,
            child_run_id=record.child_run_id,
            checkpoint_thread_id=record.checkpoint_thread_id,
            cancel_on_upstream_termination=record.cancel_on_upstream_termination,
            run_depth=record.run_depth,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            result=record.result,
            error_code=record.error_code,
        )

    def _report_runtime_error(
        self,
        exc: BaseException,
        record: BackgroundTaskRecord,
    ) -> None:
        if self._runtime_diagnostics is not None:
            self._runtime_diagnostics.runtime_error(
                exc,
                code="background_task_failed",
                component="background_runtime",
                context=self._diagnostic_context(record),
            )

    def _report_store_error(
        self,
        exc: BaseException,
        record: BackgroundTaskRecord,
    ) -> None:
        if self._runtime_diagnostics is not None:
            self._runtime_diagnostics.observation_error(
                exc,
                code="background_task_record_failed",
                component="persistence",
                context=self._diagnostic_context(record),
            )

    def _report_registry_error(
        self,
        exc: BaseException,
        record: BackgroundTaskRecord,
    ) -> None:
        if self._runtime_diagnostics is not None:
            self._runtime_diagnostics.observation_error(
                exc,
                code="runtime_run_registry_failed",
                component="persistence",
                context=self._diagnostic_context(record),
            )

    @staticmethod
    def _diagnostic_context(record: BackgroundTaskRecord) -> RuntimeDiagnosticContext:
        return RuntimeDiagnosticContext(
            request_id=record.request_id,
            lifecycle_id=record.lifecycle_id,
            workflow_run_id=record.child_run_id,
            checkpoint_thread_id=record.checkpoint_thread_id,
            subject_kind=record.target_kind,
            subject_id=record.target_id,
            subject_name=record.target_name,
            node_invocation_id=record.task_id,
        )


__all__ = [
    "ACTIVE_BACKGROUND_STATUSES",
    "BackgroundChildIdentity",
    "BackgroundTaskHandle",
    "BackgroundTaskManager",
    "BackgroundTaskRecord",
    "BackgroundTaskSnapshot",
    "BackgroundTaskStatus",
]
