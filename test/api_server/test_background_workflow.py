from __future__ import annotations

import asyncio

from agent_shell.runtime.agent_runtime import AgentRuntime
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.errors import AgentRuntimeError

from .support import *


@pytest.mark.parametrize(
    ("parent_checkpointer_enabled", "child_checkpointer_enabled"),
    ((True, True), (True, False), (False, True), (False, False)),
)
def test_parent_and_frozen_child_use_independent_checkpointer_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_checkpointer_enabled: bool,
    child_checkpointer_enabled: bool,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        child = create_workflow(
            client,
            name="Background Child",
            workflow_role="child",
        )
        event_output = workflow_event_output_payload(
            client,
            "Exploding child output",
            source=(
                "def output(event):\n"
                "    raise RuntimeError('child public output must stay disabled')\n"
            ),
        )
        output_response = client.post(
            "/api/blocks/workflow-event-output",
            json=event_output,
        )
        assert output_response.status_code == 200, output_response.text
        checkpointer = client.post(
            "/api/blocks/checkpointer",
            json={"name": "Background checkpoints", "durability": "async"},
        )
        assert checkpointer.status_code == 200, checkpointer.text
        child_response = client.put(
            f"/api/workflows/{child['id']}",
            json={
                **{
                    key: child[key]
                    for key in (
                        "name",
                        "workflow_role",
                        "description",
                        "recursion_limit",
                        "execution_timeout_seconds",
                        "max_concurrency",
                    )
                },
                "workflow_event_output_id": output_response.json()["id"],
                "checkpointer_id": (
                    checkpointer.json()["id"]
                    if child_checkpointer_enabled
                    else None
                ),
            },
        )
        assert child_response.status_code == 200, child_response.text
        child = child_response.json()
        save_linear_workflow_graph(client, child, main_agent)
        parent = create_workflow(client, name="Not A Child Target")
        if parent_checkpointer_enabled:
            parent_response = client.put(
                f"/api/workflows/{parent['id']}",
                json={
                    **{
                        key: parent[key]
                        for key in (
                            "name",
                            "workflow_role",
                            "description",
                            "workflow_event_output_id",
                            "recursion_limit",
                            "execution_timeout_seconds",
                            "max_concurrency",
                        )
                    },
                    "checkpointer_id": checkpointer.json()["id"],
                },
            )
            assert parent_response.status_code == 200, parent_response.text
            parent = parent_response.json()
        snapshot = client.app.state.agent_runtime.capture()
        disabled = client.put(
            f"/api/workflows/{child['id']}/draft",
            json=client.get(f"/api/workflows/{child['id']}/graph").json(),
        )
        assert disabled.status_code == 200, disabled.text
        portal = client.portal
        assert portal is not None

        async def scenario():
            lifecycle_id = await client.app.state.workflow_lifecycle.create(
                [{"role": "user", "content": "lifecycle input"}],
                request_id="request-background",
                run_id="parent-run",
                checkpoint_thread_id=(
                    "parent-thread" if parent_checkpointer_enabled else None
                ),
                workflow_id="parent-workflow",
                workflow_name="Parent Workflow",
            )
            context = WorkflowRuntimeContext.for_run(
                request_id="request-background",
                lifecycle_id=lifecycle_id,
                run_id="parent-run",
                checkpoint_thread_id=(
                    "parent-thread" if parent_checkpointer_enabled else None
                ),
                run_depth=0,
                workflow={"id": "parent-workflow"},
                background_runtime=snapshot,
            )
            assert context.background_runs is not None
            try:
                await context.background_runs.start_workflow(
                    parent["id"],
                    operation_id="invalid-parent-target",
                    shared_vars={},
                )
            except AgentRuntimeError as exc:
                assert exc.code == "background_workflow_target_not_found"
            else:
                raise AssertionError("a parent Workflow must not be a child target")
            handle = await context.background_runs.start_workflow(
                child["id"],
                operation_id="child-task-1",
                shared_vars={"input": {"value": 7}},
            )
            terminal = None
            for _ in range(200):
                terminal = (
                    await context.background_runs.check([handle.task_id])
                )[0]
                if terminal.runtime_status not in {"pending", "running"}:
                    break
                await asyncio.sleep(0.01)
            run = client.app.state.workflow_lifecycle.history.get_run(
                handle.child_run_id
            )
            checkpoint_count = (
                await client.app.state.workflow_checkpoints.checkpoint_count(
                    handle.checkpoint_thread_id
                )
                if handle.checkpoint_thread_id is not None
                else 0
            )
            return handle, terminal, run, checkpoint_count

        handle, terminal, run, checkpoint_count = portal.call(scenario)

    assert handle.status == "pending"
    assert handle.run_depth == 1
    assert terminal is not None
    assert terminal.runtime_status == "succeeded"
    assert isinstance(terminal.result["finish_reason"], str)
    assert isinstance(terminal.result["usage"], dict)
    assert run is not None
    assert (handle.checkpoint_thread_id is not None) is child_checkpointer_enabled
    assert run["checkpoint_thread_id"] == handle.checkpoint_thread_id
    assert run["run_id"] == handle.child_run_id
    assert run["run_kind"] == "workflow"
    assert run["status"] == "completed"
    assert (checkpoint_count > 0) is child_checkpointer_enabled


