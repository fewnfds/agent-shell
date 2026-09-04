from __future__ import annotations

import asyncio
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

import agent_shell.runtime.monitoring_archive as monitoring_archive_module
from agent_shell.runtime.monitoring_archive import (
    ARCHIVE_SCHEMA,
    RuntimeMonitoringArchiveService,
)
from agent_shell.runtime.monitoring_read_service import MonitoringReadService
from agent_shell.runtime.workflow_checkpoints import WorkflowCheckpointService
from agent_shell.runtime.workflow_lifecycle import (
    WorkflowLifecycleService,
    lifecycle_invocations_namespace,
)
from agent_shell.storage.database import SQLiteDatabase, SQLiteFile
from agent_shell.storage.runtime_monitoring_queries import (
    RuntimeMonitoringQueryStore,
)
from agent_shell.workflow import admit_workflow_document
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1
from support import runtime_workflow_document


AGENT_ID = "11111111-1111-4111-8111-111111111111"
COMMAND_ID = "22222222-2222-4222-8222-222222222222"


def _monitoring_document() -> WorkflowGraphDocumentV1:
    admission, document = admit_workflow_document(
        {
            "definition": {
                "schema_version": 1,
                "state_contract": "agent-shell.workflow.agent-invocations.v1",
                "nodes": [
                    {
                        "id": "start",
                        "type": "start",
                        "type_version": 1,
                        "config": {},
                    },
                    {
                        "id": "command",
                        "type": "command",
                        "type_version": 1,
                        "config": {"command_id": COMMAND_ID},
                    },
                    {
                        "id": "agent",
                        "type": "agent",
                        "type_version": 1,
                        "config": {"main_agent_id": AGENT_ID},
                    },
                    {
                        "id": "end",
                        "type": "end",
                        "type_version": 1,
                        "config": {},
                    },
                ],
                "edges": [
                    {
                        "id": "start-command",
                        "source": "start",
                        "source_handle": "next",
                        "target": "command",
                        "target_handle": "in",
                    },
                    {
                        "id": "command-agent",
                        "source": "command",
                        "source_handle": "branch",
                        "target": "agent",
                        "target_handle": "in",
                        "branch_key": "continue",
                    },
                    {
                        "id": "agent-end",
                        "source": "agent",
                        "source_handle": "next",
                        "target": "end",
                        "target_handle": "in",
                    },
                ],
            },
            "layout": {
                "nodes": {
                    "start": {"x": 0, "y": 0},
                    "command": {"x": 200, "y": 0},
                    "agent": {"x": 400, "y": 0},
                    "end": {"x": 600, "y": 0},
                },
                "viewport": {"x": 0, "y": 0, "zoom": 1},
            },
        }
    )
    assert admission.valid and document is not None
    return document


def _json(archive: ZipFile, path: str) -> dict:
    return json.loads(archive.read(path))


def _jsonl(archive: ZipFile, path: str) -> list[dict]:
    return [
        json.loads(line)
        for line in archive.read(path).decode("utf-8").splitlines()
        if line
    ]


