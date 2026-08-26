from __future__ import annotations

from copy import deepcopy
import asyncio

import pytest
from deepagents.backends import StateBackend
from deepagents.backends.utils import create_file_data
from langchain_core.messages import AIMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.memory import InMemoryStore

from agent_shell.runtime.agent_builder import BuiltAgent
from agent_shell.runtime.agent_runtime import AgentRuntime
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.state import AgentShellState, WorkflowState
from agent_shell.runtime.workflow_lifecycle import lifecycle_invocations_namespace
from agent_shell.validation.assembly import StaticAssembly
from agent_shell.validation import ValidationIssue, ValidationReport
from agent_shell.workflow import (
    NODE_CATALOG,
    admit_workflow_document,
    compile_workflow,
    validate_workflow_executable,
    workflow_document_sha256,
    workflow_executable_sha256,
)
from agent_shell.workflow.compiler import _make_agent_node


AGENT_A = "11111111-1111-4111-8111-111111111111"
AGENT_B = "22222222-2222-4222-8222-222222222222"
AGENT_C = "33333333-3333-4333-8333-333333333333"


class _MiddlewareRuntime:
    async def close(self) -> None:
        return None


def _built_agent(
    graph,
    *,
    agent_id: str,
    agent_name: str,
    input_state: dict[str, object] | None = None,
) -> BuiltAgent:
    return BuiltAgent(
        graph=graph,
        input_state=input_state or {"messages": [], "shared_vars": {}},
        event_output_id="",
        event_output_reference={},
        agent_id=agent_id,
        agent_name=agent_name,
        subagent_profile_ids={},
        middleware_runtime=_MiddlewareRuntime(),  # type: ignore[arg-type]
    )


