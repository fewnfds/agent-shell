from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from agent_shell.contracts import FilesystemBlock
from agent_shell.runtime.background_tasks import BackgroundTaskManager
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.runtime_cleanup import RuntimeCleanupCoordinator
from agent_shell.runtime.workflow_checkpoints import WorkflowCheckpointService
from agent_shell.runtime.workflow_lifecycle import (
    WorkflowLifecycleService,
    lifecycle_filesystem_namespace,
)
from agent_shell.storage.database import SQLiteDatabase, SQLiteFile
from agent_shell.storage.runtime_monitoring_queries import (
    RuntimeMonitoringQueryStore,
)
from support import runtime_workflow_document


class _Policy:
    def __init__(self, limit: int) -> None:
        self.limit = limit

    def snapshot(self):
        return SimpleNamespace(
            runtime_monitoring_retention_lifecycles=self.limit,
        )


def _runtime(
    database_path: Path,
    *,
    data_root: Path | None = None,
    retention: int = 20,
):
    lifecycle = WorkflowLifecycleService(
        SQLiteDatabase(database_path),
        store_database=SQLiteFile(
            database_path.with_name("workflow-store.sqlite3")
        ),
        data_root=data_root,
    )
    tasks = BackgroundTaskManager(lifecycle)
    checkpoints = WorkflowCheckpointService(
        SQLiteFile(
            database_path.with_name("workflow-checkpoints.sqlite3"),
            create=False,
        )
    )
    policy = _Policy(retention)
    cleanup = RuntimeCleanupCoordinator(
        lifecycle,
        tasks,
        checkpoints,
        policy,  # type: ignore[arg-type]
    )
    return lifecycle, tasks, checkpoints, policy, cleanup


async def _create_lifecycle(
    service: WorkflowLifecycleService,
    suffix: str,
    *,
    capture: bool = True,
) -> str:
    return await service.create(
        [{"role": "user", "content": f"input-{suffix}"}],
        request_id=f"request-{suffix}",
        run_id=f"run-{suffix}",
        checkpoint_thread_id=None,
        workflow_id="workflow",
        workflow_name="Workflow",
        workflow_document=runtime_workflow_document(),
        monitoring_capture_enabled=capture,
    )


