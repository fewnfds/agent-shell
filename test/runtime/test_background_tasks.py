from __future__ import annotations

import asyncio
from pathlib import Path

from agent_shell.runtime.background_tasks import (
    BackgroundTaskManager,
    BackgroundTaskRecord,
)
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.workflow_lifecycle import (
    WorkflowLifecycleService,
    lifecycle_tasks_namespace,
)
from agent_shell.storage.database import SQLiteDatabase, SQLiteFile
from support import runtime_workflow_document


def _lifecycle_service(root: Path) -> WorkflowLifecycleService:
    return WorkflowLifecycleService(
        SQLiteDatabase(root / "agent-shell.sqlite3"),
        store_database=SQLiteFile(root / "workflow-store.sqlite3"),
    )


class _Execution:
    finish_reason = "stop"

    def __init__(
        self,
        release: asyncio.Event,
        *,
        error: AgentRuntimeError | None = None,
    ) -> None:
        self._release = release
        self._error = error

    @property
    def usage(self) -> dict[str, int]:
        return {"total_tokens": 3}

    async def stream_text(self):
        await self._release.wait()
        if self._error is not None:
            raise self._error
        yield "internal child output"

    async def execute(self) -> None:
        async for _part in self.stream_text():
            pass


def test_background_registration_failure_removes_task_and_never_executes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        lifecycle = _lifecycle_service(tmp_path)
        await lifecycle.start()
        lifecycle_id = await lifecycle.create(
            [{"role": "user", "content": "input"}],
            request_id="request-registration",
            run_id="parent-registration",
            checkpoint_thread_id=None,
            workflow_id="parent-workflow",
            workflow_name="Parent",
            workflow_document=runtime_workflow_document(),
            monitoring_capture_enabled=True,
        )
        manager = BackgroundTaskManager(lifecycle)
        await manager.start()
        executed = False

        async def factory(_identity):
            nonlocal executed
            executed = True
            raise AssertionError("an unregistered Run must not execute")

        def fail_registration(*_args, **_kwargs) -> None:
            raise OSError("registry unavailable")

        monkeypatch.setattr(lifecycle, "register_run", fail_registration)
        try:
            try:
                await manager.start_workflow(
                    lifecycle_id=lifecycle_id,
                    request_id="request-registration",
                    launcher_run_id="parent-registration",
                    launcher_id="launcher",
                    operation_id="registration-failure",
                    caller_run_depth=0,
                    target_id="child",
                    target_name="Child",
                    target_document=runtime_workflow_document(),
                    checkpoint_thread_id=None,
                    cancel_on_upstream_termination=True,
                    execution_factory=factory,
                )
                raise AssertionError("registration failure must cross the boundary")
            except OSError as exc:
                assert str(exc) == "registry unavailable"
            assert executed is False
            assert await manager.list(lifecycle_id) == []
            assert [run["run_id"] for run in lifecycle.runs(lifecycle_id)] == [
                "parent-registration"
            ]
        finally:
            await manager.close()
            await lifecycle.close()

    asyncio.run(scenario())


async def _wait_for_status(
    manager: BackgroundTaskManager,
    lifecycle_id: str,
    task_id: str,
    expected: str,
) -> None:
    for _ in range(100):
        snapshot = (await manager.check(lifecycle_id, [task_id]))[0]
        if snapshot.runtime_status == expected:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"task {task_id} did not reach {expected}")


