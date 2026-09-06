from __future__ import annotations

import pytest

from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.state import (
    AgentShellState,
    WorkflowState,
    merge_shared_vars,
    validate_workflow_state_update,
)


def test_workflow_state_has_one_control_channel_with_a_patch_reducer() -> None:
    assert WorkflowState.__annotations__.keys() == {"shared_vars"}
    assert merge_shared_vars({"left": 1}, {"right": 2}) == {
        "left": 1,
        "right": 2,
    }
    assert validate_workflow_state_update(
        {"shared_vars": {"enabled": True}}
    ) == {"shared_vars": {"enabled": True}}
    with pytest.raises(Exception):
        validate_workflow_state_update({"shared_vars": []})


def test_agent_state_has_no_workflow_bridge_channels() -> None:
    removed = {
        "shared_vars",
        "workflow_task",
        "workflow_state_snapshot",
        "agent_invocations",
    }
    assert removed.isdisjoint(AgentShellState.__annotations__)


def test_workflow_runtime_context_has_only_command_node_scope() -> None:
    fields = set(WorkflowRuntimeContext.__dataclass_fields__)
    assert "workflow_node_id" in fields
    assert "node_invocation_id" in fields
    assert "agent_profile_id" not in fields
