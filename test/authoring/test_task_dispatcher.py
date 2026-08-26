from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.memory import InMemoryStore

from agent_shell.runtime.agent_builder import BuiltAgent
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.state import AgentShellState
from agent_shell.runtime.workflow_lifecycle import lifecycle_invocations_namespace
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.task_dispatcher import TaskDispatcherError, run_task_dispatcher
from agent_shell.task_dispatcher_packages import TaskDispatcherPackageRuntime
from agent_shell.workflow import admit_workflow_document, compile_workflow
from agent_shell.workflow.topology import validate_workflow_topology

from .app_support import make_client


DISPATCHER_ID = "11111111-1111-4111-8111-111111111111"
WORKER_ID = "22222222-2222-4222-8222-222222222222"
TOWN_WORKER_ID = "55555555-5555-4555-8555-555555555555"
COLLECTOR_ID = "33333333-3333-4333-8333-333333333333"


def _runtime(**kwargs) -> Runtime[WorkflowRuntimeContext]:
    return Runtime(context=WorkflowRuntimeContext(**kwargs))


class _MiddlewareRuntime:
    async def close(self) -> None:
        return None


def _built_agent(agent_id: str, graph) -> BuiltAgent:
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


def _graph_payload() -> dict:
    return {
        "definition": {
            "schema_version": 1,
            "state_contract": "agent-shell.workflow.agent-invocations.v1",
            "nodes": [
                {"id": "start", "type": "start", "type_version": 1, "config": {}},
                {
                    "id": "dispatcher",
                    "type": "task-dispatcher",
                    "type_version": 1,
                    "config": {"task_dispatcher_id": DISPATCHER_ID},
                },
                {
                    "id": "worker",
                    "type": "agent",
                    "type_version": 1,
                    "config": {"main_agent_id": WORKER_ID},
                },
                {
                    "id": "collector",
                    "type": "agent",
                    "type_version": 1,
                    "config": {"main_agent_id": COLLECTOR_ID, "defer": True},
                },
                {
                    "id": "town-worker",
                    "type": "agent",
                    "type_version": 1,
                    "config": {"main_agent_id": TOWN_WORKER_ID},
                },
                {"id": "end", "type": "end", "type_version": 1, "config": {}},
            ],
            "edges": [
                {
                    "id": "start-dispatcher",
                    "source": "start",
                    "source_handle": "next",
                    "target": "dispatcher",
                    "target_handle": "in",
                },
                {
                    "id": "dispatch-worker",
                    "source": "dispatcher",
                    "source_handle": "dispatch",
                    "target": "worker",
                    "target_handle": "in",
                    "dispatch_key": "record",
                },
                {
                    "id": "worker-collector",
                    "source": "worker",
                    "source_handle": "next",
                    "target": "collector",
                    "target_handle": "in",
                },
                {
                    "id": "dispatch-town-worker",
                    "source": "dispatcher",
                    "source_handle": "dispatch",
                    "target": "town-worker",
                    "target_handle": "in",
                    "dispatch_key": "town",
                },
                {
                    "id": "town-worker-collector",
                    "source": "town-worker",
                    "source_handle": "next",
                    "target": "collector",
                    "target_handle": "in",
                },
                {
                    "id": "collector-end",
                    "source": "collector",
                    "source_handle": "next",
                    "target": "end",
                    "target_handle": "in",
                },
            ],
        },
        "layout": {},
    }


