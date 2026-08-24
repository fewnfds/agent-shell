from __future__ import annotations

from agent_shell.runtime.state import (
    AgentShellState,
    WorkflowState,
    merge_background_tasks,
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
    assert "background_tasks" in WorkflowState.__annotations__


def test_runtime_context_keeps_identity_without_lifecycle_or_parent_state_payloads() -> None:
    fields = WorkflowRuntimeContext.__dataclass_fields__

    assert {"lifecycle_id", "run_id", "checkpoint_thread_id"} <= fields.keys()
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
                "dispatcher_node_id": "dispatcher-1",
                "dispatcher_invocation_id": "dispatch-old",
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
                "dispatcher_node_id": "dispatcher-1",
                "dispatcher_invocation_id": "dispatch-new",
                "task_id": "task-1",
                "dispatch_key": "work",
            },
        },
    }

    assert merge_agent_invocations(current, update) == update


def test_background_task_reducer_replaces_each_task_with_latest_check() -> None:
    assert merge_background_tasks(
        {"task-1": {"runtime_status": "running"}},
        {
            "task-1": {"runtime_status": "succeeded"},
            "task-2": {"runtime_status": "failed"},
        },
    ) == {
        "task-1": {"runtime_status": "succeeded"},
        "task-2": {"runtime_status": "failed"},
    }
