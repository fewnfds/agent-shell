from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.memory import InMemoryStore

from agent_shell.command import CommandError, run_command
from agent_shell.command_packages import CommandPackageRuntime
from agent_shell.runtime.agent_builder import BuiltAgent
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.state import AgentShellState
from agent_shell.runtime.lifecycle_store import lifecycle_invocations_namespace
from agent_shell.workflow import admit_workflow_document
from agent_shell.workflow.compiler import compile_workflow
from agent_shell.workflow.topology import validate_workflow_topology


COMMAND_ID = "11111111-1111-4111-8111-111111111111"
AGENT_A = "22222222-2222-4222-8222-222222222222"
AGENT_B = "33333333-3333-4333-8333-333333333333"


def _runtime(**kwargs) -> Runtime[WorkflowRuntimeContext]:
    return Runtime(context=WorkflowRuntimeContext(**kwargs))


class _MiddlewareRuntime:
    async def close(self) -> None:
        return None


def _built_agent(agent_id: str, content: str) -> BuiltAgent:
    graph = (
        StateGraph(AgentShellState)
        .add_node(
            "answer",
            lambda _state: {"messages": [AIMessage(content=content)]},
        )
        .add_edge(START, "answer")
        .add_edge("answer", END)
        .compile()
    )
    return BuiltAgent(
        graph=graph,
        input_state={"messages": [], "shared_vars": {}},
        event_output_id="",
        event_output_reference={},
        agent_id=agent_id,
        agent_name=content,
        subagent_profile_ids={},
        middleware_runtime=_MiddlewareRuntime(),  # type: ignore[arg-type]
    )


def _built_agent_graph(agent_id: str, graph) -> BuiltAgent:
    return BuiltAgent(
        graph=graph,
        input_state={"messages": [], "shared_vars": {}, "files": {}},
        event_output_id="",
        event_output_reference={},
        agent_id=agent_id,
        agent_name=agent_id,
        subagent_profile_ids={},
        middleware_runtime=_MiddlewareRuntime(),  # type: ignore[arg-type]
    )


def test_command_receives_complete_values_and_converts_state_mutation() -> None:
    async def command(state, runtime):
        state.setdefault("shared_vars", {})["workflow_id"] = runtime.context.workflow_id
        return {
            "activate": ["review", "audit"],
            "dispatch": [
                {
                    "task_id": "item:42",
                    "dispatch_key": "process",
                    "payload": {"item_id": 42},
                }
            ],
            "update": {},
        }

    result = asyncio.run(
        run_command(
            command,
            state={"shared_vars": {"risk": 90}, "agent_invocations": {}, "files": {}},
            runtime=_runtime(
                workflow_id="workflow-1",
            ),
            allowed_branches={"review", "audit"},
            allowed_dispatch_keys={"process"},
        )
    )

    assert result.activate == ["review", "audit"]
    assert result.dispatch[0].model_dump(mode="json") == {
        "task_id": "item:42",
        "dispatch_key": "process",
        "payload": {"item_id": 42},
    }
    assert result.update == {"shared_vars": {"risk": 90, "workflow_id": "workflow-1"}}


def test_command_accepts_zero_targets_and_rejects_unmapped_keys() -> None:
    async def command(state, runtime):
        return {"activate": [], "update": {}}
    result = asyncio.run(
        run_command(
            command,
            state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
            runtime=_runtime(),
            allowed_branches=set(),
        )
    )
    assert result.activate == []

    async def multiple_business_keys(state, runtime):
        return {"activate": ["fallback", "review"], "update": {}}
    result = asyncio.run(
        run_command(
            multiple_business_keys,
            state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
            runtime=_runtime(),
            allowed_branches={"review", "fallback"},
        )
    )
    assert result.activate == ["fallback", "review"]

    async def unmapped(state, runtime):
        return {"activate": ["missing edge"], "update": {}}
    with pytest.raises(CommandError):
        asyncio.run(
            run_command(
                unmapped,
                state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
                runtime=_runtime(),
                allowed_branches={"review", "audit"},
            )
        )


@pytest.mark.parametrize("mutate_state", [False, True])
def test_command_rejects_invalid_workflow_state_value_shapes(
    mutate_state: bool,
) -> None:
    async def invalid_update(state, runtime):
        if mutate_state:
            state["shared_vars"] = []
            return {"activate": [], "update": {}}
        return {"activate": [], "update": {"shared_vars": []}}

    with pytest.raises(CommandError):
        asyncio.run(
            run_command(
                invalid_update,
                state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
                runtime=_runtime(),
                allowed_branches=set(),
            )
        )


