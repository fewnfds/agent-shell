from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService
from agent_shell.runtime.workflow_run_journal import WorkflowRunJournal
from agent_shell.storage.database import SQLiteDatabase


class _Diagnostics:
    def __init__(self) -> None:
        self.errors: list[dict[str, object]] = []

    def observation_error(self, exc, **kwargs) -> None:
        self.errors.append({"error": exc, **kwargs})


def test_run_history_distinguishes_repeated_node_spans_and_structural_events_omit_payloads(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        database = SQLiteDatabase(tmp_path / "data" / "state" / "agent-shell.sqlite3")
        lifecycle = WorkflowLifecycleService(database)
        await lifecycle.start()
        try:
            lifecycle_id = await lifecycle.create(
                [{"role": "user", "content": "private-journal-sentinel"}],
                request_id="request-1",
                run_id="root-run",
                thread_id="root-thread",
                workflow_id="workflow-1",
                workflow_name="Parent Workflow",
            )
            assert lifecycle.start_run("root-run") is True
            context = WorkflowRuntimeContext.for_run(
                request_id="request-1",
                lifecycle_id=lifecycle_id,
                run_id="root-run",
                thread_id="root-thread",
                workflow={"id": "workflow-1", "name": "Parent Workflow"},
            )
            diagnostics = _Diagnostics()
            journal = WorkflowRunJournal(
                lifecycle,
                diagnostics,  # type: ignore[arg-type]
                context,
                workflow_node_kinds={"agent-node": "agent"},
                agent_names={"agent-node": "Writer Agent"},
                agent_profile_ids={"agent-node": "main-agent-profile"},
            )

            first = uuid4()
            second = uuid4()
            journal.on_chain_start(
                {},
                {"secret": "private-journal-sentinel"},
                run_id=first,
                name="agent-node",
                metadata={"langgraph_node": "agent-node", "langgraph_step": 1},
            )
            journal.on_chain_end({}, run_id=first)
            journal.on_chain_start(
                {},
                {"secret": "private-journal-sentinel"},
                run_id=second,
                name="agent-node",
                metadata={"langgraph_node": "agent-node", "langgraph_step": 2},
            )
            ignored_chain = uuid4()
            journal.on_chain_start(
                {},
                {},
                run_id=ignored_chain,
                parent_run_id=second,
                name="internal-sequence",
            )
            agent_span = uuid4()
            journal.on_chain_start(
                {},
                {},
                run_id=agent_span,
                parent_run_id=ignored_chain,
                name="Writer Agent",
            )
            model_span = uuid4()
            journal.on_chat_model_start(
                {"name": "provider-model"},
                [["private-journal-sentinel"]],
                run_id=model_span,
                parent_run_id=agent_span,
            )
            journal.on_llm_end(
                LLMResult(
                    generations=[
                        [
                            ChatGeneration(
                                message=AIMessage(
                                    content="done",
                                    usage_metadata={
                                        "input_tokens": 4,
                                        "output_tokens": 2,
                                        "total_tokens": 6,
                                    },
                                )
                            )
                        ]
                    ]
                ),
                run_id=model_span,
            )
            tool_span = uuid4()
            journal.on_tool_start(
                {"name": "search"},
                "private-journal-sentinel",
                run_id=tool_span,
                parent_run_id=agent_span,
            )
            journal.on_tool_end("private-journal-sentinel", run_id=tool_span)
            journal.on_chain_end({}, run_id=agent_span)
            journal.on_chain_end({}, run_id=ignored_chain)
            journal.on_chain_end({}, run_id=second)

            events = lifecycle.events(lifecycle_id)
            node_starts = [
                event
                for event in events
                if event["subject_kind"] == "workflow_node"
                and event["phase"] == "started"
            ]
            assert [event["node_invocation_id"] for event in node_starts] == [
                str(first),
                str(second),
            ]
            assert {event["subject_kind"] for event in events} >= {
                "run",
                "workflow_node",
                "agent",
                "model",
                "tool",
            }
            assert all(event["subject_name"] != "internal-sequence" for event in events)
            agent_events = [
                event for event in events if event["subject_kind"] == "agent"
            ]
            assert len(agent_events) == 4
            span_ids = {event["span_id"] for event in events if event["span_id"]}
            assert all(
                not event["parent_span_id"]
                or event["parent_span_id"] in span_ids
                for event in events
            )
            model_completed = next(
                event
                for event in events
                if event["subject_kind"] == "model"
                and event["phase"] == "completed"
            )
            assert model_completed["usage"] == {
                "input_tokens": 4,
                "output_tokens": 2,
                "total_tokens": 6,
            }
            assert [event["sequence"] for event in events] == sorted(
                event["sequence"] for event in events
            )
            first_invocation_events = lifecycle.events(
                lifecycle_id,
                node_invocation_id=str(first),
            )
            assert {event["event_type"] for event in first_invocation_events} == {
                "workflow_node",
                "agent",
            }
            assert lifecycle.events(lifecycle_id, event_type="model") == [
                event for event in events if event["event_type"] == "model"
            ]
            assert "private-journal-sentinel" not in json.dumps(events)
            model_requests = lifecycle.model_requests(lifecycle_id)
            assert len(model_requests) == 1
            assert model_requests[0]["agent_type"] == "main_agent"
            assert model_requests[0]["agent_id"] == "main-agent-profile"
            assert "private-journal-sentinel" in json.dumps(
                model_requests[0]["request"]
            )
            assert diagnostics.errors == []

            original = lifecycle.append_run_event

            def fail_event(_event):
                raise OSError("journal unavailable")

            monkeypatch.setattr(lifecycle, "append_run_event", fail_event)
            journal.on_tool_start({}, "ignored", run_id=uuid4())
            monkeypatch.setattr(lifecycle, "append_run_event", original)
            assert lifecycle.history.get_run("root-run")["observation_status"] == "partial"
            assert diagnostics.errors[0]["code"] == "workflow_run_event_record_failed"

            original_model_request = lifecycle.append_model_request

            def fail_model_request(_record):
                raise OSError("model request journal unavailable")

            monkeypatch.setattr(
                lifecycle,
                "append_model_request",
                fail_model_request,
            )
            journal.on_chat_model_start(
                {"name": "provider-model"},
                [[HumanMessage(content="ignored")]],
                run_id=uuid4(),
                metadata={"lc_agent_name": "Writer Agent"},
            )
            monkeypatch.setattr(
                lifecycle,
                "append_model_request",
                original_model_request,
            )
            assert diagnostics.errors[-1]["code"] == (
                "workflow_model_request_record_failed"
            )
        finally:
            await lifecycle.close()

    asyncio.run(scenario())


def test_model_requests_keep_main_and_subagent_profile_ownership(tmp_path) -> None:
    async def scenario() -> list[dict[str, object]]:
        database = SQLiteDatabase(tmp_path / "ownership.sqlite3")
        lifecycle = WorkflowLifecycleService(database)
        await lifecycle.start()
        try:
            lifecycle_id = await lifecycle.create(
                [{"role": "user", "content": "input"}],
                request_id="ownership-request",
                run_id="ownership-run",
                thread_id="ownership-thread",
                workflow_id="ownership-workflow",
                workflow_name="Ownership Workflow",
            )
            assert lifecycle.start_run("ownership-run") is True
            context = WorkflowRuntimeContext.for_run(
                request_id="ownership-request",
                lifecycle_id=lifecycle_id,
                run_id="ownership-run",
                thread_id="ownership-thread",
                workflow={"id": "ownership-workflow"},
            )
            journal = WorkflowRunJournal(
                lifecycle,
                None,
                context,
                workflow_node_kinds={"agent-node": "agent"},
                agent_names={"agent-node": "Writer Agent"},
                agent_profile_ids={"agent-node": "main-profile-id"},
                subagent_profile_ids={
                    "agent-node": {"Researcher": "subagent-profile-id"}
                },
            )

            node_run = uuid4()
            journal.on_chain_start(
                {},
                {},
                run_id=node_run,
                name="agent-node",
                metadata={"langgraph_node": "agent-node"},
            )
            main_root = uuid4()
            journal.on_chain_start(
                {},
                {},
                run_id=main_root,
                parent_run_id=node_run,
                name="Writer Agent",
                metadata={
                    "langgraph_node": "agent-node",
                    "lc_agent_name": "Writer Agent",
                },
            )
            journal.on_chat_model_start(
                {"name": "provider-model"},
                [[
                    SystemMessage(content="main-system-sentinel"),
                    HumanMessage(content="main-user-sentinel"),
                ]],
                run_id=uuid4(),
                parent_run_id=main_root,
                metadata={
                    "langgraph_node": "agent-node",
                    "lc_agent_name": "Writer Agent",
                },
                invocation_params={
                    "tools": [
                        {
                            "type": "function",
                            "function": {"name": "task"},
                        }
                    ],
                    "tool_choice": "auto",
                },
            )
            task_run = uuid4()
            journal.on_tool_start(
                {"name": "task"},
                "delegate",
                run_id=task_run,
                parent_run_id=main_root,
            )
            subagent_root = uuid4()
            journal.on_chain_start(
                {},
                {},
                run_id=subagent_root,
                parent_run_id=task_run,
                name="Researcher",
                metadata={
                    "langgraph_node": "agent-node",
                    "lc_agent_name": "Researcher",
                },
            )
            journal.on_chat_model_start(
                {"name": "provider-model"},
                [[SystemMessage(content="subagent-system-sentinel")]],
                run_id=uuid4(),
                parent_run_id=subagent_root,
                metadata={
                    "langgraph_node": "agent-node",
                    "lc_agent_name": "Researcher",
                },
                invocation_params={"tools": [{"name": "search"}]},
            )
            return lifecycle.model_requests(lifecycle_id)
        finally:
            await lifecycle.close()

    main_request, subagent_request = asyncio.run(scenario())
    assert main_request["agent_type"] == "main_agent"
    assert main_request["agent_id"] == "main-profile-id"
    assert main_request["workflow_node_id"] == "agent-node"
    assert main_request["parent_agent_id"] == ""
    assert main_request["request"]["capture_layer"] == (
        "langchain.on_chat_model_start"
    )
    assert main_request["request"]["invocation_params"]["tools"]
    assert "main-system-sentinel" in json.dumps(main_request["request"])

    assert subagent_request["agent_type"] == "subagent"
    assert subagent_request["agent_id"] == "subagent-profile-id"
    assert subagent_request["agent_name"] == "Researcher"
    assert subagent_request["parent_agent_id"] == "main-profile-id"
    assert subagent_request["parent_agent_name"] == "Writer Agent"
    assert subagent_request["workflow_node_id"] == "agent-node"
    assert "subagent-system-sentinel" in json.dumps(subagent_request["request"])


def test_journal_closes_all_open_spans_when_run_is_cancelled(tmp_path) -> None:
    async def scenario() -> list[dict[str, object]]:
        database = SQLiteDatabase(tmp_path / "cancelled.sqlite3")
        lifecycle = WorkflowLifecycleService(database)
        await lifecycle.start()
        try:
            lifecycle_id = await lifecycle.create(
                [{"role": "user", "content": "cancel"}],
                request_id="cancel-request",
                run_id="cancel-run",
                thread_id="cancel-thread",
                workflow_id="cancel-workflow",
                workflow_name="Cancelled Workflow",
            )
            assert lifecycle.start_run("cancel-run") is True
            context = WorkflowRuntimeContext.for_run(
                request_id="cancel-request",
                lifecycle_id=lifecycle_id,
                run_id="cancel-run",
                thread_id="cancel-thread",
                workflow={
                    "id": "cancel-workflow",
                    "name": "Cancelled Workflow",
                },
            )
            journal = WorkflowRunJournal(
                lifecycle,
                None,
                context,
                workflow_node_kinds={"agent-node": "agent"},
                agent_names={"agent-node": "Writer Agent"},
            )
            journal.on_chain_start(
                {},
                {},
                run_id="node-run",
                name="agent-node",
                metadata={"langgraph_node": "agent-node"},
            )
            journal.on_tool_start(
                {"name": "waiting-tool"},
                "",
                run_id="tool-run",
                parent_run_id="node-run",
            )

            journal.finish_open_spans(
                "cancelled", error_code="request_cancelled"
            )
            event_count = len(lifecycle.events(lifecycle_id))
            journal.finish_open_spans(
                "cancelled", error_code="request_cancelled"
            )
            events = lifecycle.events(lifecycle_id)
            assert len(events) == event_count
            return events
        finally:
            await lifecycle.close()

    events = asyncio.run(scenario())
    structural = [
        event
        for event in events
        if event["subject_kind"] in {"workflow_node", "agent", "tool"}
    ]
    started = {event["span_id"] for event in structural if event["phase"] == "started"}
    cancelled = {
        event["span_id"] for event in structural if event["phase"] == "cancelled"
    }
    assert started == cancelled
    assert all(
        event["error_code"] == "request_cancelled"
        for event in structural
        if event["phase"] == "cancelled"
    )