def test_lifecycle_resolves_fixed_and_dynamic_mappings_once(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        data_root = tmp_path / "data"
        dynamic_parent = data_root / "files" / "dynamic"
        fixed = tmp_path / "fixed"
        dynamic_parent.mkdir(parents=True)
        (data_root / "state").mkdir()
        fixed.mkdir()
        service = WorkflowLifecycleService(
            SQLiteDatabase(data_root / "state" / "agent-shell.sqlite3"),
            store_database=SQLiteFile(
                data_root / "state" / "workflow-store.sqlite3"
            ),
            data_root=data_root,
        )
        await service.start()
        filesystem = FilesystemBlock.model_validate(
            {
                "name": "Lifecycle workspace",
                "mapped_directories": [
                    {
                        "virtual_path": "/fixed/",
                        "local_path": str(fixed),
                        "path_origin": "absolute",
                        "lifecycle_mode": "fixed",
                    },
                    {
                        "virtual_path": "/dynamic/",
                        "local_path": "files/dynamic",
                        "path_origin": "data-root-relative",
                        "lifecycle_mode": "dynamic",
                    },
                ],
            }
        )
        try:
            first_id = await _create_lifecycle(service, "first")
            second_id = await _create_lifecycle(service, "second")
            first = await service.resolve_mapped_directories(
                first_id,
                "filesystem-1",
                filesystem,
            )
            repeated = await service.resolve_mapped_directories(
                first_id,
                "filesystem-1",
                filesystem,
            )
            second = await service.resolve_mapped_directories(
                second_id,
                "filesystem-1",
                filesystem,
            )

            assert first["/fixed/"] == fixed.resolve()
            assert repeated == first
            assert first["/dynamic/"].is_dir()
            assert first["/dynamic/"].parent == dynamic_parent.resolve()
            assert first["/dynamic/"] != second["/dynamic/"]
            record = await service.store.aget(
                lifecycle_filesystem_namespace(first_id),
                "filesystem-1",
            )
            assert record is not None
            assert record.value["mappings"][1]["lifecycle_mode"] == "dynamic"
        finally:
            await service.close()

    asyncio.run(scenario())


def test_lifecycle_relative_mapping_cannot_escape_data_root(tmp_path: Path) -> None:
    async def scenario() -> None:
        data_root = tmp_path / "data"
        (data_root / "state").mkdir(parents=True)
        service = WorkflowLifecycleService(
            SQLiteDatabase(data_root / "state" / "agent-shell.sqlite3"),
            store_database=SQLiteFile(
                data_root / "state" / "workflow-store.sqlite3"
            ),
            data_root=data_root,
        )
        await service.start()
        try:
            await _create_lifecycle(service, "escape")
            FilesystemBlock.model_validate(
                {
                    "name": "Invalid workspace",
                    "mapped_directories": [
                        {
                            "virtual_path": "/workspace/",
                            "local_path": "../outside",
                            "path_origin": "data-root-relative",
                        }
                    ],
                }
            )
            raise AssertionError(
                "the Filesystem contract should reject a relative escape",
            )
        except ValueError:
            pass
        finally:
            await service.close()

    asyncio.run(scenario())


def test_full_terminal_waits_for_child_run_then_retention_converges(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        lifecycle, tasks, _checkpoints, policy, cleanup = _runtime(
            tmp_path / "agent-shell.sqlite3",
            retention=1,
        )
        await lifecycle.start()
        await tasks.start()
        try:
            lifecycle_id = await _create_lifecycle(lifecycle, "parent")
            lifecycle.register_run(
                {
                    "run_id": "run-child",
                    "lifecycle_id": lifecycle_id,
                    "request_id": "request-parent",
                    "workflow_id": "child-workflow",
                    "workflow_name": "Child Workflow",
                    "parent_run_id": "run-parent",
                    "background_task_id": "child-task",
                    "run_depth": 1,
                },
                workflow_document=runtime_workflow_document(),
            )
            assert lifecycle.finish_run("run-parent", status="completed")
            await cleanup.enforce_retention()
            parent_terminal = await lifecycle.record(lifecycle_id)
            assert parent_terminal is not None
            assert "fully_terminal_at" not in parent_terminal

            assert lifecycle.finish_run("run-child", status="completed")
            await cleanup.enforce_retention()
            complete = await lifecycle.record(lifecycle_id)
            assert complete is not None
            assert complete["fully_terminal_at"]

            policy.limit = 0
            await cleanup.enforce_retention()
            assert await lifecycle.record(lifecycle_id) is None
        finally:
            await tasks.close()
            await lifecycle.close()

    asyncio.run(scenario())


def test_retention_uses_full_terminal_order_and_excludes_active_lifecycles(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        lifecycle, tasks, _checkpoints, policy, cleanup = _runtime(
            tmp_path / "agent-shell.sqlite3",
            retention=2,
        )
        await lifecycle.start()
        await tasks.start()
        try:
            old_id = await _create_lifecycle(lifecycle, "old")
            assert lifecycle.finish_run("run-old", status="completed")
            lifecycle.registry.mark_fully_terminal(
                old_id,
                terminal_at="2026-01-01T00:00:01.000+00:00",
            )

            long_running_id = await _create_lifecycle(lifecycle, "long")

            middle_id = await _create_lifecycle(lifecycle, "middle")
            assert lifecycle.finish_run("run-middle", status="completed")
            lifecycle.registry.mark_fully_terminal(
                middle_id,
                terminal_at="2026-01-01T00:00:03.000+00:00",
            )

            newest_id = await _create_lifecycle(lifecycle, "newest")
            assert lifecycle.finish_run("run-newest", status="completed")
            lifecycle.registry.mark_fully_terminal(
                newest_id,
                terminal_at="2026-01-01T00:00:04.000+00:00",
            )

            await cleanup.enforce_retention()
            assert await lifecycle.record(old_id) is None
            assert await lifecycle.record(middle_id) is not None
            assert await lifecycle.record(newest_id) is not None
            assert await lifecycle.record(long_running_id) is not None

            policy.limit = 1
            await cleanup.enforce_retention()
            assert await lifecycle.record(middle_id) is None
            assert await lifecycle.record(newest_id) is not None
            assert await lifecycle.record(long_running_id) is not None

            assert lifecycle.finish_run("run-long", status="completed")
            lifecycle.registry.mark_fully_terminal(
                long_running_id,
                terminal_at="2026-01-01T00:00:05.000+00:00",
            )
            await cleanup.enforce_retention()
            assert await lifecycle.record(newest_id) is None
            assert await lifecycle.record(long_running_id) is not None

            policy.limit = 0
            await cleanup.enforce_retention()
            assert await lifecycle.record(long_running_id) is None

            disabled_id = await _create_lifecycle(
                lifecycle,
                "disabled",
                capture=False,
            )
            assert lifecycle.finish_run("run-disabled", status="completed")
            lifecycle.registry.mark_fully_terminal(
                disabled_id,
                terminal_at="2026-01-01T00:00:06.000+00:00",
            )
            await cleanup.enforce_retention()
            assert await lifecycle.record(disabled_id) is None

            policy.limit = 3
            await cleanup.enforce_retention()
            assert await lifecycle.record(old_id) is None
        finally:
            await tasks.close()
            await lifecycle.close()

    asyncio.run(scenario())


def test_startup_recovery_interrupts_active_run_before_retention(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database_path = tmp_path / "agent-shell.sqlite3"
        first_lifecycle, first_tasks, _checkpoints, _policy, _cleanup = _runtime(
            database_path,
            retention=1,
        )
        await first_lifecycle.start()
        await first_tasks.start()
        lifecycle_id = await _create_lifecycle(first_lifecycle, "restart")
        assert first_lifecycle.start_run("run-restart")
        await first_tasks.close()
        await first_lifecycle.close()

        lifecycle, tasks, checkpoints, policy, cleanup = _runtime(
            database_path,
            retention=1,
        )
        await lifecycle.start()
        await tasks.start()
        try:
            await cleanup.startup_recover()
            run = lifecycle.run("run-restart")
            assert run is not None
            assert run["status"] == "interrupted"
            record = await lifecycle.record(lifecycle_id)
            assert record is not None
            assert record["fully_terminal_at"]
            monitoring = lifecycle.monitoring.status("run-restart")
            assert monitoring is not None
            assert monitoring["graph"] == "available"
            assert monitoring["protocol"] == "partial"
            assert monitoring["model"] == "not_applicable"
            assert monitoring["command"] == "not_applicable"
            assert checkpoints.started is False

            policy.limit = 0
            await cleanup.enforce_retention()
            assert await lifecycle.record(lifecycle_id) is None
        finally:
            await tasks.close()
            await lifecycle.close()

    asyncio.run(scenario())


def test_retention_and_explicit_delete_preserve_user_files(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        data_root = tmp_path / "data"
        state_root = data_root / "state"
        dynamic_root = data_root / "dynamic"
        fixed_root = data_root / "fixed"
        ordinary_file = data_root / "files" / "ordinary.txt"
        state_root.mkdir(parents=True)
        dynamic_root.mkdir()
        fixed_root.mkdir()
        ordinary_file.parent.mkdir()
        ordinary_file.write_text("keep", encoding="utf-8")
        filesystem = FilesystemBlock.model_validate(
            {
                "name": "Retention workspace",
                "mapped_directories": [
                    {
                        "virtual_path": "/fixed/",
                        "local_path": str(fixed_root),
                        "path_origin": "absolute",
                        "lifecycle_mode": "fixed",
                    },
                    {
                        "virtual_path": "/dynamic/",
                        "local_path": str(dynamic_root),
                        "path_origin": "absolute",
                        "lifecycle_mode": "dynamic",
                    },
                ],
            }
        )
        lifecycle, tasks, checkpoints, policy, cleanup = _runtime(
            state_root / "agent-shell.sqlite3",
            data_root=data_root,
            retention=1,
        )
        await lifecycle.start()
        await tasks.start()
        try:
            automatic_id = await _create_lifecycle(lifecycle, "automatic")
            automatic_routes = await lifecycle.resolve_mapped_directories(
                automatic_id,
                "filesystem",
                filesystem,
            )
            automatic_dynamic = automatic_routes["/dynamic/"]
            (automatic_dynamic / "result.txt").write_text(
                "preserve",
                encoding="utf-8",
            )
            assert lifecycle.finish_run("run-automatic", status="completed")
            policy.limit = 0
            await cleanup.enforce_retention()

            assert await lifecycle.record(automatic_id) is None
            assert automatic_dynamic.is_dir()
            assert (automatic_dynamic / "result.txt").read_text(
                encoding="utf-8"
            ) == "preserve"
            assert fixed_root.is_dir()
            assert ordinary_file.read_text(encoding="utf-8") == "keep"
            assert checkpoints.started is False

            policy.limit = 1
            explicit_id = await _create_lifecycle(lifecycle, "explicit")
            explicit_routes = await lifecycle.resolve_mapped_directories(
                explicit_id,
                "filesystem",
                filesystem,
            )
            explicit_dynamic = explicit_routes["/dynamic/"]
            (explicit_dynamic / "result.txt").write_text(
                "also-preserve",
                encoding="utf-8",
            )
            assert lifecycle.finish_run("run-explicit", status="completed")
            result = await cleanup.delete(explicit_id)
            assert result == {"checkpoint_thread_count": 0}
            assert explicit_dynamic.is_dir()
            assert (explicit_dynamic / "result.txt").read_text(
                encoding="utf-8"
            ) == "also-preserve"
            assert automatic_dynamic.is_dir()
        finally:
            await tasks.close()
            await lifecycle.close()

    asyncio.run(scenario())


def test_restart_marks_terminal_run_crash_window_monitoring_partial(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database_path = tmp_path / "agent-shell.sqlite3"
        (
            first_lifecycle,
            first_tasks,
            _checkpoints,
            _policy,
            first_cleanup,
        ) = _runtime(database_path, retention=1)
        await first_lifecycle.start()
        await first_tasks.start()
        lifecycle_id = await _create_lifecycle(first_lifecycle, "terminal-window")
        assert first_lifecycle.start_run("run-terminal-window")
        assert first_lifecycle.registry.finish_run(
            "run-terminal-window",
            status="completed",
            finished_at="2026-01-01T00:00:00.000+00:00",
            finish_reason="stop",
            error_code="",
            usage={},
        )
        before = first_lifecycle.monitoring.status("run-terminal-window")
        assert before is not None
        assert before["protocol"] == "capturing"
        projected = RuntimeMonitoringQueryStore(
            SQLiteDatabase(database_path)
        ).run(lifecycle_id, "run-terminal-window")
        assert projected is not None
        assert projected["monitoring"]["protocol"] == "partial"
        await first_cleanup.enforce_retention()
        converged = first_lifecycle.monitoring.status("run-terminal-window")
        assert converged is not None
        assert converged["protocol"] == "partial"
        await first_tasks.close()
        await first_lifecycle.close()

        lifecycle, tasks, _checkpoints, _policy, cleanup = _runtime(
            database_path,
            retention=1,
        )
        await lifecycle.start()
        await tasks.start()
        try:
            await cleanup.startup_recover()
            record = await lifecycle.record(lifecycle_id)
            assert record is not None
            assert record["fully_terminal_at"]
            monitoring = lifecycle.monitoring.status("run-terminal-window")
            assert monitoring is not None
            assert monitoring["graph"] == "available"
            assert monitoring["protocol"] == "partial"
            assert monitoring["model"] == "not_applicable"
            assert monitoring["command"] == "not_applicable"
        finally:
            await tasks.close()
            await lifecycle.close()

    asyncio.run(scenario())


def test_purge_pending_lifecycle_does_not_consume_retention_quota(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        lifecycle, tasks, _checkpoints, _policy, cleanup = _runtime(
            tmp_path / "agent-shell.sqlite3",
            retention=1,
        )
        await lifecycle.start()
        await tasks.start()
        try:
            retained_id = await _create_lifecycle(lifecycle, "retained")
            assert lifecycle.finish_run("run-retained", status="completed")
            await cleanup.enforce_retention()

            pending_id = await _create_lifecycle(lifecycle, "pending-newer")
            assert lifecycle.finish_run("run-pending-newer", status="completed")
            lifecycle.registry.mark_fully_terminal(
                pending_id,
                terminal_at="9999-01-01T00:00:00.000+00:00",
            )
            lifecycle.registry.mark_purge_pending(
                pending_id,
                started_at="9999-01-01T00:00:00.000+00:00",
            )
            original_delete = lifecycle.delete_store_records

            async def fail_pending(lifecycle_id: str) -> int:
                if lifecycle_id == pending_id:
                    raise OSError("pending cleanup remains unavailable")
                return await original_delete(lifecycle_id)

            monkeypatch.setattr(lifecycle, "delete_store_records", fail_pending)
            await cleanup.enforce_retention()

            assert await lifecycle.record(retained_id) is not None
            pending = await lifecycle.record(pending_id)
            assert pending is not None
            assert pending["lifecycle_status"] == "purge_pending"
        finally:
            await tasks.close()
            await lifecycle.close()

    asyncio.run(scenario())


def test_purge_pending_lifecycle_rejects_new_background_run(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        lifecycle, tasks, _checkpoints, _policy, _cleanup = _runtime(
            tmp_path / "agent-shell.sqlite3"
        )
        await lifecycle.start()
        await tasks.start()
        lifecycle_id = await _create_lifecycle(lifecycle, "pending")
        lifecycle.registry.mark_purge_pending(
            lifecycle_id,
            started_at="2026-01-01T00:00:00.000+00:00",
        )
        invoked = False

        async def factory(_identity):
            nonlocal invoked
            invoked = True
            raise AssertionError("purge-pending work must not execute")

        try:
            try:
                await tasks.start_workflow(
                    lifecycle_id=lifecycle_id,
                    request_id="request-pending",
                    launcher_run_id="run-pending",
                    operation_id="blocked",
                    caller_run_depth=0,
                    target_id="workflow",
                    target_name="Workflow",
                    target_document=runtime_workflow_document(),
                    checkpoint_thread_id=None,
                    cancel_on_upstream_termination=True,
                    execution_factory=factory,
                )
                raise AssertionError("background start should be rejected")
            except AgentRuntimeError as exc:
                assert exc.code == "workflow_lifecycle_deleting"
            assert invoked is False
        finally:
            await tasks.close()
            await lifecycle.close()

    asyncio.run(scenario())
