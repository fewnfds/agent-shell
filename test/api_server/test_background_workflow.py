from __future__ import annotations

import asyncio

from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.run_identity import WorkflowRunIdentity
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
                "cancel_on_upstream_termination": False,
                "workflow_event_output_id": None,
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
        coordinator = client.app.state.agent_runtime.create_lifecycle_coordinator(
            snapshot
        )
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
                identity=WorkflowRunIdentity(
                    request_id="request-background",
                    lifecycle_id=lifecycle_id,
                    workflow_run_id="parent-run",
                    workflow_id="parent-workflow",
                    workflow_name="Parent Workflow",
                    checkpoint_thread_id=(
                        "parent-thread" if parent_checkpointer_enabled else None
                    ),
                ),
                background_runtime=coordinator,
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
    assert handle.cancel_on_upstream_termination is False
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


def test_child_agent_and_workflow_events_join_the_parent_lifecycle_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        child = create_workflow(
            client,
            name="Output Child",
            workflow_role="child",
        )
        child_output = client.post(
            "/api/blocks/workflow-event-output",
            json=workflow_event_output_payload(
                client,
                "Child workflow output",
                source=(
                    "def output(event, origin):\n"
                    "    return ''\n"
                    "\n"
                    "def run_output(event, origin):\n"
                    "    if event.get('type') == 'agent_shell.workflow_run':\n"
                    "        return f\"<child-workflow>{event['phase']}\" + '</child-workflow>'\n"
                    "    return ''\n"
                ),
            ),
        )
        assert child_output.status_code == 200, child_output.text
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
                        "cancel_on_upstream_termination",
                    )
                },
                "workflow_event_output_id": child_output.json()["id"],
                "checkpointer_id": None,
            },
        )
        assert child_response.status_code == 200, child_response.text
        child = child_response.json()
        save_linear_workflow_graph(client, child, main_agent)
        parent = create_workflow(client, name="Output Parent")
        save_linear_workflow_graph(client, parent, main_agent)
        snapshot = client.app.state.agent_runtime.capture()
        coordinator = client.app.state.agent_runtime.create_lifecycle_coordinator(
            snapshot
        )
        portal = client.portal
        assert portal is not None

        async def scenario() -> tuple[str, str]:
            parent_execution = await coordinator.start_parent_workflow(
                parent,
                [{"role": "user", "content": "run parent and child"}],
                request_id="shared-output-request",
                public_model=parent["name"],
            )
            assert parent_execution.context is not None
            context = parent_execution.context
            assert context.background_runs is not None
            handle = await context.background_runs.start_workflow(
                child["id"],
                operation_id="child-output",
                shared_vars={},
            )
            terminal = None
            for _ in range(200):
                terminal = (
                    await context.background_runs.check([handle.task_id])
                )[0]
                if terminal.runtime_status not in {"pending", "running"}:
                    break
                await asyncio.sleep(0.01)
            content, _usage = await parent_execution.run()
            return terminal.runtime_status if terminal is not None else "", content

        status, content = portal.call(scenario)

    assert status == "succeeded"
    assert "<child-workflow>start</child-workflow>" in content
    assert "<child-workflow>end</child-workflow>" in content
    assert content.count("runtime reply") == 2