def graph_payload(*agent_ids: str) -> dict[str, object]:
    nodes = [{"id": "start", "type": "start", "type_version": 1, "config": {}}]
    nodes.extend(
        {
            "id": f"agent-{index}",
            "type": "agent",
            "type_version": 1,
            "config": {"main_agent_id": agent_id},
        }
        for index, agent_id in enumerate(agent_ids, start=1)
    )
    nodes.append({"id": "end", "type": "end", "type_version": 1, "config": {}})

    edges = []
    sequence = [str(node["id"]) for node in nodes]
    for source, target in zip(sequence, sequence[1:]):
        edges.append(
            {
                "id": f"{source}-{target}",
                "source": source,
                "source_handle": "next",
                "target": target,
                "target_handle": "in",
            }
        )

    return {
        "definition": {
            "schema_version": 1,
            "state_contract": "agent-shell.workflow.agent-invocations.v1",
            "nodes": nodes,
            "edges": edges,
        },
        "layout": {
            "nodes": {
                node_id: {"x": index * 240, "y": 160}
                for index, node_id in enumerate(sequence)
            },
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    }


def valid_main_agent(_main_agent_id: str) -> ValidationReport:
    return ValidationReport(stage="workflow_publish")


def test_catalog_exposes_the_first_supported_node_and_handle_paradigms() -> None:
    assert [item.type for item in NODE_CATALOG] == [
        "start",
        "agent",
        "command",
        "task-dispatcher",
        "end",
    ]
    assert [item.runtime_kind for item in NODE_CATALOG] == [
        "graph_entry",
        "agent_wrapper",
        "command_node",
        "send_dispatcher",
        "graph_exit",
    ]
    assert [handle.id for handle in NODE_CATALOG[0].output_handles] == ["next"]
    assert [handle.id for handle in NODE_CATALOG[1].input_handles] == ["in"]
    assert [handle.id for handle in NODE_CATALOG[1].output_handles] == ["next"]
    assert [handle.id for handle in NODE_CATALOG[2].input_handles] == ["in"]
    assert [handle.id for handle in NODE_CATALOG[2].output_handles] == ["branch"]
    assert [handle.id for handle in NODE_CATALOG[3].input_handles] == ["in"]
    assert [handle.id for handle in NODE_CATALOG[3].output_handles] == ["dispatch"]
    assert [handle.id for handle in NODE_CATALOG[4].input_handles] == ["in"]
    assert {
        handle.edge_type for item in NODE_CATALOG for handle in (
            *item.input_handles,
            *item.output_handles,
        )
    } == {"normal", "branch", "dispatch"}
    assert all(
        handle.max_connections is None
        for item in NODE_CATALOG
        for handle in (*item.input_handles, *item.output_handles)
    )
    assert NODE_CATALOG[1].config_model.model_json_schema()["required"] == [
        "main_agent_id"
    ]
    assert NODE_CATALOG[1].config_model.model_json_schema()["properties"]["defer"] == {
        "default": False,
        "title": "Defer",
        "type": "boolean",
    }


@pytest.mark.parametrize(
    "node_type, config",
    [
        ("background-workflow-start", {"child_workflow_id": AGENT_B}),
        ("background-agent-start", {"main_agent_id": AGENT_B}),
        ("background-check", {}),
        ("background-list", {}),
        ("background-cancel", {}),
    ],
)
def test_background_actions_are_runtime_commands_not_canvas_nodes(
    node_type: str,
    config: dict[str, object],
) -> None:
    payload = graph_payload(AGENT_A)
    payload["definition"]["nodes"].insert(  # type: ignore[index]
        1,
        {
            "id": "background-start",
            "type": node_type,
            "type_version": 1,
            "config": config,
        },
    )

    report, document = admit_workflow_document(payload, workflow_role="parent")

    assert document is None
    assert {issue.code for issue in report.issues} == {
        "workflow.node_type_unsupported"
    }


def test_admission_accepts_incomplete_drafts_and_layout_does_not_change_execution_sha() -> None:
    incomplete = graph_payload(AGENT_A)
    incomplete["definition"]["edges"] = []  # type: ignore[index]

    admission, admitted = admit_workflow_document(incomplete)

    assert admission.valid is True
    assert admitted is not None
    executable = validate_workflow_executable(
        admitted,
        validate_main_agent=valid_main_agent,
    )
    assert executable.valid is False
    assert {
        issue.code for issue in executable.issues
    } == {
        "workflow.start_outgoing_required",
        "workflow.node_unreachable_from_start",
    }

    leaf = graph_payload(AGENT_A)
    leaf["definition"]["edges"] = [  # type: ignore[index]
        {
            "id": "start-agent-1",
            "source": "start",
            "source_handle": "next",
            "target": "agent-1",
            "target_handle": "in",
        },
    ]
    leaf_report, leaf_document = admit_workflow_document(leaf)
    assert leaf_report.valid is True
    assert leaf_document is not None
    assert validate_workflow_executable(
        leaf_document,
        validate_main_agent=valid_main_agent,
    ).valid is True

    complete_report, complete = admit_workflow_document(graph_payload(AGENT_A))
    assert complete_report.valid is True
    assert complete is not None
    moved = complete.model_copy(
        update={
            "layout": complete.layout.model_copy(
                update={
                    "viewport": complete.layout.viewport.model_copy(
                        update={"x": 320.0, "zoom": 1.5}
                    )
                }
            )
        }
    )
    assert workflow_document_sha256(complete) != workflow_document_sha256(moved)
    assert workflow_executable_sha256(
        complete.definition
    ) == workflow_executable_sha256(moved.definition)

    reordered = complete.model_copy(
        update={
            "definition": complete.definition.model_copy(
                update={
                    "nodes": list(reversed(complete.definition.nodes)),
                    "edges": list(reversed(complete.definition.edges)),
                }
            )
        }
    )
    assert workflow_document_sha256(complete) == workflow_document_sha256(reordered)
    assert workflow_executable_sha256(
        complete.definition
    ) == workflow_executable_sha256(reordered.definition)


@pytest.mark.parametrize(
    ("mutate", "expected_code", "expected_path"),
    [
        (
            lambda payload: payload["definition"]["nodes"][1].update(type="unknown"),
            "workflow.node_type_unsupported",
            "definition.nodes[1].type",
        ),
        (
            lambda payload: payload["definition"]["nodes"][1].update(
                type_version=2
            ),
            "workflow.node_version_unsupported",
            "definition.nodes[1].type_version",
        ),
        (
            lambda payload: payload["definition"]["nodes"][1]["config"].update(
                unexpected=True
            ),
            "contract.unknown_field",
            "definition.nodes[1].config.unexpected",
        ),
        (
            lambda payload: payload["definition"]["nodes"][1].update(id="start"),
            "workflow.node_id_duplicate",
            "definition.nodes[1].id",
        ),
        (
            lambda payload: payload["layout"]["nodes"].update(
                orphan={"x": 1, "y": 1}
            ),
            "workflow.layout_node_not_found",
            "layout.nodes.orphan",
        ),
    ],
)
def test_admission_rejects_unsupported_or_ambiguous_graph_documents(
    mutate,
    expected_code: str,
    expected_path: str,
) -> None:
    payload = deepcopy(graph_payload(AGENT_A))
    mutate(payload)

    report, document = admit_workflow_document(payload)

    assert document is None
    assert any(
        issue.code == expected_code and issue.path == expected_path
        for issue in report.issues
    )


@pytest.mark.parametrize(
    ("agent_ids", "expected_validated"),
    [
        ((AGENT_A,), [AGENT_A]),
        ((AGENT_A, AGENT_B), [AGENT_A, AGENT_B]),
        ((AGENT_A, AGENT_A), [AGENT_A]),
    ],
)
def test_executable_validation_accepts_one_or_more_agent_linear_graphs(
    agent_ids: tuple[str, ...],
    expected_validated: list[str],
) -> None:
    admission, document = admit_workflow_document(graph_payload(*agent_ids))
    seen: list[str] = []

    def validate(main_agent_id: str) -> ValidationReport:
        seen.append(main_agent_id)
        return ValidationReport(stage="workflow_publish")

    assert admission.valid is True
    assert document is not None
    report = validate_workflow_executable(document, validate_main_agent=validate)

    assert report.valid is True
    assert seen == expected_validated


def test_executable_validation_accepts_multiple_normal_inputs_and_outputs() -> None:
    payload = graph_payload(AGENT_A, AGENT_B)
    payload["definition"]["edges"] = [  # type: ignore[index]
        {
            "id": "start-agent-1",
            "source": "start",
            "source_handle": "next",
            "target": "agent-1",
            "target_handle": "in",
        },
        {
            "id": "agent-1-agent-2",
            "source": "agent-1",
            "source_handle": "next",
            "target": "agent-2",
            "target_handle": "in",
        },
        {
            "id": "agent-1-end",
            "source": "agent-1",
            "source_handle": "next",
            "target": "end",
            "target_handle": "in",
        },
        {
            "id": "agent-2-end",
            "source": "agent-2",
            "source_handle": "next",
            "target": "end",
            "target_handle": "in",
        },
    ]
    admission, document = admit_workflow_document(payload)

    assert admission.valid is True
    assert document is not None
    assert validate_workflow_executable(
        document,
        validate_main_agent=valid_main_agent,
    ).valid is True


def test_topology_does_not_forbid_langgraph_cycles() -> None:
    payload = graph_payload(AGENT_A, AGENT_B)
    payload["definition"]["edges"] = [  # type: ignore[index]
        *payload["definition"]["edges"],  # type: ignore[index]
        {
            "id": "agent-2-agent-1",
            "source": "agent-2",
            "source_handle": "next",
            "target": "agent-1",
            "target_handle": "in",
        },
    ]
    admission, document = admit_workflow_document(payload)

    assert admission.valid is True
    assert document is not None
    assert validate_workflow_executable(
        document,
        validate_main_agent=valid_main_agent,
    ).valid is True


@pytest.mark.parametrize(
    ("remove_type", "expected_code"),
    [
        ("start", "workflow.start_required"),
        ("end", "workflow.end_required"),
    ],
)
def test_executable_validation_requires_each_runtime_node_kind(
    remove_type: str,
    expected_code: str,
) -> None:
    payload = graph_payload(AGENT_A)
    removed_ids = {
        node["id"]
        for node in payload["definition"]["nodes"]  # type: ignore[index]
        if node["type"] == remove_type
    }
    payload["definition"]["nodes"] = [  # type: ignore[index]
        node
        for node in payload["definition"]["nodes"]  # type: ignore[index]
        if node["id"] not in removed_ids
    ]
    payload["definition"]["edges"] = [  # type: ignore[index]
        edge
        for edge in payload["definition"]["edges"]  # type: ignore[index]
        if edge["source"] not in removed_ids and edge["target"] not in removed_ids
    ]
    payload["layout"]["nodes"] = {  # type: ignore[index]
        node_id: position
        for node_id, position in payload["layout"]["nodes"].items()  # type: ignore[index]
        if node_id not in removed_ids
    }
    admission, document = admit_workflow_document(payload)
    assert admission.valid is True
    assert document is not None

    report = validate_workflow_executable(
        document,
        validate_main_agent=valid_main_agent,
    )

    assert report.valid is False
    assert expected_code in {issue.code for issue in report.issues}


@pytest.mark.parametrize(
    ("duplicate_type", "expected_code"),
    [
        ("start", "workflow.start_multiple"),
        ("end", "workflow.end_multiple"),
    ],
)
def test_executable_validation_requires_exactly_one_start_and_end(
    duplicate_type: str,
    expected_code: str,
) -> None:
    payload = graph_payload(AGENT_A)
    payload["definition"]["nodes"].append(  # type: ignore[index]
        {
            "id": f"second-{duplicate_type}",
            "type": duplicate_type,
            "type_version": 1,
            "config": {},
        }
    )
    admission, document = admit_workflow_document(payload)
    assert admission.valid is True
    assert document is not None

    report = validate_workflow_executable(
        document,
        validate_main_agent=valid_main_agent,
    )

    assert expected_code in {issue.code for issue in report.issues}


def test_start_can_connect_directly_to_end() -> None:
    payload = graph_payload()
    admission, document = admit_workflow_document(payload)
    assert admission.valid is True
    assert document is not None
    assert validate_workflow_executable(
        document,
        validate_main_agent=valid_main_agent,
    ).valid is True

    graph = compile_workflow(document, node_agents={})

    assert (START, END) in graph.builder.edges


def test_executable_validation_allows_agent_free_script_graph() -> None:
    payload = {
        "definition": {
            "schema_version": 1,
            "state_contract": "agent-shell.workflow.agent-invocations.v1",
            "nodes": [
                {"id": "start", "type": "start", "type_version": 1, "config": {}},
                {
                    "id": "router",
                    "type": "command",
                    "type_version": 1,
                    "config": {
                        "command_id": "11111111-1111-4111-8111-111111111111"
                    },
                },
                {"id": "end", "type": "end", "type_version": 1, "config": {}},
            ],
            "edges": [
                {
                    "id": "start-router",
                    "source": "start",
                    "source_handle": "next",
                    "target": "router",
                    "target_handle": "in",
                },
                {
                    "id": "router-end",
                    "source": "router",
                    "source_handle": "branch",
                    "target": "end",
                    "target_handle": "in",
                    "branch_key": "finish",
                },
            ],
        },
        "layout": {},
    }
    admission, document = admit_workflow_document(payload)
    assert admission.valid is True
    assert document is not None

    async def router(state, runtime):
        return {
            "activate": ["finish"],
            "update": {"shared_vars": {"script_ran": True}},
        }

    report = validate_workflow_executable(
        document,
        validate_main_agent=valid_main_agent,
        commands={"router": router},
    )

    assert report.valid is True

    graph = compile_workflow(
        document,
        node_agents={},
        commands={"router": router},
    )
    runtime = AgentRuntime(
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        workflow_lifecycle=object(),  # type: ignore[arg-type]
    )
    execution = runtime._execution(
        None,
        graph=graph,
        input_state={
            "shared_vars": {},
            "agent_invocations": {},
            "background_tasks": {},
        },
        context=WorkflowRuntimeContext(
            lifecycle_id="lifecycle-1",
            run_id="run-1",
            workflow={"id": "workflow-1"},
        ),
        include_tool_call_transformer=False,
        public_output=False,
    )

    lifecycle_event = execution.normalizer.lifecycle("start", status="running")
    assert lifecycle_event.source_type == "non_agent"
    assert lifecycle_event.workflow_event_kind == "lifecycle"

    asyncio.run(execution.execute())

    assert execution.middleware_runtime is None
    assert execution.final_state is not None
    assert execution.final_state["shared_vars"] == {"script_ran": True}


def test_executable_validation_attaches_main_agent_issues_to_the_agent_node() -> None:
    admission, document = admit_workflow_document(graph_payload(AGENT_A))
    assert admission.valid is True
    assert document is not None

    def missing_main_agent(main_agent_id: str) -> ValidationReport:
        return ValidationReport(
            stage="workflow_publish",
            issues=(
                ValidationIssue(
                    code="configuration.reference_not_found",
                    scope="main_agent",
                    owner_id=main_agent_id,
                    path="id",
                    message="The requested Main Agent does not exist.",
                    message_key="validation.issue.configuration.referenceNotFound",
                    message_args={
                        "expected_type": "main_agent",
                        "reference_id": main_agent_id,
                    },
                ),
            ),
        )

    report = validate_workflow_executable(
        document,
        validate_main_agent=missing_main_agent,
    )

    assert report.valid is False
    issue = next(
        item
        for item in report.issues
        if item.code == "configuration.reference_not_found"
    )
    assert issue.owner_id == "agent-1"
    assert issue.owner_type == "agent"
    assert issue.path == "definition.nodes[1].config.main_agent_id"


def test_compiler_maps_canvas_start_and_end_to_langgraph_sentinels() -> None:
    admission, document = admit_workflow_document(graph_payload(AGENT_A))
    assert admission.valid is True
    assert document is not None

    def answer(_state: AgentShellState) -> dict[str, list[AIMessage]]:
        return {"messages": [AIMessage(content="compiled workflow response")]}

    agent_graph = (
        StateGraph(AgentShellState)
        .add_node("answer", answer)
        .add_edge(START, "answer")
        .add_edge("answer", END)
        .compile()
    )
    store = InMemoryStore()
    graph = compile_workflow(
        document,
        node_agents={
            "agent-1": _built_agent(
                agent_graph,
                agent_id=AGENT_A,
                agent_name="Agent A",
            )
        },
        store=store,
    )

    result = asyncio.run(
        graph.ainvoke(
            {"shared_vars": {}, "agent_invocations": {}},
            context=WorkflowRuntimeContext(
                request_id="request-1",
                lifecycle_id="lifecycle-1",
                run_id="run-1",
                workflow={"id": "workflow-id"},
            ),
        )
    )

    assert "messages" not in result
    record = next(iter(result["agent_invocations"].values()))
    assert set(record) == {
        "invocation_id",
        "workflow_id",
        "workflow_node_id",
        "agent_id",
        "invoked_at",
        "result_ref",
    }
    assert record["invocation_id"] in result["agent_invocations"]
    assert record["workflow_id"] == "workflow-id"
    assert record["workflow_node_id"] == "agent-1"
    assert record["agent_id"] == AGENT_A
    assert isinstance(record["invoked_at"], float)
    artifact = store.get(
        lifecycle_invocations_namespace("lifecycle-1", "run-1"),
        record["result_ref"],
    )
    assert artifact is not None
    assert artifact.value["messages"][-1]["content"] == "compiled workflow response"


def test_serial_agents_have_private_messages_and_explicit_parent_snapshot() -> None:
    admission, document = admit_workflow_document(graph_payload(AGENT_A, AGENT_B))
    assert admission.valid is True
    assert document is not None

    observations: dict[str, tuple[int, int]] = {}

    def answer(node_id: str, content: str):
        def node(
            state: AgentShellState,
            runtime: Runtime[WorkflowRuntimeContext],
        ) -> dict[str, list[AIMessage]]:
            observations[node_id] = (
                len(state.get("messages", [])),
                len(state.get("workflow_state_snapshot", {}).get("agent_invocations", {})),
            )
            return {"messages": [AIMessage(content=content)]}

        return (
            StateGraph(AgentShellState)
            .add_node("answer", node)
            .add_edge(START, "answer")
            .add_edge("answer", END)
            .compile()
        )

    store = InMemoryStore()
    graph = compile_workflow(
        document,
        node_agents={
            "agent-1": _built_agent(
                answer("agent-1", "first agent"),
                agent_id=AGENT_A,
                agent_name="Agent A",
            ),
            "agent-2": _built_agent(
                answer("agent-2", "second agent"),
                agent_id=AGENT_B,
                agent_name="Agent B",
            ),
        },
        store=store,
    )

    result = asyncio.run(
        graph.ainvoke(
            {"shared_vars": {}, "agent_invocations": {}},
            context=WorkflowRuntimeContext(
                request_id="request-1",
                lifecycle_id="lifecycle-1",
                run_id="run-1",
                workflow={"id": "workflow-id"},
            ),
        )
    )

    assert observations == {"agent-1": (0, 0), "agent-2": (0, 1)}
    records = list(result["agent_invocations"].values())
    assert [record["workflow_node_id"] for record in records] == [
        "agent-1",
        "agent-2",
    ]
    artifacts = [
        store.get(
            lifecycle_invocations_namespace("lifecycle-1", "run-1"),
            record["result_ref"],
        ).value
        for record in records
    ]
    assert [artifact["messages"][-1]["content"] for artifact in artifacts] == [
        "first agent",
        "second agent",
    ]
    assert "messages" not in result


def test_normal_edge_fan_out_and_fan_in_merge_invocations_and_independent_files() -> None:
    payload = graph_payload(AGENT_A, AGENT_B, AGENT_C)
    payload["definition"]["edges"] = [  # type: ignore[index]
        {
            "id": "start-agent-1",
            "source": "start",
            "source_handle": "next",
            "target": "agent-1",
            "target_handle": "in",
        },
        {
            "id": "start-agent-2",
            "source": "start",
            "source_handle": "next",
            "target": "agent-2",
            "target_handle": "in",
        },
        {
            "id": "agent-1-agent-3",
            "source": "agent-1",
            "source_handle": "next",
            "target": "agent-3",
            "target_handle": "in",
        },
        {
            "id": "agent-2-agent-3",
            "source": "agent-2",
            "source_handle": "next",
            "target": "agent-3",
            "target_handle": "in",
        },
        {
            "id": "agent-3-end",
            "source": "agent-3",
            "source_handle": "next",
            "target": "end",
            "target_handle": "in",
        },
    ]
    admission, document = admit_workflow_document(payload)
    assert admission.valid is True
    assert document is not None

    observations: dict[str, tuple[int, int, frozenset[str]]] = {}

    def agent_graph(node_id: str, *, file_path: str | None = None):
        def answer(
            state: AgentShellState,
            runtime: Runtime[WorkflowRuntimeContext],
        ) -> dict[str, object]:
            observations[node_id] = (
                len(state.get("messages", [])),
                len(state.get("workflow_state_snapshot", {}).get("agent_invocations", {})),
                frozenset(state.get("files", {})),
            )
            update: dict[str, object] = {
                "messages": [AIMessage(content=node_id)],
                "shared_vars": {node_id: True},
            }
            if file_path is not None:
                update["files"] = {
                    file_path: create_file_data(f"written by {node_id}")
                }
            return update

        return (
            StateGraph(AgentShellState)
            .add_node("answer", answer)
            .add_edge(START, "answer")
            .add_edge("answer", END)
            .compile()
        )

    store = InMemoryStore()
    graph = compile_workflow(
        document,
        node_agents={
            "agent-1": _built_agent(
                agent_graph("agent-1", file_path="/agent-1.txt"),
                agent_id=AGENT_A,
                agent_name="Agent A",
            ),
            "agent-2": _built_agent(
                agent_graph("agent-2", file_path="/agent-2.txt"),
                agent_id=AGENT_B,
                agent_name="Agent B",
            ),
            "agent-3": _built_agent(
                agent_graph("agent-3"),
                agent_id=AGENT_C,
                agent_name="Agent C",
            ),
        },
        store=store,
    )

    result = asyncio.run(
        graph.ainvoke(
            {"shared_vars": {}, "agent_invocations": {}, "files": {}},
            context=WorkflowRuntimeContext(
                request_id="request-1",
                lifecycle_id="lifecycle-1",
                run_id="run-1",
                workflow={"id": "workflow-id"},
            ),
        )
    )

    assert observations == {
        "agent-1": (0, 0, frozenset()),
        "agent-2": (0, 0, frozenset()),
        "agent-3": (
            0,
            2,
            frozenset({"/agent-1.txt", "/agent-2.txt"}),
        ),
    }
    assert result["shared_vars"] == {
        "agent-1": True,
        "agent-2": True,
        "agent-3": True,
    }
    assert {
        record["workflow_node_id"]
        for record in result["agent_invocations"].values()
    } == {"agent-1", "agent-2", "agent-3"}
    assert result["files"]["/agent-1.txt"]["content"] == "written by agent-1"
    assert result["files"]["/agent-2.txt"]["content"] == "written by agent-2"
    assert "messages" not in result


def test_normal_multi_in_compiles_as_one_all_of_barrier_and_runs_target_once() -> None:
    payload = graph_payload(AGENT_A, AGENT_B, AGENT_C)
    payload["definition"]["edges"] = [  # type: ignore[index]
        {
            "id": "start-agent-1",
            "source": "start",
            "source_handle": "next",
            "target": "agent-1",
            "target_handle": "in",
        },
        {
            "id": "start-agent-2",
            "source": "start",
            "source_handle": "next",
            "target": "agent-2",
            "target_handle": "in",
        },
        {
            "id": "agent-1-agent-3",
            "source": "agent-1",
            "source_handle": "next",
            "target": "agent-3",
            "target_handle": "in",
        },
        {
            "id": "agent-2-agent-3",
            "source": "agent-2",
            "source_handle": "next",
            "target": "agent-3",
            "target_handle": "in",
        },
        {
            "id": "agent-3-end",
            "source": "agent-3",
            "source_handle": "next",
            "target": "end",
            "target_handle": "in",
        },
    ]
    admission, document = admit_workflow_document(payload)
    assert admission.valid is True
    assert document is not None

    calls: list[str] = []

    def agent_graph(node_id: str):
        def answer(_state: AgentShellState) -> dict[str, object]:
            calls.append(node_id)
            return {"messages": [AIMessage(content=node_id)]}

        return (
            StateGraph(AgentShellState)
            .add_node("answer", answer)
            .add_edge(START, "answer")
            .add_edge("answer", END)
            .compile()
        )

    store = InMemoryStore()
    graph = compile_workflow(
        document,
        node_agents={
            "agent-1": _built_agent(
                agent_graph("agent-1"), agent_id=AGENT_A, agent_name="Agent A"
            ),
            "agent-2": _built_agent(
                agent_graph("agent-2"), agent_id=AGENT_B, agent_name="Agent B"
            ),
            "agent-3": _built_agent(
                agent_graph("agent-3"), agent_id=AGENT_C, agent_name="Agent C"
            ),
        },
        store=store,
    )

    result = asyncio.run(
        graph.ainvoke(
            {"shared_vars": {}, "agent_invocations": {}},
            context=WorkflowRuntimeContext(
                request_id="request-1",
                lifecycle_id="lifecycle-1",
                run_id="run-1",
                workflow={"id": "workflow-id"},
            ),
        )
    )

    assert calls.count("agent-3") == 1
    assert len(result["agent_invocations"]) == 3


def test_start_and_normal_predecessor_activate_the_same_target_independently() -> None:
    payload = graph_payload(AGENT_A, AGENT_B)
    payload["definition"]["edges"] = [  # type: ignore[index]
        {
            "id": "start-agent-1",
            "source": "start",
            "source_handle": "next",
            "target": "agent-1",
            "target_handle": "in",
        },
        {
            "id": "start-agent-2",
            "source": "start",
            "source_handle": "next",
            "target": "agent-2",
            "target_handle": "in",
        },
        {
            "id": "agent-2-agent-1",
            "source": "agent-2",
            "source_handle": "next",
            "target": "agent-1",
            "target_handle": "in",
        },
        {
            "id": "agent-1-end",
            "source": "agent-1",
            "source_handle": "next",
            "target": "end",
            "target_handle": "in",
        },
    ]
    admission, document = admit_workflow_document(payload)
    assert admission.valid is True
    assert document is not None

    calls: list[str] = []

    def agent_graph(node_id: str):
        def answer(_state: AgentShellState) -> dict[str, object]:
            calls.append(node_id)
            return {"messages": [AIMessage(content=node_id)]}

        return (
            StateGraph(AgentShellState)
            .add_node("answer", answer)
            .add_edge(START, "answer")
            .add_edge("answer", END)
            .compile()
        )

    graph = compile_workflow(
        document,
        node_agents={
            "agent-1": _built_agent(
                agent_graph("agent-1"), agent_id=AGENT_A, agent_name="Agent A"
            ),
            "agent-2": _built_agent(
                agent_graph("agent-2"), agent_id=AGENT_B, agent_name="Agent B"
            ),
        },
        store=InMemoryStore(),
    )

    asyncio.run(
        graph.ainvoke(
            {"shared_vars": {}, "agent_invocations": {}},
            context=WorkflowRuntimeContext(
                lifecycle_id="lifecycle-start-independent",
                run_id="run-start-independent",
                workflow={"id": "workflow-id"},
            ),
        )
    )

    assert calls.count("agent-1") == 2
    assert calls.count("agent-2") == 1
    assert (START, "agent-1") in graph.builder.edges
    assert ("agent-2", "agent-1") in graph.builder.edges
    assert ((START, "agent-2"), "agent-1") not in graph.builder.waiting_edges


def test_normal_terminal_edges_are_independent_end_paths() -> None:
    payload = graph_payload(AGENT_A, AGENT_B)
    payload["definition"]["edges"] = [  # type: ignore[index]
        {
            "id": "start-agent-1",
            "source": "start",
            "source_handle": "next",
            "target": "agent-1",
            "target_handle": "in",
        },
        {
            "id": "start-agent-2",
            "source": "start",
            "source_handle": "next",
            "target": "agent-2",
            "target_handle": "in",
        },
        {
            "id": "agent-1-end",
            "source": "agent-1",
            "source_handle": "next",
            "target": "end",
            "target_handle": "in",
        },
        {
            "id": "agent-2-end",
            "source": "agent-2",
            "source_handle": "next",
            "target": "end",
            "target_handle": "in",
        },
    ]
    admission, document = admit_workflow_document(payload)
    assert admission.valid is True
    assert document is not None

    def agent_graph():
        return (
            StateGraph(AgentShellState)
            .add_node("answer", lambda _state: {"messages": []})
            .add_edge(START, "answer")
            .add_edge("answer", END)
            .compile()
        )

    graph = compile_workflow(
        document,
        node_agents={
            "agent-1": _built_agent(
                agent_graph(), agent_id=AGENT_A, agent_name="Agent A"
            ),
            "agent-2": _built_agent(
                agent_graph(), agent_id=AGENT_B, agent_name="Agent B"
            ),
        },
        store=InMemoryStore(),
    )

    assert ("agent-1", "__end__") in graph.builder.edges
    assert ("agent-2", "__end__") in graph.builder.edges
    assert (("agent-1", "agent-2"), "__end__") not in graph.builder.waiting_edges


def test_agent_defer_config_is_forwarded_to_langgraph_node(monkeypatch) -> None:
    payload = graph_payload(AGENT_A)
    payload["definition"]["nodes"][1]["config"]["defer"] = True  # type: ignore[index]
    admission, document = admit_workflow_document(payload)
    assert admission.valid is True
    assert document is not None

    agent_graph = (
        StateGraph(AgentShellState)
        .add_node("answer", lambda _state: {"messages": []})
        .add_edge(START, "answer")
        .add_edge("answer", END)
        .compile()
    )
    original_add_node = StateGraph.add_node
    node_options: dict[str, object] = {}

    def add_node(builder, node_id, action, **kwargs):
        if node_id == "agent-1":
            node_options.update(kwargs)
        return original_add_node(builder, node_id, action, **kwargs)

    monkeypatch.setattr(StateGraph, "add_node", add_node)
    compile_workflow(
        document,
        node_agents={
            "agent-1": _built_agent(
                agent_graph, agent_id=AGENT_A, agent_name="Agent A"
            )
        },
    )

    assert node_options["defer"] is True


def test_repeated_node_execution_uses_distinct_langgraph_task_invocations() -> None:
    def answer(state: AgentShellState):
        count = int(state.get("shared_vars", {}).get("count", 0)) + 1
        return {
            "messages": [AIMessage(content="completed")],
            "shared_vars": {"count": count},
        }

    agent_graph = (
        StateGraph(AgentShellState)
        .add_node("answer", answer)
        .add_edge(START, "answer")
        .add_edge("answer", END)
        .compile()
    )
    node = _make_agent_node(
        node_id="agent-loop",
        built_agent=_built_agent(
            agent_graph,
            agent_id=AGENT_A,
            agent_name="Loop Agent",
        ),
    )
    parent = StateGraph(WorkflowState, context_schema=WorkflowRuntimeContext)
    parent.add_node("agent-loop", node)
    parent.add_edge(START, "agent-loop")
    parent.add_conditional_edges(
        "agent-loop",
        lambda state: (
            "again" if state.get("shared_vars", {}).get("count", 0) < 2 else "done"
        ),
        {"again": "agent-loop", "done": END},
    )
    store = InMemoryStore()
    graph = parent.compile(store=store)

    result = asyncio.run(
        graph.ainvoke(
            {"shared_vars": {}, "agent_invocations": {}},
            context=WorkflowRuntimeContext(
                request_id="request-loop",
                lifecycle_id="lifecycle-loop",
                run_id="run-loop",
                workflow={"id": "workflow-id"},
            ),
        )
    )
    records = result["agent_invocations"]

    assert len(records) == 1
    assert {record["workflow_node_id"] for record in records.values()} == {
        "agent-loop"
    }
    assert all(record["invocation_id"] == key for key, record in records.items())
    assert {record["agent_id"] for record in records.values()} == {AGENT_A}
    assert all(set(record) == {
        "invocation_id",
        "workflow_id",
        "workflow_node_id",
        "agent_id",
        "invoked_at",
        "result_ref",
    } for record in records.values())
    artifacts = store.search(
        lifecycle_invocations_namespace("lifecycle-loop", "run-loop")
    )
    assert len(artifacts) == 2
    assert {item.key for item in artifacts} != set(records)


def test_static_normal_edge_cycle_has_no_controlled_exit() -> None:
    payload = graph_payload(AGENT_A, AGENT_B)
    payload["definition"]["edges"].append(  # type: ignore[index]
        {
            "id": "agent-2-agent-1",
            "source": "agent-2",
            "source_handle": "next",
            "target": "agent-1",
            "target_handle": "in",
        }
    )
    admission, document = admit_workflow_document(payload)
    assert admission.valid is True
    assert document is not None

    def agent_graph(node_id: str):
        return (
            StateGraph(AgentShellState)
            .add_node(
                "answer",
                lambda _state: {"messages": [AIMessage(content=node_id)]},
            )
            .add_edge(START, "answer")
            .add_edge("answer", END)
            .compile()
        )

    store = InMemoryStore()
    graph = compile_workflow(
        document,
        node_agents={
            "agent-1": _built_agent(
                agent_graph("agent-1"), agent_id=AGENT_A, agent_name="Agent A"
            ),
            "agent-2": _built_agent(
                agent_graph("agent-2"), agent_id=AGENT_B, agent_name="Agent B"
            ),
        },
        store=store,
    )

    with pytest.raises(GraphRecursionError):
        asyncio.run(
            graph.ainvoke(
                {"shared_vars": {}, "agent_invocations": {}},
                config={"recursion_limit": 4},
                context=WorkflowRuntimeContext(
                    lifecycle_id="lifecycle-1",
                    run_id="run-1",
                    workflow={"id": "workflow-id"},
                ),
            )
        )


def test_workflow_agent_nodes_share_official_state_backend_files() -> None:
    admission, document = admit_workflow_document(graph_payload(AGENT_A, AGENT_B))
    assert admission.valid is True
    assert document is not None
    backend = StateBackend()

    def agent_graph(*, write: bool):
        def node(_state: AgentShellState) -> dict[str, list[AIMessage]]:
            if write:
                backend.write("/shared.txt", "from first Agent node")
            else:
                result = backend.read("/shared.txt")
                assert result.error is None
                assert result.file_data is not None
                assert result.file_data["content"] == "from first Agent node"
            return {"messages": [AIMessage(content="ok")]}

        return (
            StateGraph(
                AgentShellState,
                context_schema=WorkflowRuntimeContext,
            )
            .add_node("filesystem", node)
            .add_edge(START, "filesystem")
            .add_edge("filesystem", END)
            .compile()
        )

    store = InMemoryStore()
    graph = compile_workflow(
        document,
        node_agents={
            "agent-1": _built_agent(
                agent_graph(write=True), agent_id=AGENT_A, agent_name="Agent A"
            ),
            "agent-2": _built_agent(
                agent_graph(write=False), agent_id=AGENT_B, agent_name="Agent B"
            ),
        },
        store=store,
    )

    result = asyncio.run(
        graph.ainvoke(
            {"shared_vars": {}, "agent_invocations": {}, "files": {}},
            context=WorkflowRuntimeContext(
                lifecycle_id="lifecycle-1",
                run_id="run-1",
                workflow={"id": "workflow-id"},
            ),
        )
    )

    assert result["files"]["/shared.txt"]["content"] == "from first Agent node"


def test_runtime_builds_repeated_main_agent_references_per_workflow_node() -> None:
    admission, document = admit_workflow_document(graph_payload(AGENT_A, AGENT_A))
    assert admission.valid is True
    assert document is not None

    class RecordingRuntime(AgentRuntime):
        def __init__(self) -> None:
            self.built_ids: list[str] = []
            self.built_nodes: list[str] = []
            self._blocks = None
            self._workflow_checkpoints = None
            self._runtime_diagnostics = None
            self._runtime_policy = None
            lifecycle_store = InMemoryStore()

            class Lifecycle:
                store = lifecycle_store

                async def create(self, *_args, **_kwargs) -> str:
                    return "lifecycle-id"

            self._workflow_lifecycle = Lifecycle()
            self._builder = type(
                "Builder",
                (),
                {
                    "resolve": staticmethod(
                        lambda main_agent_id, **_kwargs: StaticAssembly(
                            main_agent={"id": main_agent_id, "name": "Repeated Agent"},
                            references={},
                            blocks={},
                            filesystem_mode="composite",
                            disabled_capabilities=frozenset(),
                            subagents=(),
                            subagent_nodes={},
                        )
                    )
                },
            )()

        async def build_resolved_agent(self, assembly, _raw_messages, **kwargs):
            main_agent_id = str(assembly.main_agent["id"])
            self.built_ids.append(main_agent_id)
            self.built_nodes.append(str(kwargs["workflow_node_id"]))

            def answer(_state: AgentShellState) -> dict[str, list[AIMessage]]:
                return {"messages": [AIMessage(content=main_agent_id)]}

            graph = (
                StateGraph(AgentShellState)
                .add_node("answer", answer)
                .add_edge(START, "answer")
                .add_edge("answer", END)
                .compile()
            )
            return BuiltAgent(
                graph=graph,
                input_state={"messages": [], "shared_vars": {}},
                event_output_id="",
                event_output_reference={},
                agent_id=main_agent_id,
                agent_name="Repeated Agent",
                subagent_profile_ids={},
                middleware_runtime=_MiddlewareRuntime(),  # type: ignore[arg-type]
            )

        def _execution(self, built: BuiltAgent, **kwargs):
            return {"built": built, **kwargs}

    runtime = RecordingRuntime()
    execution = asyncio.run(
            runtime.start_workflow(
                document,
                [{"role": "user", "content": "Run the Workflow."}],
                workflow_snapshot={"id": "workflow-id"},
                public_output=False,
            )
    )

    assert runtime.built_ids == [AGENT_A, AGENT_A]
    assert runtime.built_nodes == ["agent-1", "agent-2"]
    assert [node_id for node_id, _ in execution["workflow_built"]] == [
        "agent-1",
        "agent-2",
    ]
    result = asyncio.run(
        execution["graph"].ainvoke(
            {"shared_vars": {}, "agent_invocations": {}},
            context=execution["context"],
        )
    )
    assert [
        (
            record["agent_id"],
            record["workflow_node_id"],
        )
        for record in result["agent_invocations"].values()
    ] == [
        (AGENT_A, "agent-1"),
        (AGENT_A, "agent-2"),
    ]
    assert len(set(result["agent_invocations"])) == 2