def test_dispatcher_validates_task_identity_routes_and_state_updates() -> None:
    async def dispatch(state, runtime):
        state.setdefault("shared_vars", {})["workflow_id"] = runtime.context.workflow["id"]
        return {
            "tasks": [
                {
                    "task_id": "city:1",
                    "dispatch_key": "city",
                    "payload": {"value": 1},
                }
            ],
            "update": {},
        }

    result = asyncio.run(
        run_task_dispatcher(
            dispatch,
            state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
            runtime=_runtime(workflow={"id": "workflow-1"}),
            allowed_dispatch_keys={"city"},
        )
    )

    assert result.tasks[0].payload == {"value": 1}
    assert result.update == {"shared_vars": {"workflow_id": "workflow-1"}}

    async def duplicate(state, runtime):
        return {
            "tasks": [
                {"task_id": "same", "dispatch_key": "city", "payload": {}},
                {"task_id": "same", "dispatch_key": "city", "payload": {}},
            ],
            "update": {},
        }

    with pytest.raises(TaskDispatcherError):
        asyncio.run(
            run_task_dispatcher(
                duplicate,
                state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
                runtime=_runtime(),
                allowed_dispatch_keys={"city"},
            )
        )

    async def unmapped(state, runtime):
        return {
            "tasks": [{"task_id": "city:2", "dispatch_key": "missing", "payload": {}}],
            "update": {},
        }

    with pytest.raises(TaskDispatcherError):
        asyncio.run(
            run_task_dispatcher(
                unmapped,
                state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
                runtime=_runtime(),
                allowed_dispatch_keys={"city"},
            )
        )

    async def invalid_payload(state, runtime):
        return {
            "tasks": [
                {
                    "task_id": "city:3",
                    "dispatch_key": "city",
                    "payload": {"value": object()},
                }
            ],
            "update": {},
        }

    with pytest.raises(TaskDispatcherError):
        asyncio.run(
            run_task_dispatcher(
                invalid_payload,
                state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
                runtime=_runtime(),
                allowed_dispatch_keys={"city"},
            )
        )


def test_task_dispatcher_package_materializes_async_dispatch(tmp_path: Path) -> None:
    folder_name = "City dispatcher"
    package_dir = tmp_path / "packages" / "task_dispatcher" / folder_name
    package_dir.mkdir(parents=True)
    (package_dir / "package.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "id": DISPATCHER_ID,
                "family": "workflow-node",
                "adapter": "task-dispatcher",
            }
        ),
        encoding="utf-8",
    )
    (package_dir / "main.py").write_text(
        "def create_dispatcher():\n"
        "    async def dispatch(state, runtime):\n"
        "        city = state['shared_vars']['cities'][0]\n"
        "        return {'tasks': [{'task_id': city['id'], 'dispatch_key': 'city', 'payload': city}], 'update': {}}\n"
        "    return dispatch\n",
        encoding="utf-8",
    )
    runtime = TaskDispatcherPackageRuntime(
        request_id="request-1",
        packages_dir=tmp_path / "packages",
        runtime_root=tmp_path / "runtime",
    )
    dispatch = runtime.dispatcher_for(
        "dispatcher-node",
        DISPATCHER_ID,
        {"folder": folder_name},
    )

    result = asyncio.run(
        run_task_dispatcher(
            dispatch,
            state={
                "shared_vars": {"cities": [{"id": "city:1"}]},
                "agent_invocations": {},
                "files": {},
            },
            runtime=_runtime(),
            allowed_dispatch_keys={"city"},
        )
    )

    assert result.tasks[0].task_id == "city:1"
    assert result.tasks[0].payload == {"id": "city:1"}
    asyncio.run(runtime.close())


