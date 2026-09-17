from __future__ import annotations

import pytest

from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.state import (
    AgentShellState,
    WORKFLOW_STATE_CHANNEL,
    WorkflowState,
    flatten_workflow_state,
    merge_workflow_state,
    wrap_workflow_state_update,
    validate_workflow_state_update,
)


def test_workflow_state_exposes_one_flat_store_channel() -> None:
    assert WorkflowState.__annotations__.keys() == {WORKFLOW_STATE_CHANNEL}
    assert merge_workflow_state({"left": 1}, {"right": 2}) == {
        "left": 1,
        "right": 2,
    }
    assert validate_workflow_state_update(
        {WORKFLOW_STATE_CHANNEL: {"enabled": True}}
    ) == {WORKFLOW_STATE_CHANNEL: {"enabled": True}}
    with pytest.raises(Exception):
        validate_workflow_state_update({WORKFLOW_STATE_CHANNEL: []})


def test_workflow_state_wrap_and_flatten_round_trip() -> None:
    flat = {"topic": "x", "count": 3}
    channel = wrap_workflow_state_update(flat)
    assert channel == {WORKFLOW_STATE_CHANNEL: flat}
    assert flatten_workflow_state(channel) == flat
    assert flatten_workflow_state({}) == {}
    assert flatten_workflow_state({WORKFLOW_STATE_CHANNEL: []}) == {}


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
