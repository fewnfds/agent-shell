from __future__ import annotations

from agent_shell.runtime.event_origin import RunEventOriginResolver
from agent_shell.runtime.output_projection import OutputProjector
from agent_shell.runtime.run_identity import AgentRunIdentity, WorkflowRunIdentity


def test_projector_receives_raw_event_and_root_workflow_origin() -> None:
    event = {
        "type": "event",
        "seq": 4,
        "method": "custom",
        "params": {
            "namespace": ["command-a:invoke-1"],
            "timestamp": 123,
            "data": {"answer": 42},
        },
    }
    identity = WorkflowRunIdentity(
        request_id="request-1",
        lifecycle_id="lifecycle-1",
        run_id="run-1",
        thread_id="thread-1",
        assistant_id="assistant-1",
        caller_run_id="caller-1",
        operation_id="review-report",
        workflow_id="workflow-1",
        workflow_name="Review Workflow",
    )
    origin = RunEventOriginResolver(identity).resolve(event).output
    seen: list[tuple[object, object]] = []

    def output(received_event, received_origin):
        seen.append((received_event, received_origin))
        return "ok"

    assert OutputProjector(output).render(event, origin) == "ok"
    assert seen == [(event, origin)]
    assert origin == {
        "lifecycle_id": "lifecycle-1",
        "graph_kind": "workflow",
        "run_id": "run-1",
        "thread_id": "thread-1",
        "assistant_id": "assistant-1",
        "caller_run_id": "caller-1",
        "operation_id": "review-report",
        "workflow_id": "workflow-1",
        "main_agent_id": "",
        "agent_profile_id": "",
        "subagent_profile_id": "",
    }


def test_projector_passes_stream_start_to_optional_segment_end() -> None:
    event = {
        "seq": 2,
        "method": "messages",
        "params": {
            "namespace": ["model:invoke-1"],
            "data": {
                "event": "content-block-start",
                "index": 0,
                "content": {"type": "text", "text": ""},
            },
        },
    }
    origin = {"graph_kind": "agent", "main_agent_id": "agent-1"}
    seen: list[tuple[object, object]] = []

    def segment_end(received_event, received_origin):
        seen.append((received_event, received_origin))
        return "</answer>"

    projector = OutputProjector(lambda _event, _origin: "", segment_end=segment_end)

    assert projector.render_segment_end(event, origin) == "</answer>"
    assert seen == [(event, origin)]


def test_workflow_namespace_does_not_change_root_output_identity() -> None:
    identity = WorkflowRunIdentity(
        request_id="request-1",
        lifecycle_id="lifecycle-1",
        run_id="run-1",
        workflow_id="workflow-1",
        workflow_name="Workflow",
    )
    resolver = RunEventOriginResolver(identity)
    event = {
        "method": "values",
        "params": {
            "namespace": ["command-a:invoke-3"],
            "data": {"shared_vars": {"answer": 42}},
        },
    }

    resolved = resolver.resolve(event)

    assert resolved.source_type == "workflow"
    assert resolved.output == resolver.run_origin()


def test_agent_origin_exposes_configured_subagent_without_changing_graph_owner() -> None:
    identity = AgentRunIdentity(
        request_id="request-1",
        lifecycle_id="lifecycle-1",
        run_id="run-1",
        main_agent_id="agent-1",
        main_agent_name="Writer",
    )
    resolver = RunEventOriginResolver(
        identity,
        main_agent_names=("Writer",),
        root_agent_profile_id="agent-1",
        root_subagent_profile_ids={"Researcher": "subagent-1"},
    )
    event = {
        "method": "messages",
        "params": {
            "namespace": ["task:research", "model:call"],
            "data": (
                {"event": "message-start", "role": "ai", "id": "message-1"},
                {"run_id": "model-run", "lc_agent_name": "Researcher"},
            ),
        },
    }

    resolved = resolver.resolve(event)

    assert resolved.source_type == "subagent"
    assert resolved.output["graph_kind"] == "agent"
    assert resolved.output["main_agent_id"] == "agent-1"
    assert resolved.output["subagent_profile_id"] == "subagent-1"
