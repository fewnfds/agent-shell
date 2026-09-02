from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agent_shell.runtime.model_request_recorder import ModelRequestRecorder
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.run_identity import WorkflowRunIdentity
from agent_shell.runtime.state import AgentShellState, WorkflowState
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService
from agent_shell.storage.database import SQLiteDatabase, SQLiteFile
from agent_shell.storage.runtime_monitoring_queries import (
    RuntimeMonitoringQueryStore,
)
from agent_shell.workflow import admit_workflow_document
from agent_shell.workflow.compiler import _make_agent_node
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
            root_run = service.run("root-run")
            lifecycle = await service.record(lifecycle_id)
            assert root_run is not None
            assert lifecycle is not None
            assert root_run["workflow_id"] == "workflow-root-run"
            assert "run_kind" not in root_run
            assert "target_id" not in root_run
            assert lifecycle["root_status"] == "pending"
            assert "parent_status" not in lifecycle
            graph = RuntimeMonitoringQueryStore(
                SQLiteDatabase(database_path)
            ).graph(lifecycle_id, "root-run")
            assert graph is not None
            assert graph["document"] == document.model_dump(mode="json")
            assert "node_sources" not in graph
            assert "edge_classes" not in graph

            try:
                service.register_run(
                    {
                        "run_id": "child-run",
                        "lifecycle_id": lifecycle_id,
                        "request_id": "request-root-run",
                        "workflow_id": "duplicate",
                        "workflow_name": "Duplicate",
                        "parent_run_id": "root-run",
                        "background_task_id": "duplicate-task",
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
            "runtime_node_attempts",
            "runtime_run_graphs",
            "runtime_protocol_events",
            "runtime_model_requests",
            "runtime_command_observations",
        } <= tables
        assert "workflow_run_events" not in tables
        assert "runtime_managed_directories" not in tables

    asyncio.run(scenario())


def test_protocol_events_keep_raw_official_envelope(
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
            service.append_protocol_event(
                lifecycle_id,
                "event-run",
                envelope,
            )
            persisted = RuntimeMonitoringQueryStore(
                SQLiteDatabase(tmp_path / "agent-shell.sqlite3")
            ).protocol_events(
                lifecycle_id,
                "event-run",
                after_sequence=0,
                limit=10,
            )["items"]
            assert persisted[0]["envelope"] == envelope
            assert "origin" not in persisted[0]
            try:
                service.append_protocol_event(
                    lifecycle_id,
                    "event-run",
                    envelope,
                )
                raise AssertionError("duplicate (run_id, seq) must fail")
            except sqlite3.IntegrityError:
                pass
        finally:
            await service.close()

    asyncio.run(scenario())


def test_monitoring_facts_require_the_owning_run_lifecycle(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database_path = tmp_path / "agent-shell.sqlite3"
        service = _service(database_path)
        await service.start()
        try:
            first_lifecycle = await _create(
                service,
                run_id="first-run",
                document=_observed_document(),
                capture=True,
            )
            second_lifecycle = await _create(
                service,
                run_id="second-run",
                document=_observed_document(),
                capture=True,
            )
            assert first_lifecycle != second_lifecycle
            try:
                service.monitoring.start_node_attempt(
                    {
                        "lifecycle_id": second_lifecycle,
                        "run_id": "first-run",
                        "workflow_node_id": "agent",
                        "invocation_id": "cross-lifecycle",
                        "attempt": 1,
                        "node_first_attempt_time": None,
                        "started_at": "2026-01-01T00:00:00.000+00:00",
                    }
                )
                raise AssertionError("a monitoring fact must match its Run lifecycle")
            except sqlite3.IntegrityError:
                pass
        finally:
            await service.close()

        with SQLiteDatabase(database_path).transaction() as connection:
            rows = connection.execute(
                "SELECT 1 FROM runtime_node_attempts "
                "WHERE invocation_id = 'cross-lifecycle'"
            ).fetchall()
            assert rows == []

            for table in (
                "runtime_run_monitoring",
                "runtime_node_attempts",
                "runtime_run_graphs",
                "runtime_protocol_events",
                "runtime_model_requests",
                "runtime_command_observations",
            ):
                foreign_keys = connection.execute(
                    f"PRAGMA foreign_key_list({table})"
                ).fetchall()
                groups: dict[int, set[tuple[str, str, str]]] = {}
                for row in foreign_keys:
                    groups.setdefault(int(row["id"]), set()).add(
                        (str(row["table"]), str(row["from"]), str(row["to"]))
                    )
                assert {
                    ("runtime_workflow_runs", "lifecycle_id", "lifecycle_id"),
                    ("runtime_workflow_runs", "run_id", "run_id"),
                } in groups.values()

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
                RuntimeMonitoringQueryStore(
                    SQLiteDatabase(tmp_path / "agent-shell.sqlite3")
                ).model_requests(
                    lifecycle_id,
                    "model-run",
                    page=1,
                    page_size=10,
                )["items"],
                service.monitoring.status("model-run") or {},
            )
        finally:
            await service.close()

    requests, status = asyncio.run(scenario())
    assert [request["status"] for request in requests] == [
        "completed",
        "failed",
    ]
    assert requests[0]["usage"] == {
        "input_tokens": 3,
        "output_tokens": 2,
        "total_tokens": 5,
    }
    assert requests[0]["request"]["capture_layer"] == (
        "langchain.on_chat_model_start"
    )
    assert "main input" in json.dumps(requests[0]["request"])
    assert "agent_type" not in requests[0]
    assert "workflow_node_id" not in requests[0]
    assert requests[1]["error_code"] == "RuntimeError"
    assert status["model"] == "available"


def test_node_retry_preserves_invocation_and_records_each_official_attempt(
    tmp_path: Path,
) -> None:
    class BuiltAgent:
        agent_id = AGENT_ID
        input_state: dict[str, object] = {}

        def __init__(self, graph) -> None:
            self.graph = graph

    async def scenario() -> tuple[list[dict[str, object]], int]:
        database_path = tmp_path / "agent-shell.sqlite3"
        service = _service(database_path)
        await service.start()
        calls = 0

        def answer(_state: AgentShellState):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("retry this attempt")
            return {"messages": [AIMessage(content="complete")]}

        agent_graph = (
            StateGraph(AgentShellState)
            .add_node("answer", answer)
            .add_edge(START, "answer")
            .add_edge("answer", END)
            .compile()
        )
        try:
            lifecycle_id = await _create(
                service,
                run_id="retry-run",
                document=_observed_document(),
                capture=True,
            )
            assert service.start_run("retry-run")
            parent = StateGraph(
                WorkflowState,
                context_schema=WorkflowRuntimeContext,
            )
            parent.add_node(
                "agent",
                _make_agent_node(
                    node_id="agent",
                    built_agent=BuiltAgent(agent_graph),
                    lifecycle_service=service,
                ),
                retry_policy=RetryPolicy(
                    initial_interval=0,
                    max_attempts=2,
                    jitter=False,
                    retry_on=RuntimeError,
                ),
            )
            parent.add_edge(START, "agent")
            parent.add_edge("agent", END)
            graph = parent.compile(store=service.store)
            await graph.ainvoke(
                {"shared_vars": {}, "agent_invocations": {}},
                context=WorkflowRuntimeContext(
                    lifecycle_id=lifecycle_id,
                    workflow_run_id="retry-run",
                    workflow_id="workflow-retry-run",
                ),
            )
            assert service.finish_run("retry-run", status="completed")
            attempts = RuntimeMonitoringQueryStore(
                SQLiteDatabase(database_path)
            ).node_attempts(
                lifecycle_id,
                "retry-run",
                "agent",
                page=1,
                page_size=10,
            )["items"]
            return attempts, calls
        finally:
            await service.close()

    attempts, calls = asyncio.run(scenario())
    assert calls == 2
    assert [item["attempt"] for item in attempts] == [1, 2]
    assert [item["status"] for item in attempts] == ["failed", "completed"]
    assert len({item["invocation_id"] for item in attempts}) == 1
    assert len({item["node_first_attempt_time"] for item in attempts}) == 1


def test_terminal_runs_settle_node_attempts_missing_a_terminal_boundary(
    tmp_path: Path,
) -> None:
    async def scenario() -> tuple[dict[str, object], dict[str, object], dict, dict]:
        database_path = tmp_path / "agent-shell.sqlite3"
        service = _service(database_path)
        await service.start()
        try:
            completed_id = await _create(
                service,
                run_id="completed-run",
                document=_observed_document(),
                capture=True,
            )
            assert service.start_run("completed-run")
            service.start_node_attempt(
                {
                    "lifecycle_id": completed_id,
                    "run_id": "completed-run",
                    "workflow_node_id": "agent",
                    "invocation_id": "completed-invocation",
                    "attempt": 1,
                    "node_first_attempt_time": None,
                    "started_at": "2026-01-01T00:00:00.000+00:00",
                }
            )
            assert service.finish_run("completed-run", status="completed")

            interrupted_id = await _create(
                service,
                run_id="interrupted-run",
                document=_observed_document(),
                capture=True,
            )
            assert service.start_run("interrupted-run")
            service.start_node_attempt(
                {
                    "lifecycle_id": interrupted_id,
                    "run_id": "interrupted-run",
                    "workflow_node_id": "agent",
                    "invocation_id": "interrupted-invocation",
                    "attempt": 1,
                    "node_first_attempt_time": None,
                    "started_at": "2026-01-01T00:00:00.000+00:00",
                }
            )
            service.interrupt_active_runs()
            queries = RuntimeMonitoringQueryStore(SQLiteDatabase(database_path))
            completed = queries.node_attempts(
                completed_id,
                "completed-run",
                "agent",
                page=1,
                page_size=10,
            )["items"][0]
            interrupted = queries.node_attempts(
                interrupted_id,
                "interrupted-run",
                "agent",
                page=1,
                page_size=10,
            )["items"][0]
            return (
                completed,
                interrupted,
                service.monitoring.status("completed-run") or {},
                service.monitoring.status("interrupted-run") or {},
            )
        finally:
            await service.close()

    completed, interrupted, completed_status, interrupted_status = asyncio.run(
        scenario()
    )
    assert completed["status"] == "incomplete"
    assert interrupted["status"] == "interrupted"
    assert completed_status["node"] == "partial"
    assert interrupted_status["node"] == "partial"


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
                    "request": {},
                }
            )
            service.append_command_observation(
                {
                    "lifecycle_id": lifecycle_id,
                    "run_id": "partial-run",
                    "invocation_id": "unfinished-command",
                    "workflow_node_id": "command",
                    "attempt": 1,
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


def test_monitoring_finalize_read_failure_keeps_registry_terminal_result(
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
        try:
            await _create(
                service,
                run_id="finalize-read-failure",
                document=_observed_document(),
                capture=True,
            )
            assert service.start_run("finalize-read-failure")

            def fail_status(_run_id: str):
                raise OSError("monitoring status unavailable")

            monkeypatch.setattr(service.monitoring, "status", fail_status)
            assert service.finish_run(
                "finalize-read-failure",
                status="completed",
            )
            return service.run("finalize-read-failure") or {}, diagnostics.errors
        finally:
            await service.close()

    run, errors = asyncio.run(scenario())
    assert run["status"] == "completed"
    assert errors[0]["code"] == "runtime_monitoring_finalize_failed"


def test_monitoring_registration_failure_preserves_registry_and_is_reported(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> tuple[
        dict[str, object],
        dict[str, object],
        list[dict[str, object]],
    ]:
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
            return (
                service.run("registration-failure") or {},
                service.run_summary(lifecycle_id),
                diagnostics.errors,
            )
        finally:
            await service.close()

    run, summary, errors = asyncio.run(scenario())
    assert run["status"] == "pending"
    assert summary["run_count"] == 1
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
            queries = RuntimeMonitoringQueryStore(
                SQLiteDatabase(tmp_path / "agent-shell.sqlite3")
            )
            assert queries.graph(lifecycle_id, "disabled-run") is None
            service.append_protocol_event(
                lifecycle_id,
                "disabled-run",
                {"jsonrpc": "2.0", "method": "messages", "seq": 1},
            )
            assert service.start_model_request(
                {
                    "lifecycle_id": lifecycle_id,
                    "run_id": "disabled-run",
                    "model_run_id": "disabled-model",
                    "started_at": "2026-01-01T00:00:00.000+00:00",
                    "request": {},
                }
            ) is False
            assert service.start_node_attempt(
                {
                    "lifecycle_id": lifecycle_id,
                    "run_id": "disabled-run",
                    "workflow_node_id": "agent",
                    "invocation_id": "disabled-agent",
                    "attempt": 1,
                    "node_first_attempt_time": None,
                    "started_at": "2026-01-01T00:00:00.000+00:00",
                }
            ) is False
            service.append_command_observation(
                {
                    "lifecycle_id": lifecycle_id,
                    "run_id": "disabled-run",
                    "invocation_id": "disabled-command",
                    "workflow_node_id": "command",
                    "attempt": 1,
                    "occurred_at": "2026-01-01T00:00:00.000+00:00",
                    "phase": "started",
                }
            )
            assert service.start_run("disabled-run")
            assert service.finish_run("disabled-run", status="completed")
            record = await service.record(lifecycle_id)
            assert record is not None
            assert record["monitoring_capture_enabled"] is False
            assert service.run("disabled-run")["status"] == "completed"
            assert queries.protocol_events(
                lifecycle_id,
                "disabled-run",
                after_sequence=0,
                limit=10,
            )["items"] == []
            assert queries.node_attempts(
                lifecycle_id,
                "disabled-run",
                "agent",
                page=1,
                page_size=10,
            )["items"] == []
            assert queries.model_requests(
                lifecycle_id,
                "disabled-run",
                page=1,
                page_size=10,
            )["items"] == []
            assert queries.command_observations(
                lifecycle_id,
                "disabled-run",
                after_sequence=0,
                limit=10,
            )["items"] == []
        finally:
            await service.close()

    asyncio.run(scenario())
