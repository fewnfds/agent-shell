from __future__ import annotations

import asyncio
from pathlib import Path

from agent_shell.contracts import FilesystemBlock
from agent_shell.runtime.background_tasks import BackgroundTaskManager
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.workflow_lifecycle import (
    WorkflowLifecycleService,
    lifecycle_filesystem_namespace,
)
from agent_shell.storage.database import SQLiteDatabase, SQLiteFile


def _lifecycle_service(
    database_path: Path,
    *,
    data_root: Path | None = None,
) -> WorkflowLifecycleService:
    return WorkflowLifecycleService(
        SQLiteDatabase(database_path),
        store_database=SQLiteFile(
            database_path.with_name("workflow-store.sqlite3")
        ),
        data_root=data_root,
    )


async def _create_lifecycle(
    service: WorkflowLifecycleService,
    suffix: str,
) -> str:
    return await service.create(
        [{"role": "user", "content": f"input-{suffix}"}],
        request_id=f"request-{suffix}",
        run_id=f"run-{suffix}",
        checkpoint_thread_id=None,
        workflow_id="workflow",
        workflow_name="Workflow",
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
        service = _lifecycle_service(
            data_root / "state" / "agent-shell.sqlite3",
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
            assert record.value["mappings"][1]["resolved_local_path"] == str(
                first["/dynamic/"]
            )
        finally:
            await service.close()

    asyncio.run(scenario())


def test_lifecycle_relative_mapping_cannot_escape_data_root(tmp_path: Path) -> None:
    async def scenario() -> None:
        data_root = tmp_path / "data"
        (data_root / "state").mkdir(parents=True)
        service = _lifecycle_service(
            data_root / "state" / "agent-shell.sqlite3",
            data_root=data_root,
        )
        await service.start()
        try:
            lifecycle_id = await _create_lifecycle(service, "escape")
            filesystem = FilesystemBlock.model_validate(
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


def test_lifecycle_mutation_locks_are_isolated_by_lifecycle(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _lifecycle_service(tmp_path / "agent-shell.sqlite3")
        await service.start()
        first_id = await _create_lifecycle(service, "first")
        second_id = await _create_lifecycle(service, "second")
        first_entered = asyncio.Event()
        release_first = asyncio.Event()

        async def hold_first() -> None:
            async with service.exclusive_mutation(first_id):
                first_entered.set()
                await release_first.wait()

        holder = asyncio.create_task(hold_first())
        try:
            await first_entered.wait()
            await asyncio.wait_for(
                service.finish_parent(second_id, "completed"),
                timeout=0.5,
            )
            second = await service.record(second_id)
            assert second is not None
            assert second["parent_status"] == "completed"
        finally:
            release_first.set()
            await holder
            await service.close()

    asyncio.run(scenario())


def test_lifecycle_deletion_tombstone_blocks_new_tasks_and_allows_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        data_root = tmp_path / "data"
        dynamic_parent = data_root / "dynamic"
        dynamic_parent.mkdir(parents=True)
        service = _lifecycle_service(
            data_root / "agent-shell.sqlite3",
            data_root=data_root,
        )
        await service.start()
        manager = BackgroundTaskManager(service)
        await manager.start()
        lifecycle_id = await _create_lifecycle(service, "deleting")
        filesystem = FilesystemBlock.model_validate(
            {
                "name": "Deleting workspace",
                "mapped_directories": [
                    {
                        "virtual_path": "/workspace/",
                        "local_path": str(dynamic_parent),
                        "path_origin": "absolute",
                        "lifecycle_mode": "dynamic",
                    }
                ],
            }
        )
        resolved = await service.resolve_mapped_directories(
            lifecycle_id,
            "filesystem",
            filesystem,
        )
        dynamic_directory = resolved["/workspace/"]
        await service.finish_parent(lifecycle_id, "completed")

        async with service.exclusive_mutation(lifecycle_id):
            await service.mark_deleting(lifecycle_id)

        async def execution_factory(_identity):
            raise AssertionError("a deleting Lifecycle must not start work")

        try:
            try:
                await manager.start_workflow(
                    lifecycle_id=lifecycle_id,
                    request_id="request-deleting",
                    launcher_run_id="run-deleting",
                    launcher_id="launcher",
                    operation_id="blocked-start",
                    caller_run_depth=0,
                    target_id="workflow",
                    target_name="Workflow",
                    target_graph_sha="graph-sha",
                    checkpoint_thread_id=None,
                    cancel_on_upstream_termination=True,
                    execution_factory=execution_factory,
                )
                raise AssertionError("background start should be rejected")
            except AgentRuntimeError as exc:
                assert exc.code == "workflow_lifecycle_deleting"

            import agent_shell.runtime.workflow_lifecycle as lifecycle_module

            original_rmtree = lifecycle_module.shutil.rmtree

            def fail_rmtree(_path: Path) -> None:
                raise OSError("expected deletion failure")

            monkeypatch.setattr(lifecycle_module.shutil, "rmtree", fail_rmtree)
            async with service.exclusive_mutation(lifecycle_id):
                try:
                    await service.delete(
                        lifecycle_id,
                        delete_dynamic_directories=True,
                    )
                    raise AssertionError("the first deletion should fail")
                except OSError:
                    pass
            retained = await service.record(lifecycle_id)
            assert retained is not None
            assert retained["lifecycle_status"] == "deleting"
            assert dynamic_directory.is_dir()

            monkeypatch.setattr(
                lifecycle_module.shutil,
                "rmtree",
                original_rmtree,
            )
            async with service.exclusive_mutation(lifecycle_id):
                assert await service.delete(
                    lifecycle_id,
                    delete_dynamic_directories=True,
                )
            assert await service.record(lifecycle_id) is None
            assert not dynamic_directory.exists()
        finally:
            await manager.close()
            await service.close()

    asyncio.run(scenario())
