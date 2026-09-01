from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from agent_shell.runtime.model_request_recorder import ModelRequestRecorder
from agent_shell.runtime.run_identity import WorkflowRunIdentity
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService
from agent_shell.storage.database import SQLiteDatabase, SQLiteFile
from agent_shell.workflow import admit_workflow_document
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1
from support import runtime_workflow_document


AGENT_ID = "11111111-1111-4111-8111-111111111111"
COMMAND_ID = "22222222-2222-4222-8222-222222222222"


def _service(path: Path, *, diagnostics=None) -> WorkflowLifecycleService:
    return WorkflowLifecycleService(
        SQLiteDatabase(path),
        store_database=SQLiteFile(path.with_name("workflow-store.sqlite3")),
        runtime_diagnostics=diagnostics,
    )


def _observed_document() -> WorkflowGraphDocumentV1:
    report, document = admit_workflow_document(
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
    assert report.valid and document is not None
    return document


class _Diagnostics:
    def __init__(self) -> None:
        self.errors: list[dict[str, object]] = []

    def observation_error(self, exc, **kwargs) -> None:
        self.errors.append({"error": exc, **kwargs})


async def _create(
    service: WorkflowLifecycleService,
    *,
    run_id: str,
    document: WorkflowGraphDocumentV1,
    capture: bool,
) -> str:
    return await service.create(
        [{"role": "user", "content": f"input-{run_id}"}],
        request_id=f"request-{run_id}",
        run_id=run_id,
        checkpoint_thread_id=None,
        workflow_id=f"workflow-{run_id}",
        workflow_name=f"Workflow {run_id}",
        workflow_document=document,
        monitoring_capture_enabled=capture,
    )


def test_runtime_schema_and_registration_keep_one_control_record_and_frozen_graph(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database_path = tmp_path / "agent-shell.sqlite3"
        service = _service(database_path)
        document = _observed_document()
        await service.start()
        try:
            lifecycle_id = await _create(
                service,
                run_id="root-run",
                document=document,
                capture=True,
            )
            service.register_run(
                {
                    "run_id": "child-run",
                    "lifecycle_id": lifecycle_id,
                    "request_id": "request-root-run",
                    "workflow_id": "child-workflow",
                    "workflow_name": "Child Workflow",
                    "parent_run_id": "root-run",
                    "background_task_id": "task-1",
                    "run_depth": 1,
                },
                workflow_document=runtime_workflow_document(),
            )

            assert [run["run_id"] for run in service.runs(lifecycle_id)] == [
                "root-run",
                "child-run",
            ]
            graph = service.monitoring.graph("root-run")
            assert graph is not None
            assert graph["document"] == document.model_dump(mode="json")
            assert {item["source_id"] for item in graph["node_sources"]} >= {
                AGENT_ID,
                COMMAND_ID,
            }
            assert {
                item["edge_class"] for item in graph["edge_classes"]
            } == {"normal", "branch"}

            try:
                service.register_run(
                    {
                        "run_id": "child-run",
                        "lifecycle_id": lifecycle_id,
                        "request_id": "duplicate",
                        "workflow_id": "duplicate",
                        "workflow_name": "Duplicate",
                        "run_depth": 1,
                    },
                    workflow_document=runtime_workflow_document(),
                )
                raise AssertionError("duplicate Run registration must fail")
            except sqlite3.IntegrityError:
                pass
        finally:
            await service.close()

        with SQLiteDatabase(database_path).transaction() as connection:
            tables = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert {
            "runtime_lifecycles",
            "runtime_workflow_runs",
            "runtime_run_monitoring",
            "runtime_run_graphs",
            "runtime_protocol_events",
            "runtime_model_requests",
            "runtime_command_observations",
        } <= tables
        assert "workflow_run_events" not in tables

    asyncio.run(scenario())


def test_protocol_events_keep_official_envelope_and_origin_sidecar(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = _service(tmp_path / "agent-shell.sqlite3")
        await service.start()
        try:
            lifecycle_id = await _create(
                service,
                run_id="event-run",
                document=runtime_workflow_document(),
                capture=True,
            )
            envelope = {
                "jsonrpc": "2.0",
                "method": "messages",
                "seq": 1,
                "params": {
                    "namespace": ["agent:one"],
                    "data": [{"event": "message-start"}],
                },
            }
            origin = {
                "namespace": ["agent:one"],
                "cycle_key": "cycle-1",
                "source_type": "agent",
                "workflow_node_id": "agent",
                "node_invocation_id": "invocation-1",
                "agent_profile_id": AGENT_ID,
                "subagent_profile_id": "",
            }
            service.append_protocol_event(
                lifecycle_id,
                "event-run",
                envelope,
                origin,
            )
            persisted = service.protocol_events(
                lifecycle_id,
                run_id="event-run",
            )
            assert persisted[0]["envelope"] == envelope
            assert persisted[0]["origin"] == origin
            try:
                service.append_protocol_event(
                    lifecycle_id,
                    "event-run",
                    envelope,
                    origin,
                )
                raise AssertionError("duplicate (run_id, seq) must fail")
            except sqlite3.IntegrityError:
                pass
        finally:
            await service.close()

    asyncio.run(scenario())


def test_model_request_recorder_uses_official_start_end_error_boundary(
    tmp_path: Path,
) -> None:
    async def scenario() -> tuple[list[dict[str, object]], dict[str, object]]:
        service = _service(tmp_path / "agent-shell.sqlite3")
        await service.start()
        try:
            lifecycle_id = await _create(
                service,
                run_id="model-run",
                document=_observed_document(),
                capture=True,
            )
            assert service.start_run("model-run")
            identity = WorkflowRunIdentity(
                request_id="request-model-run",
                lifecycle_id=lifecycle_id,
                workflow_run_id="model-run",
                workflow_id="workflow-model-run",
                workflow_name="Model Workflow",
            )
            recorder = ModelRequestRecorder(
                service,
                None,
                identity,
                agent_names={"agent": "Writer"},
                agent_profile_ids={"agent": AGENT_ID},
                subagent_profile_ids={"agent": {"Researcher": "subagent-id"}},
            )
            main_id = uuid4()
            recorder.on_chat_model_start(
                {"name": "provider-model"},
                [[HumanMessage(content="main input")]],
                run_id=main_id,
                metadata={
                    "langgraph_node": "agent",
                    "lc_agent_name": "Writer",
                },
                invocation_params={"tools": [{"name": "search"}]},
            )
            recorder.on_llm_end(
                LLMResult(
                    generations=[
                        [
                            ChatGeneration(
                                message=AIMessage(
                                    content="done",
                                    usage_metadata={
                                        "input_tokens": 3,
                                        "output_tokens": 2,
                                        "total_tokens": 5,
                                    },
                                )
                            )
                        ]
                    ]
                ),
                run_id=main_id,
            )
            subagent_id = uuid4()
            recorder.on_chat_model_start(
                {"name": "provider-model"},
                [[HumanMessage(content="subagent input")]],
                run_id=subagent_id,
                metadata={
                    "langgraph_node": "agent",
                    "lc_agent_name": "Researcher",
                },
            )
            recorder.on_llm_error(
                RuntimeError("provider failed"),
                run_id=subagent_id,
            )
            service.finish_run("model-run", status="completed")
            return (
                service.model_requests(lifecycle_id, run_id="model-run"),
                service.monitoring.status("model-run") or {},
            )
        finally:
            await service.close()

    requests, status = asyncio.run(scenario())
    assert [request["status"] for request in requests] == [
        "completed",
        "failed",
    ]
    assert requests[0]["agent_type"] == "main_agent"
    assert requests[0]["agent_id"] == AGENT_ID
    assert requests[0]["usage"] == {
        "input_tokens": 3,
        "output_tokens": 2,
        "total_tokens": 5,
    }
    assert requests[0]["request"]["capture_layer"] == (
        "langchain.on_chat_model_start"
    )
    assert "main input" in json.dumps(requests[0]["request"])
    assert requests[1]["agent_type"] == "subagent"
    assert requests[1]["agent_id"] == "subagent-id"
    assert requests[1]["parent_agent_id"] == AGENT_ID
    assert requests[1]["error_code"] == "RuntimeError"
    assert status["model"] == "available"


def test_monitoring_failure_is_partition_local_and_unclosed_facts_are_partial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> tuple[dict[str, object], list[dict[str, object]]]:
        diagnostics = _Diagnostics()
        service = _service(
            tmp_path / "agent-shell.sqlite3",
            diagnostics=diagnostics,
        )
        await service.start()
        original = service.monitoring.save_graph

        def fail_graph(_record) -> None:
            raise OSError("graph writer unavailable")

        monkeypatch.setattr(service.monitoring, "save_graph", fail_graph)
        try:
            lifecycle_id = await _create(
                service,
                run_id="partial-run",
                document=_observed_document(),
                capture=True,
            )
            monkeypatch.setattr(service.monitoring, "save_graph", original)
            assert service.start_run("partial-run")
            service.start_model_request(
                {
                    "lifecycle_id": lifecycle_id,
                    "run_id": "partial-run",
                    "model_run_id": "unfinished-model",
                    "started_at": "2026-01-01T00:00:00.000+00:00",
                    "agent_type": "main_agent",
                    "agent_id": AGENT_ID,
                    "agent_name": "Writer",
                    "request": {},
                }
            )
            service.append_command_observation(
                {
                    "lifecycle_id": lifecycle_id,
                    "run_id": "partial-run",
                    "invocation_id": "unfinished-command",
                    "workflow_node_id": "command",
                    "occurred_at": "2026-01-01T00:00:00.000+00:00",
                    "phase": "started",
                }
            )
            assert service.finish_run("partial-run", status="failed")
            return service.monitoring.status("partial-run") or {}, diagnostics.errors
        finally:
            await service.close()

    status, errors = asyncio.run(scenario())
    assert status["graph"] == "partial"
    assert status["protocol"] == "available"
    assert status["model"] == "partial"
    assert status["command"] == "partial"
    assert errors[0]["code"] == "runtime_graph_record_failed"


def test_monitoring_registration_failure_is_reported_as_partial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> tuple[dict[str, object], list[dict[str, object]]]:
        diagnostics = _Diagnostics()
        service = _service(
            tmp_path / "agent-shell.sqlite3",
            diagnostics=diagnostics,
        )
        await service.start()

        def fail_registration(**_kwargs) -> None:
            raise OSError("monitoring registration unavailable")

        monkeypatch.setattr(
            service.monitoring,
            "initialize_run",
            fail_registration,
        )
        try:
            lifecycle_id = await _create(
                service,
                run_id="registration-failure",
                document=_observed_document(),
                capture=True,
            )
            return service.run_summary(lifecycle_id), diagnostics.errors
        finally:
            await service.close()

    summary, errors = asyncio.run(scenario())
    assert summary["observation_status"] == "partial"
    assert errors[0]["code"] == "runtime_monitoring_registration_failed"


def test_capture_disabled_keeps_only_required_control_facts_until_cleanup(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = _service(tmp_path / "agent-shell.sqlite3")
        await service.start()
        try:
            lifecycle_id = await _create(
                service,
                run_id="disabled-run",
                document=_observed_document(),
                capture=False,
            )
            assert service.monitoring.status("disabled-run") is None
            assert service.monitoring.graph("disabled-run") is None
            assert service.start_run("disabled-run")
            assert service.finish_run("disabled-run", status="completed")
            record = await service.record(lifecycle_id)
            assert record is not None
            assert record["monitoring_capture_enabled"] is False
            assert service.run("disabled-run")["status"] == "completed"
            assert service.protocol_events(
                lifecycle_id,
                run_id="disabled-run",
            ) == []
        finally:
            await service.close()

    asyncio.run(scenario())