def test_background_manager_checks_independent_terminal_failure_and_unknown_statuses(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        lifecycle = _lifecycle_service(tmp_path)
        await lifecycle.start()
        lifecycle_id = await lifecycle.create(
            [{"role": "user", "content": "input"}],
            request_id="request-1",
            run_id="parent-run",
            checkpoint_thread_id=None,
            workflow_id="parent-workflow",
            workflow_name="Parent",
            workflow_document=runtime_workflow_document(),
            monitoring_capture_enabled=True,
        )
        manager = BackgroundTaskManager(lifecycle)
        await manager.start()
        first_release = asyncio.Event()
        second_release = asyncio.Event()
        first_factory_calls = 0

        async def first_factory(_identity):
            nonlocal first_factory_calls
            first_factory_calls += 1
            return _Execution(first_release)

        async def second_factory(_identity):
            return _Execution(
                second_release,
                error=AgentRuntimeError(
                    "child_expected_failure",
                    "The child failed.",
                    status_code=422,
                ),
            )

        try:
            first, first_retry = await asyncio.gather(
                *(
                    manager.start_workflow(
                        lifecycle_id=lifecycle_id,
                        request_id="request-1",
                        launcher_run_id="parent-run",
                            launcher_id="launcher",
                        operation_id="first-child",
                        caller_run_depth=0,
                        target_id="child-1",
                        target_name="Child One",
                        target_document=runtime_workflow_document(),
                        checkpoint_thread_id=None,
                        cancel_on_upstream_termination=True,
                        execution_factory=first_factory,
                    )
                    for _ in range(2)
                )
            )
            assert first_retry.task_id == first.task_id
            assert first_retry.child_run_id == first.child_run_id
            second = await manager.start_workflow(
                lifecycle_id=lifecycle_id,
                request_id="request-1",
                launcher_run_id="parent-run",
                launcher_id="launcher",
                operation_id="second-child",
                caller_run_depth=0,
                target_id="child-2",
                target_name="Child Two",
                target_document=runtime_workflow_document(),
                checkpoint_thread_id=None,
                cancel_on_upstream_termination=True,
                execution_factory=second_factory,
            )

            initial = await manager.check(
                lifecycle_id,
                [first.task_id, second.task_id, "missing-task"],
            )
            assert initial[0].runtime_status in {"pending", "running"}
            assert initial[1].runtime_status in {"pending", "running"}
            assert initial[2].runtime_status == "not_found"
            assert initial[0].model_dump(mode="json")["runtime_status"] in {
                "pending",
                "running",
            }
            assert initial[2].model_dump(mode="json")["runtime_status"] == "not_found"

            first_release.set()
            await _wait_for_status(
                manager, lifecycle_id, first.task_id, "succeeded"
            )
            assert first_factory_calls == 1
            still_running = (
                await manager.check(lifecycle_id, [second.task_id])
            )[0]
            assert still_running.runtime_status == "running"

            second_release.set()
            await _wait_for_status(
                manager, lifecycle_id, second.task_id, "failed"
            )
            failed = (await manager.check(lifecycle_id, [second.task_id]))[0]
            assert failed.error_code == "child_expected_failure"
            failed_run = lifecycle.run(second.child_run_id)
            assert failed_run is not None
            assert failed_run["status"] == "failed"
            assert failed_run["error_code"] == "child_expected_failure"

            old = BackgroundTaskRecord(
                task_id="old-task",
                lifecycle_id=lifecycle_id,
                runtime_instance_id="old-runtime",
                launcher_run_id="old-parent",
                launcher_id="launcher",
                operation_id="old-child",
                target_kind="workflow",
                target_id="child-old",
                target_name="Old Child",
                target_graph_sha="graph-sha-old",
                cancel_on_upstream_termination=True,
                child_run_id="old-run",
                checkpoint_thread_id="old-thread",
                run_depth=1,
                status="running",
                created_at="2026-01-01T00:00:00+00:00",
            )
            await lifecycle.store.aput(
                lifecycle_tasks_namespace(lifecycle_id),
                old.task_id,
                old.model_dump(mode="json"),
                index=False,
            )
            interrupted = (
                await manager.check(lifecycle_id, [old.task_id])
            )[0]
            assert interrupted.runtime_status == "interrupted"
            assert interrupted.error_code == "background_runtime_lost"
        finally:
            await manager.close()
            await lifecycle.close()

    asyncio.run(scenario())


def test_background_manager_shutdown_cancels_active_task(tmp_path: Path) -> None:
    async def scenario() -> None:
        lifecycle = _lifecycle_service(tmp_path)
        await lifecycle.start()
        lifecycle_id = await lifecycle.create(
            [{"role": "user", "content": "input"}],
            request_id="request-1",
            run_id="parent-run",
            checkpoint_thread_id=None,
            workflow_id="parent-workflow",
            workflow_name="Parent",
            workflow_document=runtime_workflow_document(),
            monitoring_capture_enabled=True,
        )
        manager = BackgroundTaskManager(lifecycle)
        await manager.start()
        release = asyncio.Event()

        async def factory(_identity):
            return _Execution(release)

        handle = await manager.start_workflow(
            lifecycle_id=lifecycle_id,
            request_id="request-1",
            launcher_run_id="parent-run",
            launcher_id="launcher",
            operation_id="shutdown-child",
            caller_run_depth=0,
            target_id="child",
            target_name="Child",
            target_document=runtime_workflow_document(),
            checkpoint_thread_id=None,
            cancel_on_upstream_termination=True,
            execution_factory=factory,
        )
        await manager.close()
        snapshot = (await manager.check(lifecycle_id, [handle.task_id]))[0]
        assert snapshot.runtime_status == "cancelled"
        assert snapshot.error_code == "background_task_cancelled"
        run = lifecycle.run(handle.child_run_id)
        assert run is not None
        assert run["status"] == "cancelled"
        assert run["error_code"] == "background_task_cancelled"
        await lifecycle.close()

    asyncio.run(scenario())


def test_parent_termination_cancels_only_children_with_propagation_enabled(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        lifecycle = _lifecycle_service(tmp_path)
        await lifecycle.start()
        lifecycle_id = await lifecycle.create(
            [{"role": "user", "content": "input"}],
            request_id="request-1",
            run_id="parent-run",
            checkpoint_thread_id=None,
            workflow_id="parent-workflow",
            workflow_name="Parent",
            workflow_document=runtime_workflow_document(),
            monitoring_capture_enabled=True,
        )
        manager = BackgroundTaskManager(lifecycle)
        await manager.start()
        cascading_release = asyncio.Event()
        independent_release = asyncio.Event()

        async def cascading_factory(_identity):
            return _Execution(cascading_release)

        async def independent_factory(_identity):
            return _Execution(independent_release)

        try:
            cascading = await manager.start_workflow(
                lifecycle_id=lifecycle_id,
                request_id="request-1",
                launcher_run_id="parent-run",
                launcher_id="launcher",
                operation_id="cascading-child",
                caller_run_depth=0,
                target_id="child-cascading",
                target_name="Cascading Child",
                target_document=runtime_workflow_document(),
                checkpoint_thread_id=None,
                cancel_on_upstream_termination=True,
                execution_factory=cascading_factory,
            )
            independent = await manager.start_workflow(
                lifecycle_id=lifecycle_id,
                request_id="request-1",
                launcher_run_id="parent-run",
                launcher_id="launcher",
                operation_id="independent-child",
                caller_run_depth=0,
                target_id="child-independent",
                target_name="Independent Child",
                target_document=runtime_workflow_document(),
                checkpoint_thread_id=None,
                cancel_on_upstream_termination=False,
                execution_factory=independent_factory,
            )
            await _wait_for_status(manager, lifecycle_id, cascading.task_id, "running")
            await _wait_for_status(manager, lifecycle_id, independent.task_id, "running")

            await manager.cancel_children_on_parent_termination(
                lifecycle_id,
                "parent-run",
            )

            await _wait_for_status(manager, lifecycle_id, cascading.task_id, "cancelled")
            still_running = (
                await manager.check(lifecycle_id, [independent.task_id])
            )[0]
            assert still_running.runtime_status == "running"
            assert cascading.cancel_on_upstream_termination is True
            assert independent.cancel_on_upstream_termination is False

            independent_release.set()
            await _wait_for_status(manager, lifecycle_id, independent.task_id, "succeeded")
        finally:
            await manager.close()
            await lifecycle.close()

    asyncio.run(scenario())


def test_background_manager_lists_filters_and_cancels_workflow_task_idempotently(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        lifecycle = _lifecycle_service(tmp_path)
        await lifecycle.start()
        lifecycle_id = await lifecycle.create(
            [{"role": "user", "content": "input"}],
            request_id="request-1",
            run_id="parent-run",
            checkpoint_thread_id=None,
            workflow_id="parent-workflow",
            workflow_name="Parent",
            workflow_document=runtime_workflow_document(),
            monitoring_capture_enabled=True,
        )
        manager = BackgroundTaskManager(lifecycle)
        await manager.start()
        release = asyncio.Event()

        async def factory(_identity):
            return _Execution(release)

        try:
            handle = await manager.start_workflow(
                lifecycle_id=lifecycle_id,
                request_id="request-1",
                launcher_run_id="parent-run",
                launcher_id="agent-launcher",
                operation_id="cancel-workflow",
                caller_run_depth=0,
                target_id="workflow-1",
                target_name="Workflow One",
                target_document=runtime_workflow_document(),
                checkpoint_thread_id=None,
                cancel_on_upstream_termination=True,
                execution_factory=factory,
            )
            assert handle.target_kind == "workflow"
            listed = await manager.list(lifecycle_id)
            assert [item.task_id for item in listed] == [handle.task_id]
            assert listed[0].target_kind == "workflow"
            running = await manager.list(
                lifecycle_id,
                statuses=frozenset({"running"}),
            )
            assert [item.task_id for item in running] == [handle.task_id]
            assert await manager.list(
                lifecycle_id,
                statuses=frozenset({"succeeded"}),
            ) == []

            requested, missing = await manager.cancel(
                lifecycle_id,
                [handle.task_id, "missing-task"],
            )
            assert requested.runtime_status == "cancel_requested"
            assert missing.runtime_status == "not_found"
            await _wait_for_status(manager, lifecycle_id, handle.task_id, "cancelled")
            repeated = (await manager.cancel(lifecycle_id, [handle.task_id]))[0]
            assert repeated.runtime_status == "cancelled"
            cancelled = await manager.list(
                lifecycle_id,
                statuses=frozenset({"cancelled"}),
            )
            assert [item.task_id for item in cancelled] == [handle.task_id]
            run = lifecycle.run(handle.child_run_id)
            assert run is not None
            assert run["status"] == "cancelled"
        finally:
            await manager.close()
            await lifecycle.close()

    asyncio.run(scenario())
