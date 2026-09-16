from __future__ import annotations

from agent_shell.runtime.lifecycle_store import (
    build_lifecycle_request_envelope,
    lifecycle_request_messages,
)


def test_lifecycle_request_envelope_preserves_the_complete_request() -> None:
    request = {
        "model": "Researcher",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
        "temperature": 0.7,
        "x_trace": {"id": "trace-1"},
    }
    metadata = {"lifecycle_id": "lifecycle-1", "request_id": "request-1"}

    envelope = build_lifecycle_request_envelope(request, metadata)

    assert envelope == {
        "schema_version": 1,
        "request": {
            "model": "Researcher",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
            "temperature": 0.7,
            "x_trace": {"id": "trace-1"},
        },
        "metadata": {
            "lifecycle_id": "lifecycle-1",
            "request_id": "request-1",
        },
    }

    request["messages"][0]["content"] = "mutated"
    metadata["lifecycle_id"] = "mutated"
    assert envelope["request"]["messages"][0]["content"] == "hello"
    assert envelope["metadata"]["lifecycle_id"] == "lifecycle-1"


def test_lifecycle_request_messages_reads_only_the_envelope_shape() -> None:
    messages = [{"role": "user", "content": "hello"}]

    assert lifecycle_request_messages(
        {"schema_version": 1, "request": {"messages": messages}}
    ) == messages
    assert lifecycle_request_messages({"messages": messages}) is None
    assert lifecycle_request_messages({"request": None}) is None
    assert lifecycle_request_messages(None) is None