def _minimal_archive_service(
    tmp_path: Path,
    *,
    node_read_mode: str,
) -> RuntimeMonitoringArchiveService:
    lifecycle_id = "lifecycle-archive"
    run_id = "run-archive"
    run = {
        "run_id": run_id,
        "status": "completed",
        "monitoring": {
            "graph": "available",
            "node": "available",
            "protocol": "available",
            "model": "available",
            "command": "available",
        },
    }
    graph = {
        "availability": "available",
        "read_at": "2026-01-01T00:00:00.000+00:00",
        "graph": {
            "document": {
                "definition": {
                    "nodes": [{"id": "agent", "type": "agent"}],
                }
            }
        },
    }
    read_at = "2026-01-01T00:00:00.000+00:00"

    def archive_node_attempts(*_args, after_sequence: int, **_kwargs):
        if node_read_mode == "partial" and after_sequence == 0:
            return [{
                "sequence": 1,
                "invocation_id": "invocation-1",
                "workflow_node_id": "agent",
            }]
        raise OSError("node archive read failed")

    async def application_query(call):
        return call()

    async def latest_state(*_args, **_kwargs):
        return {"availability": "not_enabled", "read_at": read_at, "state": None}

    async def agent_invocation(*_args, **_kwargs):
        return {
            "availability": "available",
            "read_at": read_at,
            "workflow_node_id": "agent",
            "artifact": {"messages": []},
        }

    def empty_partition(*_args, **_kwargs):
        return []

    queries = SimpleNamespace(
        archive_high_waters=lambda *_args: {
            run_id: {
                "node": 2 if node_read_mode == "partial" else 1,
                "protocol": 0,
                "model": 0,
                "command": 0,
            }
        },
        lifecycle=lambda *_args: {"lifecycle_status": "active"},
        archive_node_attempts=archive_node_attempts,
        archive_protocol_events=empty_partition,
        archive_model_requests=empty_partition,
        archive_command_observations=empty_partition,
    )
    reads = SimpleNamespace(
        application_query=application_query,
        snapshot=lambda *_args, **_kwargs: {
            "read_at": read_at,
            "lifecycle": {"lifecycle_id": lifecycle_id},
            "summary": {},
            "forest": {},
            "runs": [run],
        },
        graph=lambda *_args, **_kwargs: graph,
        latest_state=latest_state,
        agent_invocation=agent_invocation,
    )
    return RuntimeMonitoringArchiveService(
        reads,  # type: ignore[arg-type]
        queries,  # type: ignore[arg-type]
        tmp_path / "runtime" / "tmp",
    )


@pytest.mark.parametrize(
    ("node_read_mode", "expected_availability"),
    (("unavailable", "unavailable"), ("partial", "partial")),
)
def test_agent_invocation_index_preserves_node_partition_read_failure(
    tmp_path: Path,
    node_read_mode: str,
    expected_availability: str,
) -> None:
    async def scenario() -> None:
        service = _minimal_archive_service(
            tmp_path,
            node_read_mode=node_read_mode,
        )
        prepared = await service.prepare_run("lifecycle-archive", "run-archive")
        try:
            with ZipFile(prepared.path) as downloaded:
                manifest = _json(downloaded, "manifest.json")
                run_manifest = manifest["runs"][0]
                assert run_manifest["resources"]["node"]["availability"] == (
                    expected_availability
                )
                invocation_index = _json(
                    downloaded,
                    "runs/0001/agent-invocations/index.json",
                )
                assert invocation_index["availability"] == expected_availability
        finally:
            prepared.release()

    asyncio.run(scenario())


def test_archive_cancellation_waits_for_blocking_writer_before_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    zip_started = Event()
    allow_zip_to_finish = Event()

    def blocking_zip(_source: Path, _destination: Path) -> None:
        zip_started.set()
        allow_zip_to_finish.wait()

    async def scenario() -> set[Path]:
        service = _minimal_archive_service(tmp_path, node_read_mode="unavailable")
        monkeypatch.setattr(
            monitoring_archive_module,
            "_zip_directory",
            blocking_zip,
        )
        task = asyncio.create_task(
            service.prepare_run("lifecycle-archive", "run-archive")
        )
        assert await asyncio.to_thread(zip_started.wait, 5)
        task.cancel()
        try:
            done, _pending = await asyncio.wait({task}, timeout=0.05)
            assert not done
        finally:
            allow_zip_to_finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        return set((tmp_path / "runtime" / "tmp").glob("*"))

    assert asyncio.run(scenario()) == set()


