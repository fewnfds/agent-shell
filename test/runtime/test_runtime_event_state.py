from __future__ import annotations

from agent_shell.runtime.message_state import MessageRunRegistry
from agent_shell.runtime.tool_state import ToolCallRegistry


def test_message_run_registry_keeps_stream_history_after_active_run_cleanup() -> None:
    registry = MessageRunRegistry()
    registry.begin(
        "model-1",
        message_id="message-1",
        main_agent_ai=True,
        public_ai=True,
    )

    assert registry.was_streamed("model-1")
    assert registry.active_main_runs == frozenset({"model-1"})
    registry.discard("model-1")
    assert registry.get("model-1") is None
    assert registry.was_streamed("model-1")
    assert registry.active_main_runs == frozenset()


def test_tool_call_registry_owns_only_name_correlation() -> None:
    registry = ToolCallRegistry()
    key = ("agent|node", "node:invocation", "call-1")
    registry.remember(key, "read_file")

    assert registry.get(key) == "read_file"
    assert registry.pop(key) == "read_file"
    assert registry.get(key) == ""
    assert registry.pop(key) == ""
