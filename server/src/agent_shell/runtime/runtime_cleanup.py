from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from agent_shell.runtime.background_tasks import (
    ACTIVE_BACKGROUND_STATUSES,
    BackgroundTaskManager,
)
from agent_shell.runtime.diagnostics import RuntimeDiagnosticContext, RuntimeDiagnostics
from agent_shell.runtime.workflow_checkpoints import WorkflowCheckpointService
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService
from agent_shell.storage.runtime_policy import RuntimePolicyStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class RuntimeLifecycleActiveError(RuntimeError):
    """The requested cleanup targets a Lifecycle with active work."""


class RuntimeCleanupCoordinator:
    """Converge terminal Lifecycles and orchestrate cross-owner cleanup."""

    def __init__(
        self,
        lifecycle: WorkflowLifecycleService,
        background_tasks: BackgroundTaskManager,
        checkpoints: WorkflowCheckpointService,
        policy: RuntimePolicyStore,
        diagnostics: RuntimeDiagnostics | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._background_tasks = background_tasks
        self._checkpoints = checkpoints
        self._policy = policy
        self._diagnostics = diagnostics
        self._lock = asyncio.Lock()
        lifecycle.set_cleanup_hook(self)

    async def startup_recover(self) -> None:
        """Normalize process-owned active facts before enforcing retention."""

        self._lifecycle.interrupt_active_runs()
        self._lifecycle.reconcile_terminal_monitoring()
        for record in self._lifecycle.registry.list_all_lifecycles():
            lifecycle_id = str(record["lifecycle_id"])
            async with self._lifecycle.exclusive_mutation(lifecycle_id):
                await self._background_tasks.list_for_cleanup(lifecycle_id)
        await self.enforce_retention()

    async def lifecycle_changed(self, lifecycle_id: str) -> None:
        async with self._lock:
            await self._mark_terminal_if_complete(lifecycle_id)
            await self._enforce_retention_locked()

    async def enforce_retention(self) -> None:
        async with self._lock:
            for record in self._lifecycle.registry.list_all_lifecycles():
                await self._mark_terminal_if_complete(str(record["lifecycle_id"]))
            await self._enforce_retention_locked()

    async def _mark_terminal_if_complete(self, lifecycle_id: str) -> None:
        async with self._lifecycle.exclusive_mutation(lifecycle_id):
            record = await self._lifecycle.record(lifecycle_id)
            if record is None:
                return
            self._lifecycle.reconcile_terminal_monitoring(lifecycle_id)
            if record.get("fully_terminal_at") is not None:
                return
            if record.get("lifecycle_status") in {"deleting", "purge_pending"}:
                return
            root = self._lifecycle.run(str(record["root_run_id"]))
            if root is None or root["status"] in {"pending", "running"}:
                return
            if self._lifecycle.registry.has_active_runs(lifecycle_id):
                return
            tasks = await self._background_tasks.list_for_cleanup(lifecycle_id)
            if any(
                task.runtime_status in ACTIVE_BACKGROUND_STATUSES for task in tasks
            ):
                return
            self._lifecycle.registry.mark_fully_terminal(
                lifecycle_id,
                terminal_at=_now(),
            )

    async def _enforce_retention_locked(self) -> None:
        limit = self._policy.snapshot().runtime_monitoring_retention_lifecycles
        captured = self._lifecycle.registry.terminal_capture_enabled()
        purge_ids = {
            str(record["lifecycle_id"])
            for record in captured[limit:]
        }
        for record in self._lifecycle.registry.list_all_lifecycles():
            if record.get("fully_terminal_at") is None:
                continue
            if not record["monitoring_capture_enabled"]:
                purge_ids.add(str(record["lifecycle_id"]))
            elif limit == 0:
                purge_ids.add(str(record["lifecycle_id"]))
            elif record.get("lifecycle_status") == "purge_pending":
                purge_ids.add(str(record["lifecycle_id"]))
        for lifecycle_id in sorted(purge_ids):
            await self._purge(lifecycle_id, automatic=True)

    async def delete(
        self,
        lifecycle_id: str,
    ) -> dict[str, int]:
        async with self._lock:
            result = await self._purge(
                lifecycle_id,
                automatic=False,
            )
        if result is None:
            return {"checkpoint_thread_count": 0}
        return result

    async def _purge(
        self,
        lifecycle_id: str,
        *,
        automatic: bool,
    ) -> dict[str, int] | None:
        async with self._lifecycle.exclusive_mutation(lifecycle_id):
            record = await self._lifecycle.record(lifecycle_id)
            if record is None:
                return None
            tasks = await self._background_tasks.list_for_cleanup(lifecycle_id)
            if self._lifecycle.registry.has_active_runs(lifecycle_id) or any(
                task.runtime_status in ACTIVE_BACKGROUND_STATUSES for task in tasks
            ):
                if automatic:
                    return None
                raise RuntimeLifecycleActiveError(
                    "a Workflow lifecycle with an active run cannot be deleted"
                )
            if automatic:
                self._lifecycle.registry.mark_purge_pending(
                    lifecycle_id,
                    started_at=_now(),
                )
            else:
                self._lifecycle.registry.mark_deleting(
                    lifecycle_id,
                    started_at=_now(),
                )
            checkpoint_ids = self._lifecycle.registry.checkpoint_thread_ids(
                lifecycle_id
            )
            try:
                for thread_id in checkpoint_ids:
                    await self._checkpoints.purge_thread(thread_id)
                await self._lifecycle.delete_store_records(lifecycle_id)
                self._lifecycle.monitoring.purge_lifecycle(lifecycle_id)
                self._lifecycle.registry.delete_lifecycle(lifecycle_id)
            except Exception as exc:
                self._report_failure(exc, lifecycle_id)
                if automatic:
                    return None
                raise
            return {
                "checkpoint_thread_count": len(checkpoint_ids),
            }

    def _report_failure(self, exc: BaseException, lifecycle_id: str) -> None:
        if self._diagnostics is None:
            return
        self._diagnostics.observation_error(
            exc,
            code="runtime_lifecycle_cleanup_failed",
            component="persistence",
            context=RuntimeDiagnosticContext(
                lifecycle_id=lifecycle_id,
                subject_kind="persistence",
                subject_name="Runtime Lifecycle cleanup",
            ),
        )


__all__ = ["RuntimeCleanupCoordinator", "RuntimeLifecycleActiveError"]