def test_archive_reads_canonical_owners_and_stops_at_frozen_high_water(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class State(TypedDict):
        value: str

    async def scenario() -> tuple[set[str], set[str]]:
        database = SQLiteDatabase(tmp_path / "agent-shell.sqlite3")
        lifecycle = WorkflowLifecycleService(
            database,
            store_database=SQLiteFile(tmp_path / "workflow-store.sqlite3"),
        )
        checkpoints = WorkflowCheckpointService(
            SQLiteFile(tmp_path / "workflow-checkpoints.sqlite3", create=False)
        )
        queries = RuntimeMonitoringQueryStore(database)
        reads = MonitoringReadService(database, queries, lifecycle, checkpoints)
        archive_service = RuntimeMonitoringArchiveService(
            reads,
            queries,
            tmp_path / "runtime" / "tmp",
        )
        await lifecycle.start()
        try:
            thread_id = "checkpoint-root"
            lifecycle_id = await lifecycle.create(
                [{"role": "user", "content": "private lifecycle input"}],
                request_id="request-root",
                run_id="root",
                checkpoint_thread_id=thread_id,
                workflow_id="workflow-root",
                workflow_name="Root Workflow",
                workflow_document=_monitoring_document(),
                monitoring_capture_enabled=True,
            )
            lifecycle.register_run(
                {
                    "run_id": "child",
                    "lifecycle_id": lifecycle_id,
                    "request_id": "request-root",
                    "workflow_id": "workflow-child",
                    "workflow_name": "Called Workflow",
                    "caller_run_id": "root",
                    "operation_id": "spawn-child",
                },
                workflow_document=runtime_workflow_document(),
            )
            assert lifecycle.start_run("root")

            assert lifecycle.start_node_attempt(
                {
                    "lifecycle_id": lifecycle_id,
                    "run_id": "root",
                    "workflow_node_id": "command",
                    "invocation_id": "command-invocation",
                    "attempt": 1,
                    "node_first_attempt_time": None,
                    "started_at": "2026-01-01T00:00:00.000+00:00",
                }
            )
            assert lifecycle.finish_node_attempt(
                "root",
                "command-invocation",
                1,
                status="completed",
            )
            for attempt, status in ((1, "failed"), (2, "completed")):
                assert lifecycle.start_node_attempt(
                    {
                        "lifecycle_id": lifecycle_id,
                        "run_id": "root",
                        "workflow_node_id": "agent",
                        "invocation_id": "agent-invocation",
                        "attempt": attempt,
                        "node_first_attempt_time": (
                            "2026-01-01T00:00:00.000+00:00"
                            if attempt == 2
                            else None
                        ),
                        "started_at": (
                            f"2026-01-01T00:00:0{attempt}.000+00:00"
                        ),
                    }
                )
                assert lifecycle.finish_node_attempt(
                    "root",
                    "agent-invocation",
                    attempt,
                    status=status,
                    error_code="RuntimeError" if status == "failed" else "",
                )

            lifecycle.append_protocol_event(
                lifecycle_id,
                "root",
                {
                    "jsonrpc": "2.0",
                    "method": "messages",
                    "seq": 1,
                    "params": {"data": [{"text": "captured"}]},
                },
                source_type="agent",
                workflow_node_id="agent",
                node_invocation_id="agent-invocation",
                agent_profile_id=AGENT_ID,
                subagent_profile_id="",
            )
            lifecycle.start_model_request(
                {
                    "lifecycle_id": lifecycle_id,
                    "run_id": "root",
                    "model_run_id": "model-1",
                    "started_at": "2026-01-01T00:00:00.000+00:00",
                    "request": {"model": "test-model"},
                }
            )
            lifecycle.finish_model_request(
                "model-1",
                status="completed",
                usage={"total_tokens": 3},
            )
            for phase in ("started", "completed"):
                lifecycle.append_command_observation(
                    {
                        "lifecycle_id": lifecycle_id,
                        "run_id": "root",
                        "workflow_node_id": "command",
                        "invocation_id": "command-invocation",
                        "attempt": 1,
                        "occurred_at": "2026-01-01T00:00:00.000+00:00",
                        "phase": phase,
                        "payload": {"update": {"phase": phase}},
                    }
                )
            await lifecycle.store.aput(
                lifecycle_invocations_namespace(lifecycle_id, "root"),
                "agent-invocation",
                {
                    "invocation_id": "agent-invocation",
                    "workflow_id": "workflow-root",
                    "workflow_node_id": "agent",
                    "agent_id": AGENT_ID,
                    "invoked_at": "2026-01-01T00:00:00.000+00:00",
                    "messages": [
                        {"role": "assistant", "content": "completed artifact"}
                    ],
                },
                index=False,
            )
            checkpointer = await checkpoints.require_checkpointer()
            graph = (
                StateGraph(State)
                .add_node("write", lambda _state: {"value": "persisted"})
                .add_edge(START, "write")
                .add_edge("write", END)
                .compile(checkpointer=checkpointer)
            )
            await graph.ainvoke(
                {"value": "initial"},
                config={"configurable": {"thread_id": thread_id}},
                durability="sync",
            )

            original_protocol_read = queries.archive_protocol_events
            added_after_cut = False

            def archive_protocol_events(*args, **kwargs):
                nonlocal added_after_cut
                if not added_after_cut:
                    added_after_cut = True
                    lifecycle.append_protocol_event(
                        lifecycle_id,
                        "root",
                        {
                            "jsonrpc": "2.0",
                            "method": "messages",
                            "seq": 2,
                            "params": {"data": [{"text": "after cut"}]},
                        },
                        source_type="agent",
                        workflow_node_id="agent",
                        node_invocation_id="agent-invocation",
                        agent_profile_id=AGENT_ID,
                        subagent_profile_id="",
                    )
                return original_protocol_read(*args, **kwargs)

            monkeypatch.setattr(
                queries,
                "archive_protocol_events",
                archive_protocol_events,
            )
            lifecycle_archive = await archive_service.prepare_lifecycle(lifecycle_id)
            lifecycle_root = lifecycle_archive.path.parent
            with ZipFile(lifecycle_archive.path) as downloaded:
                names = set(downloaded.namelist())
                manifest = _json(downloaded, "manifest.json")
                assert manifest["schema"] == ARCHIVE_SCHEMA
                assert manifest["scope"] == "lifecycle"
                assert manifest["active_snapshot"] is True
                assert {item["run_id"] for item in manifest["runs"]} == {
                    "root",
                    "child",
                }
                root_manifest = next(
                    item for item in manifest["runs"] if item["run_id"] == "root"
                )
                root_directory = root_manifest["directory"]
                assert root_manifest["high_water"]["protocol"] == 1
                assert [
                    item["sequence"]
                    for item in _jsonl(
                        downloaded,
                        f"{root_directory}/protocol-events.jsonl",
                    )
                ] == [1]
                attempts = _jsonl(
                    downloaded,
                    f"{root_directory}/node-attempts.jsonl",
                )
                assert len(attempts) == 3
                agent_attempts = [
                    item for item in attempts
                    if item["invocation_id"] == "agent-invocation"
                ]
                assert [item["attempt"] for item in agent_attempts] == [1, 2]
                assert [item["status"] for item in agent_attempts] == [
                    "failed",
                    "completed",
                ]
                assert _jsonl(
                    downloaded,
                    f"{root_directory}/model-requests.jsonl",
                )[0]["request"] == {"model": "test-model"}
                assert len(
                    _jsonl(
                        downloaded,
                        f"{root_directory}/command-observations.jsonl",
                    )
                ) == 2
                assert _json(
                    downloaded,
                    f"{root_directory}/state.json",
                )["state"]["state"]["value"] == "persisted"
                invocation_index = _json(
                    downloaded,
                    f"{root_directory}/agent-invocations/index.json",
                )
                assert len(invocation_index["items"]) == 1
                invocation = invocation_index["items"][0]
                assert _json(downloaded, invocation["path"])["artifact"][
                    "messages"
                ][0]["content"] == "completed artifact"
                assert _json(
                    downloaded,
                    f"{root_directory}/graph.json",
                )["graph"]["workflow_id"] == "workflow-root"
                assert "input.json" not in names
                assert not any("unrelated-store-record" in name for name in names)
                assert not any("filesystem" in name for name in names)
                assert not any("checkpoint-history" in name for name in names)
                assert not any("diagnostic" in name for name in names)
            lifecycle_archive.release()
            assert not lifecycle_root.exists()

            run_archive = await archive_service.prepare_run(lifecycle_id, "root")
            run_root = run_archive.path.parent
            with ZipFile(run_archive.path) as downloaded:
                manifest = _json(downloaded, "manifest.json")
                assert manifest["scope"] == "run"
                assert manifest["selected_run_id"] == "root"
                assert [item["run_id"] for item in manifest["runs"]] == ["root"]
            run_archive.release()
            assert not run_root.exists()

            def fail_zip(_source: Path, _destination: Path) -> None:
                raise OSError("archive output unavailable")

            monkeypatch.setattr(
                monitoring_archive_module,
                "_zip_directory",
                fail_zip,
            )
            with pytest.raises(OSError, match="archive output unavailable"):
                await archive_service.prepare_run(lifecycle_id, "root")
            return (
                set((tmp_path / "runtime" / "tmp").glob("*")),
                names,
            )
        finally:
            await checkpoints.close()
            await lifecycle.close()
            await database.close()

    remaining, names = asyncio.run(scenario())
    assert remaining == set()
    assert "manifest.json" in names