def test_command_package_loads_local_modules_and_materializes_async_route(
    tmp_path: Path,
) -> None:
    folder_name = COMMAND_ID
    package_dir = tmp_path / "packages" / "command" / folder_name
    package_dir.mkdir(parents=True)
    (package_dir / "package.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "id": COMMAND_ID,
                "family": "workflow-node",
                "adapter": "command",
            }
        ),
        encoding="utf-8",
    )
    (package_dir / "main.py").write_text(
        "from .routing import build_route\n"
            "def create_command():\n"
            "    return build_route(80)\n",
        encoding="utf-8",
    )
    (package_dir / "routing.py").write_text(
        "def build_route(threshold):\n"
        "    async def route(state, runtime):\n"
        "        branch = 'review' if state['shared_vars']['risk'] >= threshold else 'continue'\n"
        "        return {'activate': [branch], 'update': {}}\n"
        "    return route\n",
        encoding="utf-8",
    )
    runtime = CommandPackageRuntime(
        request_id="request-1",
        packages_dir=tmp_path / "packages",
        runtime_root=tmp_path / "runtime",
    )
    command = runtime.command_for(
        "command-node",
        COMMAND_ID,
        {"folder": folder_name},
    )

    result = asyncio.run(
        run_command(
            command,
            state={"shared_vars": {"risk": 90}, "agent_invocations": {}, "files": {}},
            runtime=_runtime(),
            allowed_branches={"review", "continue"},
        )
    )

    assert result.activate == ["review"]
    asyncio.run(runtime.close())


def test_compiler_uses_command_for_named_multi_branch_routing() -> None:
    payload = {
        "definition": {
            "schema_version": 1,
            "state_contract": "agent-shell.workflow.agent-invocations.v1",
            "nodes": [
                {"id": "start", "type": "start", "type_version": 1, "config": {}},
                {
                    "id": "command",
                    "type": "command",
                    "type_version": 1,
                    "config": {"command_id": COMMAND_ID},
                },
                {"id": "agent-a", "type": "agent", "type_version": 1, "config": {"main_agent_id": AGENT_A}},
                {"id": "agent-b", "type": "agent", "type_version": 1, "config": {"main_agent_id": AGENT_B}},
                {"id": "end", "type": "end", "type_version": 1, "config": {}},
            ],
            "edges": [
                {"id": "start-command", "source": "start", "source_handle": "next", "target": "command", "target_handle": "in"},
                {"id": "review", "source": "command", "source_handle": "branch", "target": "agent-a", "target_handle": "in", "branch_key": "review"},
                {"id": "audit", "source": "command", "source_handle": "branch", "target": "agent-b", "target_handle": "in", "branch_key": "audit"},
                {"id": "agent-a-end", "source": "agent-a", "source_handle": "next", "target": "end", "target_handle": "in"},
                {"id": "agent-b-end", "source": "agent-b", "source_handle": "next", "target": "end", "target_handle": "in"},
            ],
        },
        "layout": {},
    }
    admission, document = admit_workflow_document(payload)
    assert admission.valid is True
    assert document is not None
    async def command(state, runtime):
        return {
            "activate": ["review", "audit"],
            "update": {"shared_vars": {"routed": True}},
        }
    assert validate_workflow_topology(document, commands={"command": command}) == ()
    graph = compile_workflow(
        document,
        node_agents={
            "agent-a": _built_agent(AGENT_A, "agent-a"),
            "agent-b": _built_agent(AGENT_B, "agent-b"),
        },
        commands={"command": command},
        store=InMemoryStore(),
    )

    result = asyncio.run(
        graph.ainvoke(
            {"shared_vars": {}, "agent_invocations": {}, "files": {}},
            context=WorkflowRuntimeContext(
                lifecycle_id="lifecycle-1",
                run_id="run-1",
                workflow_id="workflow-1",
            ),
        )
    )

    assert result["shared_vars"] == {"routed": True}
    assert {
        record["workflow_node_id"]
        for record in result["agent_invocations"].values()
    } == {"agent-a", "agent-b"}


