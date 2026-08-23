from __future__ import annotations

import asyncio
import sqlite3

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from agent_shell.runtime.agent_builder import BuiltAgent
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.input_messages import client_messages_sha
from agent_shell.runtime.state import AgentShellState
from agent_shell.runtime.workflow_checkpoints import WorkflowCheckpointService
from agent_shell.runtime.workflow_lifecycle import (
    LIFECYCLE_INPUT_KEY,
    WorkflowLifecycleService,
    lifecycle_input_namespace,
)
from agent_shell.storage.database import SQLiteDatabase, SQLiteFile
from agent_shell.workflow import admit_workflow_document, compile_workflow


AGENT_ID = "11111111-1111-4111-8111-111111111111"


class _MiddlewareRuntime:
    async def close(self) -> None:
        return None


def _workflow_payload() -> dict[str, object]:
    return {
        "definition": {
            "schema_version": 1,
            "state_contract": "agent-shell.workflow.agent-invocations.v1",
            "nodes": [
                {"id": "start", "type": "start", "type_version": 1, "config": {}},
                {
                    "id": "agent-1",
                    "type": "agent",
                    "type_version": 1,
                    "config": {"main_agent_id": AGENT_ID},
                },
                {"id": "end", "type": "end", "type_version": 1, "config": {}},
            ],
            "edges": [
                {
                    "id": "start-agent",
                    "source": "start",
                    "source_handle": "next",
                    "target": "agent-1",
                    "target_handle": "in",
                },
                {
                    "id": "agent-end",
                    "source": "agent-1",
                    "source_handle": "next",
                    "target": "end",
                    "target_handle": "in",
                },
            ],
        },
        "layout": {
            "nodes": {
                "start": {"x": 0, "y": 0},
                "agent-1": {"x": 240, "y": 0},
                "end": {"x": 480, "y": 0},
            },
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    }


def test_workflow_checkpointer_persists_state_without_turning_input_into_chat_state(
    tmp_path,
) -> None:
    async def scenario() -> None:
        state_root = tmp_path / "data" / "state"
        database = SQLiteDatabase(state_root / "agent-shell.sqlite3")
        checkpoint_database = SQLiteFile(
            state_root / "workflow-checkpoints.sqlite3"
        )
        store_database = SQLiteFile(state_root / "workflow-store.sqlite3")
        service = WorkflowCheckpointService(
            checkpoint_database,
            tracing_enabled=False,
            langsmith_project="workflow-checkpoint-test",
        )
        lifecycle = WorkflowLifecycleService(
            database,
            store_database=store_database,
        )
        raw_messages = [
            {"role": "system", "content": "private-system-attention-sentinel"},
            {"role": "assistant", "content": "private-assistant-data-sentinel"},
            {"role": "user", "content": "private-user-data-sentinel"},
        ]
        messages_sha = client_messages_sha(raw_messages)
        observed_root_messages: list[object] = []

        def inspect_state(state: AgentShellState) -> dict[str, object]:
            observed_root_messages.extend(state.get("messages", []))
            return {
                "messages": [AIMessage(content="complete")],
                "shared_vars": {"result": "complete"},
            }

        agent_graph = (
            StateGraph(AgentShellState, context_schema=WorkflowRuntimeContext)
            .add_node("inspect", inspect_state)
            .add_edge(START, "inspect")
            .add_edge("inspect", END)
            .compile()
        )
        admission, document = admit_workflow_document(_workflow_payload())
        assert admission.valid is True
        assert document is not None

        await lifecycle.start()
        await service.start()
        try:
            run = service.create_context(
                request_id="request-1",
                workflow_id="workflow-1",
                workflow_name="Checkpoint Workflow",
                messages_sha=messages_sha,
            )
            lifecycle_id = await lifecycle.create(
                raw_messages,
                request_id="request-1",
                run_id=str(run.run_id),
                thread_id=run.thread_id,
                workflow_id="workflow-1",
                workflow_name="Checkpoint Workflow",
            )
            context = WorkflowRuntimeContext.for_run(
                request_id="request-1",
                lifecycle_id=lifecycle_id,
                run_id=str(run.run_id),
                thread_id=run.thread_id,
                workflow={"id": "workflow-1", "name": "Checkpoint Workflow"},
            )
            graph = compile_workflow(
                document,
                node_agents={
                    "agent-1": BuiltAgent(
                        graph=agent_graph,
                        input_state={"messages": [], "shared_vars": {}},
                        event_output_id="",
                        event_output_reference={},
                        agent_id=AGENT_ID,
                        agent_name="Checkpoint Agent",
                        subagent_profile_ids={},
                        middleware_runtime=_MiddlewareRuntime(),  # type: ignore[arg-type]
                    )
                },
                checkpointer=service.checkpointer,
                store=lifecycle.store,
            )

            result = await graph.ainvoke(
                {"shared_vars": {}, "agent_invocations": {}},
                config=run.config(),
                context=context,
                durability="sync",
            )

            assert result["shared_vars"] == {"result": "complete"}
            assert observed_root_messages == []
            checkpoints = await service.checkpoint_history(run.thread_id)
            assert checkpoints
            assert all(checkpoint["checkpoint_id"] for checkpoint in checkpoints)

            lifecycle_input = await lifecycle.store.aget(
                lifecycle_input_namespace(lifecycle_id),
                LIFECYCLE_INPUT_KEY,
            )
            assert lifecycle_input is not None
            assert lifecycle_input.value["messages"] == raw_messages
            assert lifecycle_input.value["messages_sha"] == messages_sha

            assert await service.purge_thread(run.thread_id) is True
            assert await service.checkpoint_count(run.thread_id) == 0
        finally:
            await service.close()
            await lifecycle.close()

    asyncio.run(scenario())


def test_langgraph_store_and_checkpointer_own_distinct_sqlite_files(
    tmp_path,
) -> None:
    async def scenario() -> None:
        state_root = tmp_path / "data" / "state"
        application_path = state_root / "agent-shell.sqlite3"
        checkpoint_path = state_root / "workflow-checkpoints.sqlite3"
        store_path = state_root / "workflow-store.sqlite3"
        application_database = SQLiteDatabase(application_path)
        checkpoints = WorkflowCheckpointService(
            SQLiteFile(checkpoint_path),
            tracing_enabled=False,
            langsmith_project="workflow-database-ownership-test",
        )
        lifecycle = WorkflowLifecycleService(
            application_database,
            store_database=SQLiteFile(store_path),
        )

        await lifecycle.start()
        await checkpoints.start()
        try:
            await lifecycle.create(
                [{"role": "user", "content": "input"}],
                request_id="ownership-request",
                run_id="ownership-run",
                thread_id="ownership-thread",
                workflow_id="ownership-workflow",
                workflow_name="Ownership Workflow",
            )
        finally:
            await checkpoints.close()
            await lifecycle.close()

        def tables(path) -> set[str]:
            with sqlite3.connect(path) as connection:
                return {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }

        application_tables = tables(application_path)
        checkpoint_tables = tables(checkpoint_path)
        store_tables = tables(store_path)
        assert "workflow_lifecycles" in application_tables
        assert "checkpoints" not in application_tables
        assert "store" not in application_tables
        assert "checkpoints" in checkpoint_tables
        assert "workflow_lifecycles" not in checkpoint_tables
        assert "store" in store_tables
        assert "workflow_lifecycles" not in store_tables

    asyncio.run(scenario())
