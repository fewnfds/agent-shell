from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agent_shell.runtime.monitoring_read_service import (
    MonitoringInvocationNotFound,
    MonitoringReadService,
)
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


def _runtime(root: Path):
    database = SQLiteDatabase(root / "agent-shell.sqlite3")
    lifecycle = WorkflowLifecycleService(
        database,
        store_database=SQLiteFile(root / "workflow-store.sqlite3"),
    )
    checkpoints = WorkflowCheckpointService(
        SQLiteFile(root / "workflow-checkpoints.sqlite3", create=False)
    )
    queries = RuntimeMonitoringQueryStore(database)
    reads = MonitoringReadService(database, queries, lifecycle, checkpoints)
    return lifecycle, checkpoints, queries, reads


async def _create_root(
    lifecycle: WorkflowLifecycleService,
    *,
    document: WorkflowGraphDocumentV1,
    checkpoint_thread_id: str | None = None,
    capture: bool = True,
) -> str:
    return await lifecycle.create(
        [{"role": "user", "content": "observe"}],
        request_id="request-root",
        run_id="root",
        checkpoint_thread_id=checkpoint_thread_id,
        workflow_id="workflow-root",
        workflow_name="Root Workflow",
        workflow_document=document,
        monitoring_capture_enabled=capture,
    )


def test_snapshot_scopes_and_forest_use_only_registry_parent_facts(
    tmp_path: Path,
) -> None:
    async def scenario() -> tuple[dict, dict, dict, dict]:
        lifecycle, checkpoints, _queries, reads = _runtime(tmp_path)
        await lifecycle.start()
        try:
            lifecycle_id = await _create_root(
                lifecycle,
                document=runtime_workflow_document(),
            )

            def child(
                run_id: str,
                workflow_id: str,
                parent_run_id: str,
                depth: int,
            ) -> None:
                lifecycle.register_run(
                    {
                        "run_id": run_id,
                        "lifecycle_id": lifecycle_id,
                        "request_id": "request-root",
                        "workflow_id": workflow_id,
                        "workflow_name": workflow_id,
                        "parent_run_id": parent_run_id,
                        "background_task_id": f"task-{run_id}",
                        "run_depth": depth,
                    },
                    workflow_document=runtime_workflow_document(),
                )

            child("selected", "workflow-selected", "root", 1)
            child("descendant", "workflow-descendant", "selected", 2)
            child("sibling", "workflow-other", "root", 1)
            child("orphan", "workflow-orphan", "root", 1)
            with SQLiteDatabase(
                tmp_path / "agent-shell.sqlite3"
            ).transaction() as connection:
                connection.execute(
                    "UPDATE runtime_workflow_runs SET parent_run_id = NULL "
                    "WHERE run_id = 'orphan'"
                )
            lifecycle.mark_monitoring_partial("selected", "protocol")

            all_runs = reads.snapshot(
                lifecycle_id,
                scope="lifecycle",
                selector_id=None,
            )
            workflow = reads.snapshot(
                lifecycle_id,
                scope="workflow",
                selector_id="workflow-selected",
            )
            exact = reads.snapshot(
                lifecycle_id,
                scope="run",
                selector_id="selected",
            )
            repeated = reads.snapshot(
                lifecycle_id,
                scope="workflow",
                selector_id="workflow-selected",
            )
            return all_runs, workflow, exact, repeated
        finally:
            await checkpoints.close()
            await lifecycle.close()

    all_runs, workflow, exact, repeated = asyncio.run(scenario())
    assert {item["run_id"] for item in all_runs["runs"]} == {
        "root",
        "selected",
        "descendant",
        "sibling",
        "orphan",
    }
    assert all_runs["forest"]["orphan_run_ids"] == ["orphan"]
    assert all_runs["forest"]["relationship_availability"] == "partial"
    assert {item["run_id"] for item in workflow["runs"]} == {
        "selected",
        "descendant",
    }
    assert workflow["forest"]["root_run_ids"] == ["selected"]
    assert workflow["forest"]["orphan_run_ids"] == []
    assert workflow["forest"]["relationship_availability"] == "available"
    assert workflow["forest"]["relationships"] == [
        {"parent_run_id": "selected", "child_run_id": "descendant"}
    ]
    assert workflow["summary"]["partition_availability"]["protocol"] == "partial"
    assert [item["run_id"] for item in exact["runs"]] == ["selected"]
    assert exact["forest"]["orphan_run_ids"] == []
    assert exact["forest"]["relationship_availability"] == "available"
    comparable = deepcopy(workflow)
    comparable.pop("read_at")
    repeated.pop("read_at")
    assert repeated == comparable


