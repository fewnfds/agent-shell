from __future__ import annotations

from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.output_projection import (
    EventOutputOriginResolver,
    OutputProjector,
)
from agent_shell.workflow.events import WorkflowEventSourceV1


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
    source = WorkflowEventSourceV1(
        source_type="agent",
        workflow_node_id="agent-a",
        agent_profile_id="66666666-6666-4666-8666-666666666666",
    )
    resolver = EventOutputOriginResolver(
        context,
        workflow_sources={"agent-a": source},
        main_agent_names=("Main",),
    )
    origin = resolver.resolve(event)
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
    source = WorkflowEventSourceV1(
        source_type="agent",
        workflow_node_id="agent-a",
        agent_profile_id="66666666-6666-4666-8666-666666666666",
    )
    resolver = EventOutputOriginResolver(context, workflow_sources={"agent-a": source})
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
    origin = resolver.resolve(event)
    assert origin["workflow_node_id"] == "agent-a"
    assert origin["node_invocation_id"] == "invoke-9"