def test_compiler_commits_update_and_ends_at_command_with_zero_targets() -> None:
    payload = {
        "definition": {
            "schema_version": 1,
            "state_contract": "agent-shell.workflow.agent-invocations.v1",
            "nodes": [
                {"id": "start", "type": "start", "type_version": 1, "config": {}},
                {
                    "id": "command",
                    "type": "command",
                    "type_version": 1,
                    "config": {"command_id": COMMAND_ID},
                },
                {"id": "end", "type": "end", "type_version": 1, "config": {}},
            ],
            "edges": [
                {"id": "start-command", "source": "start", "source_handle": "next", "target": "command", "target_handle": "in"},
            ],
        },
        "layout": {},
    }
    admission, document = admit_workflow_document(payload)
    assert admission.valid is True
    assert document is not None

    async def command(state, runtime):
        return {"activate": [], "update": {"shared_vars": {"launched": True}}}

    assert validate_workflow_topology(document, commands={"command": command}) == ()
    graph = compile_workflow(document, node_agents={}, commands={"command": command})
    result = asyncio.run(
        graph.ainvoke(
            {"shared_vars": {}, "agent_invocations": {}, "files": {}},
            context=WorkflowRuntimeContext(
                lifecycle_id="lifecycle-1",
                run_id="run-1",
                workflow_id="workflow-1",
            ),
        )
    )

    assert result["shared_vars"] == {"launched": True}


def test_command_validates_dispatch_keys_task_ids_and_json_payloads() -> None:
    async def duplicate(state, runtime):
        return {
            "dispatch": [
                {"task_id": "same", "dispatch_key": "city", "payload": {}},
                {"task_id": "same", "dispatch_key": "city", "payload": {}},
            ]
        }

    with pytest.raises(CommandError):
        asyncio.run(
            run_command(
                duplicate,
                state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
                runtime=_runtime(),
                allowed_branches=(),
                allowed_dispatch_keys={"city"},
            )
        )

    async def unmapped(state, runtime):
        return {
            "dispatch": [
                {"task_id": "city:2", "dispatch_key": "missing", "payload": {}}
            ]
        }

    with pytest.raises(CommandError):
        asyncio.run(
            run_command(
                unmapped,
                state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
                runtime=_runtime(),
                allowed_branches=(),
                allowed_dispatch_keys={"city"},
            )
        )

    for payload in ({"value": object()}, {"value": float("nan")}):
        async def invalid_payload(state, runtime, payload=payload):
            return {
                "dispatch": [
                    {
                        "task_id": "city:3",
                        "dispatch_key": "city",
                        "payload": payload,
                    }
                ]
            }

        with pytest.raises(CommandError):
            asyncio.run(
                run_command(
                    invalid_payload,
                    state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
                    runtime=_runtime(),
                    allowed_branches=(),
                    allowed_dispatch_keys={"city"},
                )
            )


def _dispatch_graph_payload() -> dict[str, Any]:
    return {
        "definition": {
            "schema_version": 1,
            "state_contract": "agent-shell.workflow.agent-invocations.v1",
            "nodes": [
                {"id": "start", "type": "start", "type_version": 1, "config": {}},
                {
                    "id": "command",
                    "type": "command",
                    "type_version": 1,
                    "config": {"command_id": COMMAND_ID},
                },
                {
                    "id": "worker-a",
                    "type": "agent",
                    "type_version": 1,
                    "config": {"main_agent_id": AGENT_A},
                },
                {
                    "id": "worker-b",
                    "type": "agent",
                    "type_version": 1,
                    "config": {"main_agent_id": AGENT_A},
                },
                {
                    "id": "branch-agent",
                    "type": "agent",
                    "type_version": 1,
                    "config": {"main_agent_id": AGENT_B},
                },
                {
                    "id": "collector",
                    "type": "agent",
                    "type_version": 1,
                    "config": {"main_agent_id": AGENT_B, "defer": True},
                },
                {"id": "end", "type": "end", "type_version": 1, "config": {}},
            ],
            "edges": [
                {"id": "start-command", "source": "start", "source_handle": "next", "target": "command", "target_handle": "in"},
                {"id": "command-worker-a", "source": "command", "source_handle": "dispatch", "target": "worker-a", "target_handle": "in", "dispatch_key": "record"},
                {"id": "command-worker-b", "source": "command", "source_handle": "dispatch", "target": "worker-b", "target_handle": "in", "dispatch_key": "town"},
                {"id": "command-branch", "source": "command", "source_handle": "branch", "target": "branch-agent", "target_handle": "in", "branch_key": "audit"},
                {"id": "worker-a-collector", "source": "worker-a", "source_handle": "next", "target": "collector", "target_handle": "in"},
                {"id": "worker-b-collector", "source": "worker-b", "source_handle": "next", "target": "collector", "target_handle": "in"},
                {"id": "branch-collector", "source": "branch-agent", "source_handle": "next", "target": "collector", "target_handle": "in"},
                {"id": "collector-end", "source": "collector", "source_handle": "next", "target": "end", "target_handle": "in"},
            ],
        },
        "layout": {},
    }


