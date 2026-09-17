from __future__ import annotations

import asyncio

import pytest

from langgraph.graph import END, START
from langgraph.types import Command

from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.run_identity import WorkflowRunIdentity
from agent_shell.runtime.state import (
    WORKFLOW_STATE_CHANNEL,
    wrap_workflow_state_update,
)
from agent_shell.workflow import admit_workflow_document
from agent_shell.workflow.catalog import node_catalog_payload
from agent_shell.workflow.compiler import compile_workflow
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1
from agent_shell.workflow.validation import validate_workflow_executable


COMMAND_ID = "11111111-1111-4111-8111-111111111111"


def _document(*, edges: list[dict] | None = None) -> WorkflowGraphDocumentV1:
    return WorkflowGraphDocumentV1.model_validate(
        {
            "definition": {
                "schema_version": 1,
                "state_contract": "agent-shell.workflow.control.v1",
                "nodes": [
                    {"id": "start", "type": "start", "type_version": 1, "config": {}},
                    {
                        "id": "router",
                        "type": "command",
                        "type_version": 1,
                        "config": {"command_id": COMMAND_ID},
                    },
                    {"id": "review", "type": "command", "type_version": 1, "config": {"command_id": COMMAND_ID}},
                    {"id": "end", "type": "end", "type_version": 1, "config": {}},
                ],
                "edges": edges
                if edges is not None
                else [
                    {"id": "start-router", "source": "start", "source_handle": "next", "target": "router", "target_handle": "in"},
                    {"id": "router-review", "source": "router", "source_handle": "next", "target": "review", "target_handle": "in"},
                    {"id": "router-end", "source": "router", "source_handle": "next", "target": "end", "target_handle": "in"},
                    {"id": "review-end", "source": "review", "source_handle": "next", "target": "end", "target_handle": "in"},
                ],
            },
            "layout": {"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
        }
    )


def _context() -> WorkflowRuntimeContext:
    return WorkflowRuntimeContext.for_run(
        identity=WorkflowRunIdentity(
            request_id="request-1",
            lifecycle_id="lifecycle-1",
            run_id="run-1",
            workflow_id="workflow-1",
            workflow_name="Workflow",
            thread_id="thread-1",
        )
    )


def test_catalog_exposes_only_control_graph_nodes_and_normal_handles() -> None:
    catalog = node_catalog_payload()
    assert [item["type"] for item in catalog] == ["start", "command", "end"]
    assert {item["runtime_kind"] for item in catalog} == {
        "graph_entry",
        "command_node",
        "graph_exit",
    }
    assert {
        handle["edge_type"]
        for item in catalog
        for handle in [*item["input_handles"], *item["output_handles"]]
    } == {"normal"}


def test_admission_rejects_removed_agent_nodes_and_routing_fields() -> None:
    payload = _document().model_dump(mode="json")
    payload["definition"]["nodes"][1] = {
        "id": "agent",
        "type": "agent",
        "type_version": 1,
        "config": {"main_agent_id": COMMAND_ID},
    }
    report, normalized = admit_workflow_document(payload)
    assert normalized is None
    assert {issue.code for issue in report.issues} == {
        "workflow.node_type_unsupported"
    }

    payload = _document().model_dump(mode="json")
    payload["definition"]["edges"][0]["branch_key"] = "legacy"
    report, normalized = admit_workflow_document(payload)
    assert normalized is None
    assert report.valid is False


def test_validation_requires_command_references_and_reachability() -> None:
    document = _document()
    missing = validate_workflow_executable(document, commands={})
    assert any(issue.code == "configuration.reference_not_found" for issue in missing.issues)
    valid = validate_workflow_executable(
        document,
        commands={"router": object(), "review": object()},
    )
    assert valid.valid


def test_compiler_uses_start_edge_and_command_destinations_without_static_command_edges() -> None:
    calls: list[str] = []

    async def router(state, runtime):
        calls.append(runtime.context.workflow_node_id)
        return Command(
            update={"selected": "review"},
            goto="review",
        )

    async def review(state, runtime):
        calls.append(runtime.context.workflow_node_id)
        return Command(goto=END)

    graph = compile_workflow(
        _document(),
        commands={"router": router, "review": review},
    )
    result = asyncio.run(
        graph.ainvoke(wrap_workflow_state_update({}), context=_context())
    )

    assert calls == ["router", "review"]
    assert result[WORKFLOW_STATE_CHANNEL] == {"selected": "review"}
    assert graph.builder.edges == {(START, "router")}


def test_command_loop_is_checkpointable_super_step_control() -> None:
    document = _document(
        edges=[
            {"id": "start-router", "source": "start", "source_handle": "next", "target": "router", "target_handle": "in"},
            {"id": "router-loop", "source": "router", "source_handle": "next", "target": "router", "target_handle": "in"},
            {"id": "router-end", "source": "router", "source_handle": "next", "target": "end", "target_handle": "in"},
        ]
    )
    document.definition.nodes = [
        node for node in document.definition.nodes if node.id != "review"
    ]

    async def router(state, runtime):
        count = state.get("count", 0) + 1
        return Command(
            update={"count": count},
            goto="router" if count < 3 else END,
        )

    graph = compile_workflow(document, commands={"router": router})
    result = asyncio.run(
        graph.ainvoke(wrap_workflow_state_update({}), context=_context())
    )
    assert result[WORKFLOW_STATE_CHANNEL] == {"count": 3}


def test_start_can_finish_without_an_executable_node() -> None:
    document = WorkflowGraphDocumentV1.model_validate(
        {
            "definition": {
                "schema_version": 1,
                "state_contract": "agent-shell.workflow.control.v1",
                "nodes": [
                    {"id": "start", "type": "start", "type_version": 1, "config": {}},
                    {"id": "end", "type": "end", "type_version": 1, "config": {}},
                ],
                "edges": [
                    {"id": "finish", "source": "start", "source_handle": "next", "target": "end", "target_handle": "in"}
                ],
            },
            "layout": {"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
        }
    )
    assert validate_workflow_executable(document).valid
    result = asyncio.run(
        compile_workflow(document).ainvoke(
            wrap_workflow_state_update({"ok": True})
        )
    )
    assert result == {WORKFLOW_STATE_CHANNEL: {"ok": True}}


def test_admission_rejects_an_invalid_state_schema() -> None:
    payload = _document().model_dump(mode="json")
    payload["definition"]["state_schema"] = {
        "type": "object",
        "properties": {"topic": {"type": 7}},
    }
    report, normalized = admit_workflow_document(payload)
    assert normalized is None
    assert {issue.code for issue in report.issues} == {
        "workflow.state_schema_invalid"
    }

    payload["definition"]["state_schema"] = {"properties": {}}
    report, normalized = admit_workflow_document(payload)
    assert normalized is None
    assert {issue.code for issue in report.issues} == {
        "workflow.state_schema_invalid"
    }


def test_declared_state_schema_keeps_declared_keys_across_super_steps() -> None:
    document = _document()
    document.definition.state_schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "selected": {"type": "string"},
        },
        "required": ["count"],
        "additionalProperties": False,
    }
    seen: list[dict] = []

    async def router(state, runtime):
        seen.append(dict(state))
        return Command(update={"selected": "review"}, goto="review")

    async def review(state, runtime):
        seen.append(dict(state))
        return Command(goto=END)

    graph = compile_workflow(
        document,
        commands={"router": router, "review": review},
    )
    result = asyncio.run(
        graph.ainvoke(
            wrap_workflow_state_update({"count": 1}),
            context=_context(),
        )
    )

    assert seen == [{"count": 1}, {"count": 1, "selected": "review"}]
    assert result[WORKFLOW_STATE_CHANNEL] == {
        "count": 1,
        "selected": "review",
    }


def test_declared_state_schema_fails_the_run_on_an_invalid_command_update() -> None:
    document = _document()
    document.definition.state_schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "additionalProperties": False,
    }

    async def router(state, runtime):
        return Command(update={"count": "many"}, goto="review")

    async def review(state, runtime):
        raise AssertionError("the invalid update must stop the run")

    graph = compile_workflow(
        document,
        commands={"router": router, "review": review},
    )
    with pytest.raises(AgentRuntimeError) as raised:
        asyncio.run(
            graph.ainvoke(
                wrap_workflow_state_update({"count": 1}),
                context=_context(),
            )
        )

    assert raised.value.code == "workflow.state_invalid"
    assert raised.value.status_code == 422
