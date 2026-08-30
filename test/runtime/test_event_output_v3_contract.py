from __future__ import annotations

from langchain_core.messages import AIMessage

from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.event_origin import (
    RunEventOriginResolver,
    WorkflowNodeSource,
)
from agent_shell.runtime.output_projection import OutputProjector, WorkflowOutputProjector


def test_output_projector_passes_raw_protocol_event_and_origin_unchanged() -> None:
    event = {
        "type": "event",
        "seq": 4,
        "method": "custom",
        "params": {
            "namespace": ["agent-a:invoke-1"],
            "timestamp": 123,
            "data": {"answer": 42},
        },
    }
    context = WorkflowRuntimeContext.for_run(
        request_id="request-1",
        lifecycle_id="11111111-1111-4111-8111-111111111111",
        run_id="22222222-2222-4222-8222-222222222222",
        parent_run_id="33333333-3333-4333-8333-333333333333",
        background_task_id="44444444-4444-4444-8444-444444444444",
        run_depth=1,
        workflow={"id": "55555555-5555-4555-8555-555555555555", "workflow_role": "child"},
    )
    source = WorkflowNodeSource(
        source_type="agent",
        workflow_node_id="agent-a",
        agent_profile_id="66666666-6666-4666-8666-666666666666",
    )
    resolver = RunEventOriginResolver(
        context,
        workflow_sources={"agent-a": source},
        main_agent_names=("Main",),
    )
    resolved = resolver.resolve(event)
    origin = resolved.output
    seen: list[tuple[object, object]] = []

    def output(received_event, received_origin):
        seen.append((received_event, received_origin))
        return "ok"

    assert OutputProjector(output).render(event, origin) == "ok"
    assert seen == [(event, origin)]
    assert origin == {
        "lifecycle_id": "11111111-1111-4111-8111-111111111111",
        "workflow_run_id": "22222222-2222-4222-8222-222222222222",
        "parent_workflow_run_id": "33333333-3333-4333-8333-333333333333",
        "workflow_id": "55555555-5555-4555-8555-555555555555",
        "workflow_role": "child",
        "background_task_id": "44444444-4444-4444-8444-444444444444",
        "run_depth": 1,
        "workflow_node_id": "agent-a",
        "node_invocation_id": "invoke-1",
        "agent_profile_id": "66666666-6666-4666-8666-666666666666",
        "subagent_profile_id": "",
    }


def test_origin_resolver_reads_lifecycle_namespace_from_protocol_payload() -> None:
    context = WorkflowRuntimeContext.for_run(
        request_id="request-1",
        lifecycle_id="11111111-1111-4111-8111-111111111111",
        run_id="22222222-2222-4222-8222-222222222222",
        workflow={"id": "55555555-5555-4555-8555-555555555555", "workflow_role": "parent"},
    )
    source = WorkflowNodeSource(
        source_type="agent",
        workflow_node_id="agent-a",
        agent_profile_id="66666666-6666-4666-8666-666666666666",
    )
    resolver = RunEventOriginResolver(context, workflow_sources={"agent-a": source})
    event = {
        "seq": 1,
        "method": "lifecycle",
        "params": {
            "namespace": [],
            "timestamp": 1,
            "data": {
                "event": "started",
                "graph_name": "Main",
                "namespace": ["agent-a:invoke-9"],
            },
        },
    }
    origin = resolver.resolve(event).output
    assert origin["workflow_node_id"] == "agent-a"
    assert origin["node_invocation_id"] == "invoke-9"


def test_workflow_projector_selects_agent_or_workflow_package_from_origin() -> None:
    agent_a = lambda event, origin: "A:" + str(event["params"]["data"])
    agent_b = lambda event, origin: "B:" + str(event["params"]["data"])
    workflow = lambda event, origin: "W:" + str(event["params"]["data"])
    projector = WorkflowOutputProjector(
        {"agent-a": agent_a, "agent-b": agent_b},
        workflow_output=workflow,
    )
    event = {
        "method": "custom",
        "params": {"namespace": [], "data": "visible"},
    }

    assert projector.render(event, {
        "workflow_node_id": "agent-a",
        "agent_profile_id": "profile-a",
    }) == "A:visible"
    assert projector.render(event, {
        "workflow_node_id": "agent-b",
        "agent_profile_id": "profile-b",
    }) == "B:visible"
    assert projector.render(event, {
        "workflow_node_id": "unknown",
        "agent_profile_id": "profile-unknown",
    }) == ""
    assert projector.render(event, {
        "workflow_node_id": "script-node",
        "agent_profile_id": "",
    }) == "W:visible"


def test_origin_resolver_keeps_workflow_agents_and_subagents_distinct() -> None:
    resolver = RunEventOriginResolver(
        None,
        workflow_sources={
            "agent-a": WorkflowNodeSource("agent", "agent-a", "profile-a"),
            "agent-b": WorkflowNodeSource("agent", "agent-b", "profile-b"),
        },
        main_agent_names=("Writer", "Reviewer"),
        workflow_agent_names={"agent-a": "Writer", "agent-b": "Reviewer"},
        workflow_subagent_profile_ids={
            "agent-a": {"Researcher": "subagent-a"},
            "agent-b": {"Researcher": "subagent-b"},
        },
    )
    message = {
        "seq": 17,
        "method": "messages",
        "params": {
            "namespace": ["agent-b:invoke-2", "model:model-run"],
            "data": [
                AIMessage(content="review complete"),
                {"langgraph_node": "model", "run_id": "review-run"},
            ],
        },
    }
    lifecycle = {
        "seq": 18,
        "method": "lifecycle",
        "params": {
            "namespace": [],
            "data": {
                "event": "started",
                "namespace": ["agent-b:invoke-2", "task:call-1"],
                "graph_name": "Researcher",
            },
        },
    }

    main_origin = resolver.resolve(message)
    subagent_origin = resolver.resolve(lifecycle)

    assert main_origin.source_type == "agent"
    assert main_origin.workflow_node_id == "agent-b"
    assert main_origin.node_invocation_id == "invoke-2"
    assert main_origin.agent_profile_id == "profile-b"
    assert subagent_origin.source_type == "subagent"
    assert subagent_origin.workflow_node_id == "agent-b"
    assert subagent_origin.agent_profile_id == "profile-b"
    assert subagent_origin.subagent_profile_id == "subagent-b"


def test_script_origin_and_full_raw_state_stay_separate() -> None:
    resolver = RunEventOriginResolver(
        None,
        workflow_sources={
            "inspect-file": WorkflowNodeSource("script", "inspect-file"),
        },
    )
    event = {
        "seq": 2,
        "method": "values",
        "params": {
            "namespace": ["inspect-file:invoke-3"],
            "data": {"shared_vars": {"answer": 42}},
        },
    }
    origin = resolver.resolve(event)
    seen: list[object] = []
    projector = WorkflowOutputProjector(
        {},
        workflow_output=lambda raw, shell_origin: (
            seen.extend((raw, shell_origin))
            or str(raw["params"]["data"]["shared_vars"]["answer"])
        ),
    )

    assert projector.render(event, origin.output) == "42"
    assert seen == [event, origin.output]
    assert origin.source_type == "script"
    assert origin.workflow_node_id == "inspect-file"
    assert origin.node_invocation_id == "invoke-3"