def test_compiler_combines_branch_dispatch_and_update_with_deferred_collection() -> None:
    admission, document = admit_workflow_document(_dispatch_graph_payload())
    assert admission.valid is True
    assert document is not None
    async def command(state, runtime):
        assert runtime.context.workflow_node_id == "command"
        return {
            "activate": ["audit"],
            "dispatch": [
                {"task_id": "record:1", "dispatch_key": "record", "payload": {"value": 1}},
                {"task_id": "record:2", "dispatch_key": "record", "payload": {"value": 2}},
                {"task_id": "town:1", "dispatch_key": "town", "payload": {"value": 3}},
            ],
            "update": {"shared_vars": {"planned": 3}},
        }

    def worker(state: AgentShellState) -> dict[str, Any]:
        task = state["workflow_task"]
        return {"messages": [AIMessage(content=str(task["payload"]["value"]))]}

    def branch_agent(state: AgentShellState) -> dict[str, Any]:
        assert "workflow_task" not in state
        return {"messages": [AIMessage(content="audit")]}

    def collector(state: AgentShellState) -> dict[str, Any]:
        records = state["workflow_state_snapshot"]["agent_invocations"].values()
        task_ids = sorted(
            record["workflow_task"]["task_id"]
            for record in records
            if "workflow_task" in record
        )
        return {"messages": [AIMessage(content=",".join(task_ids))]}

    def graph_for(function):
        return (
            StateGraph(AgentShellState)
            .add_node("run", function)
            .add_edge(START, "run")
            .add_edge("run", END)
            .compile()
        )

    store = InMemoryStore()
    graph = compile_workflow(
        document,
        node_agents={
            "worker-a": _built_agent_graph(AGENT_A, graph_for(worker)),
            "worker-b": _built_agent_graph(AGENT_A, graph_for(worker)),
            "branch-agent": _built_agent_graph(AGENT_B, graph_for(branch_agent)),
            "collector": _built_agent_graph(AGENT_B, graph_for(collector)),
        },
        commands={"command": command},
        store=store,
    )

    result = asyncio.run(
        graph.ainvoke(
            {"shared_vars": {}, "agent_invocations": {}, "files": {}},
            context=WorkflowRuntimeContext(
                lifecycle_id="lifecycle-1",
                run_id="run-1",
                workflow_id="workflow-1",
            ),
        )
    )

    records = list(result["agent_invocations"].values())
    worker_records = [
        record
        for record in records
        if record["workflow_node_id"] in {"worker-a", "worker-b"}
    ]
    assert sorted(record["workflow_task"]["task_id"] for record in worker_records) == [
        "record:1",
        "record:2",
        "town:1",
    ]
    assert {record["workflow_task"]["command_node_id"] for record in worker_records} == {"command"}
    assert {record["workflow_node_id"] for record in worker_records} == {"worker-a", "worker-b"}
    assert result["shared_vars"] == {"planned": 3}
    collector_record = next(
        record for record in records if record["workflow_node_id"] == "collector"
    )
    artifact = store.get(
        lifecycle_invocations_namespace("lifecycle-1", "run-1"),
        collector_record["result_ref"],
    )
    assert artifact is not None
    assert artifact.value["messages"][-1]["content"] == "record:1,record:2,town:1"


def test_dispatch_topology_rejects_non_agent_targets_and_parallel_node_pairs() -> None:
    admission, document = admit_workflow_document(_dispatch_graph_payload())
    assert admission.valid is True
    assert document is not None

    duplicate_pair = document.model_copy(deep=True)
    duplicate_pair.definition.edges.append(
        duplicate_pair.definition.edges[1].model_copy(
            update={
                "id": "command-worker-a-branch",
                "source_handle": "branch",
                "branch_key": "also-worker-a",
                "dispatch_key": None,
            }
        )
    )
    issues = validate_workflow_topology(
        duplicate_pair,
        commands={"command": object()},
    )
    assert "workflow.edge_duplicate" in {issue.code for issue in issues}

    command_target = document.model_copy(deep=True)
    command_target.definition.edges[1] = command_target.definition.edges[1].model_copy(
        update={"target": "command"}
    )
    end_target = document.model_copy(deep=True)
    end_target.definition.edges[1] = end_target.definition.edges[1].model_copy(
        update={"target": "end"}
    )
    for invalid in (command_target, end_target):
        issues = validate_workflow_topology(
            invalid,
            commands={"command": object()},
        )
        assert "workflow.edge_type_mismatch" in {issue.code for issue in issues}