def test_frozen_snapshot_runs_background_agent_without_parent_stream_or_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_context = None
    original_start_background_agent = AgentRuntime.start_background_agent

    async def observe_start_background_agent(self, *args, **kwargs):
        nonlocal captured_context
        execution = await original_start_background_agent(self, *args, **kwargs)
        assert execution.context is not None
        captured_context = execution.context
        return execution

    monkeypatch.setattr(
        AgentRuntime,
        "start_background_agent",
        observe_start_background_agent,
    )
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        parent = create_workflow(client, name="Agent Launcher")
        snapshot = client.app.state.agent_runtime.capture()
        portal = client.portal
        assert portal is not None

        async def scenario():
            lifecycle_id = await client.app.state.workflow_lifecycle.create(
                [{"role": "user", "content": "background agent input"}],
                request_id="request-background-agent",
                run_id="parent-run",
                checkpoint_thread_id=None,
                workflow_id=parent["id"],
                workflow_name=parent["name"],
            )
            context = WorkflowRuntimeContext.for_run(
                request_id="request-background-agent",
                lifecycle_id=lifecycle_id,
                run_id="parent-run",
                checkpoint_thread_id=None,
                run_depth=0,
                workflow=parent,
                background_runtime=snapshot,
            ).for_workflow_node(
                workflow_node_id="router-launcher",
                invocation_id="launcher-invocation",
            )
            assert context.background_runs is not None
            handle = await context.background_runs.start_agent(
                main_agent["id"],
                operation_id="agent-task-1",
                shared_vars={"input": {"value": 9}},
                workflow_task={
                    "dispatcher_node_id": "dispatcher",
                    "dispatcher_invocation_id": "dispatch-run",
                    "task_id": "agent-task-1",
                    "dispatch_key": "agent",
                    "payload": {"value": 9},
                },
            )
            terminal = None
            for _ in range(200):
                terminal = (
                    await context.background_runs.check([handle.task_id])
                )[0]
                if terminal.runtime_status not in {"pending", "running"}:
                    break
                await asyncio.sleep(0.01)
            run = client.app.state.workflow_lifecycle.history.get_run(
                handle.child_run_id
            )
            events = client.app.state.workflow_lifecycle.events(
                lifecycle_id,
                run_id=handle.child_run_id,
            )
            return handle, terminal, run, events

        handle, terminal, run, events = portal.call(scenario)

    assert handle.target_kind == "agent"
    assert handle.run_depth == 1
    assert terminal is not None
    assert terminal.runtime_status == "succeeded"
    assert run is not None
    assert run["run_kind"] == "agent"
    assert run["status"] == "completed"
    assert run["checkpoint_thread_id"] is None
    assert handle.checkpoint_thread_id is None
    assert {event["subject_kind"] for event in events} >= {"run", "agent", "model"}
    assert captured_context is not None
    assert captured_context.launcher_id == "router-launcher"
    assert captured_context.workflow_node_id == ""
    assert captured_context.agent_id == main_agent["id"]
    assert captured_context.background_task_id == handle.task_id
    assert captured_context.invocation_id == handle.task_id
    assert captured_context.checkpoint_thread_id is None
