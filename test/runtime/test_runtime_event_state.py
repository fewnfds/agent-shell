from __future__ import annotations

from agent_shell.runtime.message_state import MessageRunRegistry


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