def test_resources_page_and_resume_from_their_native_sequences(
    tmp_path: Path,
) -> None:
    async def scenario() -> dict[str, dict]:
        lifecycle, checkpoints, _queries, reads = _runtime(tmp_path)
        await lifecycle.start()
        try:
            lifecycle_id = await _create_root(
                lifecycle,
                document=_monitoring_document(),
            )
            assert lifecycle.start_run("root")
            for node_id, invocation_id in (
                ("command", "command-invocation"),
                ("agent", "agent-invocation"),
            ):
                lifecycle.start_node_attempt(
                    {
                        "lifecycle_id": lifecycle_id,
                        "run_id": "root",
                        "workflow_node_id": node_id,
                        "invocation_id": invocation_id,
                        "attempt": 1,
                        "node_first_attempt_time": None,
                        "started_at": "2026-01-01T00:00:00.000+00:00",
                    }
                )
                lifecycle.finish_node_attempt(
                    "root",
                    invocation_id,
                    1,
                    status="completed",
                )
            for sequence in (1, 2):
                is_agent_event = sequence == 1
                lifecycle.append_protocol_event(
                    lifecycle_id,
                    "root",
                    {
                        "jsonrpc": "2.0",
                        "method": "messages",
                        "seq": sequence,
                        "params": {"data": [{"sequence": sequence}]},
                    },
                    source_type="agent" if is_agent_event else "non_agent",
                    workflow_node_id="agent" if is_agent_event else "",
                    node_invocation_id=(
                        "agent-invocation" if is_agent_event else ""
                    ),
                    agent_profile_id=AGENT_ID if is_agent_event else "",
                    subagent_profile_id="",
                )
            for model_id in ("model-1", "model-2"):
                lifecycle.start_model_request(
                    {
                        "lifecycle_id": lifecycle_id,
                        "run_id": "root",
                        "model_run_id": model_id,
                        "started_at": "2026-01-01T00:00:00.000+00:00",
                        "request": {"model": model_id},
                    }
                )
                lifecycle.finish_model_request(
                    model_id,
                    status="completed",
                    usage={"total_tokens": 1},
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
                        "payload": {"phase": phase},
                    }
                )
            assert lifecycle.finish_run("root", status="completed")

            protocol = reads.protocol_events(
                lifecycle_id,
                "root",
                after_sequence=1,
                limit=1,
                method=None,
            )
            first_command = reads.command_observations(
                lifecycle_id,
                "root",
                after_sequence=0,
                limit=1,
                node_id="command",
                phase=None,
            )
            second_command = reads.command_observations(
                lifecycle_id,
                "root",
                after_sequence=first_command["next_after_sequence"],
                limit=1,
                node_id="command",
                phase=None,
            )
            return {
                "graph": reads.graph(lifecycle_id, "root"),
                "nodes_1": reads.node_summaries(
                    lifecycle_id,
                    "root",
                    page=1,
                    page_size=1,
                    status=None,
                ),
                "nodes_2": reads.node_summaries(
                    lifecycle_id,
                    "root",
                    page=2,
                    page_size=1,
                    status=None,
                ),
                "attempts": reads.node_attempts(
                    lifecycle_id,
                    "root",
                    "agent",
                    page=1,
                    page_size=10,
                    status="completed",
                ),
                "protocol": protocol,
                "agent_protocol": reads.protocol_events(
                    lifecycle_id,
                    "root",
                    after_sequence=0,
                    limit=10,
                    method=None,
                    node_id="agent",
                    invocation_id="agent-invocation",
                ),
                "protocol_repeated": reads.protocol_events(
                    lifecycle_id,
                    "root",
                    after_sequence=1,
                    limit=1,
                    method=None,
                ),
                "models": reads.model_requests(
                    lifecycle_id,
                    "root",
                    page=2,
                    page_size=1,
                    status="completed",
                ),
                "commands_1": first_command,
                "commands_2": second_command,
            }
        finally:
            await checkpoints.close()
            await lifecycle.close()

    result = asyncio.run(scenario())
    assert result["graph"]["availability"] == "available"
    assert result["graph"]["graph"]["document"]["definition"]["nodes"]
    assert result["nodes_1"]["total"] == 2
    assert result["nodes_1"]["items"] != result["nodes_2"]["items"]
    assert result["attempts"]["items"][0]["invocation_id"] == "agent-invocation"
    assert [item["sequence"] for item in result["protocol"]["items"]] == [2]
    assert [
        item["sequence"] for item in result["agent_protocol"]["items"]
    ] == [1]
    assert result["agent_protocol"]["items"][0]["origin"] == {
        "source_type": "agent",
        "workflow_node_id": "agent",
        "node_invocation_id": "agent-invocation",
        "agent_profile_id": AGENT_ID,
        "subagent_profile_id": "",
    }
    protocol_copy = deepcopy(result["protocol"])
    repeated_copy = deepcopy(result["protocol_repeated"])
    protocol_copy.pop("read_at")
    repeated_copy.pop("read_at")
    assert repeated_copy == protocol_copy
    assert result["models"]["items"][0]["model_run_id"] == "model-2"
    assert result["commands_1"]["items"][0]["phase"] == "started"
    assert result["commands_2"]["items"][0]["phase"] == "completed"


