from __future__ import annotations

from agent_shell.runtime.state import (
    AgentShellState,
    WorkflowState,
    merge_agent_invocations,
    merge_shared_vars,
)
from agent_shell.runtime.context import WorkflowRuntimeContext


def test_shared_vars_reducer_merges_independent_patches() -> None:
    assert merge_shared_vars(
        {"research": {"status": "ready"}},
        {"report": {"path": "/report.md"}},
    ) == {
        "research": {"status": "ready"},
        "report": {"path": "/report.md"},
    }


def test_agent_shell_state_exposes_shared_vars_as_public_graph_state() -> None:
    assert "shared_vars" in AgentShellState.__annotations__
    assert "workflow_state_snapshot" in AgentShellState.__annotations__
    assert "background_tasks" not in WorkflowState.__annotations__


def test_runtime_context_keeps_run_identity_and_commands_out_of_graph_state() -> None:
    fields = WorkflowRuntimeContext.__dataclass_fields__

    assert {
        "lifecycle_id",
        "request_id",
        "run_id",
        "workflow_id",
        "workflow_node_id",
        "agent_profile_id",
        "node_invocation_id",
        "caller_run_id",
        "operation_id",
        "workflow_runs",
    } <= fields.keys()
    assert "checkpoint_thread_id" not in fields
    assert "parent_workflow_run_id" not in fields
    assert "background_task_id" not in fields
    assert "launcher_id" not in fields
    assert "run_depth" not in fields
    assert "workflow_name" not in fields
    assert "workflow_role" not in fields
    assert "workflow" not in fields
    assert "messages" not in fields
    assert "messages_sha" not in fields
    assert "workflow_state" not in fields


def test_agent_invocation_reducer_merges_independent_invocation_ids() -> None:
    first = {"first": {"invocation_id": "first"}}
    second = {"second": {"invocation_id": "second"}}

    assert merge_agent_invocations(first, second) == {**first, **second}


def test_agent_invocation_reducer_replaces_the_same_logical_slots() -> None:
    current = {
        "old-node": {
            "invocation_id": "old-node",
            "workflow_node_id": "agent-1",
        },
        "old-task": {
            "invocation_id": "old-task",
            "workflow_node_id": "worker",
            "workflow_task": {
                "command_node_id": "command-1",
                "command_invocation_id": "command-old",
                "task_id": "task-1",
                "dispatch_key": "work",
            },
        },
    }
    update = {
        "new-node": {
            "invocation_id": "new-node",
            "workflow_node_id": "agent-1",
        },
        "new-task": {
            "invocation_id": "new-task",
            "workflow_node_id": "worker",
            "workflow_task": {
                "command_node_id": "command-1",
                "command_invocation_id": "command-new",
                "task_id": "task-1",
                "dispatch_key": "work",
            },
        },
    }

    assert merge_agent_invocations(current, update) == update