def test_compiler_sends_private_task_to_worker_state_and_subgraph_context() -> None:
    admission, document = admit_workflow_document(_graph_payload())
    assert admission.valid is True
    assert document is not None

    async def dispatch(state, runtime):
        assert runtime.context.workflow_node_id == "dispatcher"
        assert runtime.context.invocation_id
        return {
            "tasks": [
                {"task_id": "record:1", "dispatch_key": "record", "payload": {"value": 1}},
                {"task_id": "record:2", "dispatch_key": "record", "payload": {"value": 2}},
                {"task_id": "town:1", "dispatch_key": "town", "payload": {"value": 3}},
            ],
            "update": {"shared_vars": {"planned": 2}},
        }

    def worker(
        state: AgentShellState,
        runtime: Runtime[WorkflowRuntimeContext],
    ) -> dict:
        task = state["workflow_task"]
        assert runtime.context.workflow_node_id in {"worker", "town-worker"}
        return {"messages": [AIMessage(content=str(task["payload"]["value"]))]}

    def collector(
        state: AgentShellState,
        runtime: Runtime[WorkflowRuntimeContext],
    ) -> dict:
        records = state["workflow_state_snapshot"]["agent_invocations"].values()
        task_ids = sorted(
            record["workflow_task"]["task_id"]
            for record in records
            if "workflow_task" in record
        )
        return {"messages": [AIMessage(content=",".join(task_ids))]}

    worker_graph = (
        StateGraph(AgentShellState, context_schema=WorkflowRuntimeContext)
        .add_node("worker", worker)
        .add_edge(START, "worker")
        .add_edge("worker", END)
        .compile()
    )
    collector_graph = (
        StateGraph(AgentShellState, context_schema=WorkflowRuntimeContext)
        .add_node("collector", collector)
        .add_edge(START, "collector")
        .add_edge("collector", END)
        .compile()
    )
    store = InMemoryStore()
    graph = compile_workflow(
        document,
        node_agents={
            "worker": _built_agent(WORKER_ID, worker_graph),
            "town-worker": _built_agent(TOWN_WORKER_ID, worker_graph),
            "collector": _built_agent(COLLECTOR_ID, collector_graph),
        },
        task_dispatchers={"dispatcher": dispatch},
        store=store,
    )

    result = asyncio.run(
        graph.ainvoke(
            {"shared_vars": {}, "agent_invocations": {}, "files": {}},
            context=WorkflowRuntimeContext(
                lifecycle_id="lifecycle-1",
                run_id="run-1",
                workflow={"id": "workflow-1"},
            ),
        )
    )

    records = list(result["agent_invocations"].values())
    worker_records = [record for record in records if record["workflow_node_id"] == "worker"]
    collector_records = [record for record in records if record["workflow_node_id"] == "collector"]
    town_worker_records = [
        record for record in records if record["workflow_node_id"] == "town-worker"
    ]
    assert sorted(record["workflow_task"]["task_id"] for record in worker_records) == [
        "record:1",
        "record:2",
    ]
    assert [record["workflow_task"]["task_id"] for record in town_worker_records] == [
        "town:1"
    ]
    assert len(collector_records) == 1
    collector_artifact = store.get(
        lifecycle_invocations_namespace("lifecycle-1", "run-1"),
        collector_records[0]["result_ref"],
    )
    assert collector_artifact is not None
    assert collector_artifact.value["messages"][-1]["content"] == (
        "record:1,record:2,town:1"
    )
    worker_artifact = store.get(
        lifecycle_invocations_namespace("lifecycle-1", "run-1"),
        worker_records[0]["result_ref"],
    )
    assert worker_artifact is not None
    assert worker_artifact.value["workflow_task"]["payload"] == {"value": 1}
    assert "payload" not in worker_records[0]["workflow_task"]
    assert result["shared_vars"] == {"planned": 2}


def test_dispatch_edges_require_unique_keys_and_cannot_mix_worker_inputs() -> None:
    admission, document = admit_workflow_document(_graph_payload())
    assert admission.valid is True
    assert document is not None
    duplicate = document.model_copy(deep=True)
    duplicate.definition.edges.append(
        duplicate.definition.edges[1].model_copy(update={"id": "dispatch-worker-copy"})
    )
    duplicate.definition.edges.append(
        duplicate.definition.edges[0].model_copy(
            update={
                "id": "start-worker",
                "target": "worker",
            }
        )
    )

    async def dispatch(state, runtime):
        return {"tasks": [], "update": {}}

    issues = validate_workflow_topology(
        duplicate,
        task_dispatchers={"dispatcher": dispatch},
    )
    assert {issue.code for issue in issues} >= {
        "workflow.dispatch_key_duplicate",
        "workflow.task_worker_input_mixed",
    }


def test_builtin_dispatcher_example_creates_owned_python_package(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = Path(__file__).parents[2]
    shutil.copytree(
        repository
        / "examples"
        / "workflow-components"
        / "task-dispatcher"
        / "item-list-dispatcher",
        tmp_path
        / "examples"
        / "workflow-components"
        / "task-dispatcher"
        / "item-list-dispatcher",
    )
    client = make_client(tmp_path, monkeypatch)
    catalog_response = client.get("/api/python-package-templates/task-dispatcher")
    assert catalog_response.status_code == 200
    selected = catalog_response.json()["catalog"][0]
    assert selected["key"] == "内置示例-item-list-dispatcher"

    response = client.post(
        "/api/blocks/task-dispatcher",
        json={
            "name": "Item tasks",
            "python_package": {"folder": ""},
            "python_package_template": {
                "key": selected["key"],
                "revision": selected["revision"],
            },
        },
    )

    assert response.status_code == 200, response.text
    created = response.json()
    manifest_path = (
        FileConfigRepository(tmp_path / "data").python_packages_root
        / "task_dispatcher"
        / created["name"]
        / "package.json"
    )
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == {
        "format_version": 1,
        "family": "workflow-node",
        "adapter": "task-dispatcher",
        "id": created["id"],
    }