def test_latest_state_and_completed_agent_artifact_use_exact_public_owners(
    tmp_path: Path,
) -> None:
    class State(TypedDict):
        value: str

    async def run() -> tuple[dict, dict]:
        lifecycle, checkpoints, _queries, reads = _runtime(tmp_path)
        await lifecycle.start()
        try:
            thread_id = "checkpoint-thread"
            lifecycle_id = await _create_root(
                lifecycle,
                document=_monitoring_document(),
                checkpoint_thread_id=thread_id,
            )
            assert lifecycle.start_run("root")
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
            lifecycle.start_node_attempt(
                {
                    "lifecycle_id": lifecycle_id,
                    "run_id": "root",
                    "workflow_node_id": "agent",
                    "invocation_id": "agent-invocation",
                    "attempt": 1,
                    "node_first_attempt_time": None,
                    "started_at": "2026-01-01T00:00:00.000+00:00",
                }
            )
            lifecycle.finish_node_attempt(
                "root",
                "agent-invocation",
                1,
                status="completed",
            )
            await lifecycle.store.aput(
                lifecycle_invocations_namespace(lifecycle_id, "root"),
                "agent-invocation",
                {
                    "invocation_id": "agent-invocation",
                    "workflow_id": "workflow-root",
                    "workflow_node_id": "agent",
                    "agent_id": AGENT_ID,
                    "invoked_at": None,
                    "messages": [{"role": "assistant", "content": "complete"}],
                },
                index=False,
            )
            state = await reads.latest_state(lifecycle_id, "root")
            artifact = await reads.agent_invocation(
                lifecycle_id,
                "root",
                "agent-invocation",
            )
            with pytest.raises(MonitoringInvocationNotFound):
                await reads.agent_invocation(
                    lifecycle_id,
                    "root",
                    "missing-invocation",
                )
            return state, artifact
        finally:
            await checkpoints.close()
            await lifecycle.close()

    state, artifact = asyncio.run(run())
    assert state["availability"] == "available"
    assert state["state"]["checkpoint_ns"] == ""
    assert state["state"]["state"]["value"] == "persisted"
    assert artifact["availability"] == "available"
    assert artifact["workflow_node_id"] == "agent"
    assert artifact["artifact"]["messages"][-1]["content"] == "complete"


def test_one_resource_read_failure_does_not_hide_other_snapshot_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> tuple[dict, dict]:
        lifecycle, checkpoints, queries, reads = _runtime(tmp_path)
        await lifecycle.start()
        try:
            lifecycle_id = await _create_root(
                lifecycle,
                document=runtime_workflow_document(),
            )

            def unavailable(*_args, **_kwargs):
                raise OSError("protocol table unavailable")

            def node_counts_unavailable(*_args, **_kwargs):
                raise OSError("node attempts table unavailable")

            monkeypatch.setattr(queries, "protocol_events", unavailable)
            resource = reads.protocol_events(
                lifecycle_id,
                "root",
                after_sequence=0,
                limit=10,
                method=None,
            )
            monkeypatch.setattr(
                queries,
                "scope_node_attempt_status_counts",
                node_counts_unavailable,
            )
            snapshot = reads.snapshot(
                lifecycle_id,
                scope="lifecycle",
                selector_id=None,
            )
            return resource, snapshot
        finally:
            await checkpoints.close()
            await lifecycle.close()

    resource, snapshot = asyncio.run(scenario())
    assert resource["availability"] == "unavailable"
    assert resource["items"] == []
    assert snapshot["summary"]["run_count"] == 1
    assert snapshot["runs"][0]["run_id"] == "root"
    assert snapshot["summary"]["node_attempt_status_counts"] == {}
    assert snapshot["summary"]["partition_availability"]["node"] == "unavailable"
