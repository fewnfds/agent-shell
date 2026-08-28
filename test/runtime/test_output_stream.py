from __future__ import annotations

from .support import *


def _normalized(
    normalizer: V3EventNormalizer, envelopes: list[dict]
) -> list[OutputEvent]:
    return [
        event
        for envelope in envelopes
        for event in normalizer.feed(envelope)
        if isinstance(event, OutputEvent)
    ]


def test_message_finish_records_the_call_without_fabricating_a_public_block_end() -> None:
    responses = []
    normalizer = V3EventNormalizer(
        "Main Agent", model_response_observers=(responses.append,)
    )
    normalizer.feed(
        message_envelope(
            {"event": "message-start", "role": "ai", "id": "message-1"}
        )
    )
    normalizer.feed(
        message_envelope(
            {
                "event": "content-block-start",
                "index": 0,
                "content": {"type": "text", "text": ""},
            }
        )
    )
    normalizer.feed(
        message_envelope(
            {
                "event": "content-block-delta",
                "index": 0,
                "delta": {"type": "text-delta", "text": "partial"},
            }
        )
    )

    events = normalizer.feed(
        message_envelope(
            {
                "event": "message-finish",
                "usage": {},
                "metadata": {"finish_reason": "stop"},
            }
        )
    )

    assert len(events) == 1
    assert isinstance(events[0], ModelCallBoundary)
    assert events[0].phase == "end"
    assert responses[0].stream_diagnostics["incomplete_block_count"] == 1
    assert normalizer.main_agent_message_active is False


def test_graph_end_discards_open_normalizer_state_without_fabricating_finish() -> None:
    normalizer = V3EventNormalizer("Main Agent")
    normalizer.feed(
        message_envelope(
            {"event": "message-start", "role": "ai", "id": "message-1"}
        )
    )
    normalizer.feed(
        message_envelope(
            {
                "event": "content-block-start",
                "index": 0,
                "content": {"type": "reasoning", "reasoning": ""},
            }
        )
    )
    normalizer.feed(
        message_envelope(
            {
                "event": "content-block-delta",
                "index": 0,
                "delta": {"type": "reasoning-delta", "reasoning": "partial"},
            }
        )
    )

    normalizer.close_main_agent_messages()
    assert normalizer.finish_reason == "unknown"
    assert normalizer.main_agent_message_active is False


def test_message_error_fails_immediately_without_exposing_upstream_payload() -> None:
    normalizer = V3EventNormalizer("Main Agent")
    normalizer.feed(
        message_envelope(
            {"event": "message-start", "role": "ai", "id": "message-1"}
        )
    )

    with pytest.raises(AgentRuntimeError) as captured:
        normalizer.feed(
            message_envelope(
                {"event": "error", "error": {"provider_body": "private"}}
            )
        )

    assert captured.value.code == "agent_execution_failed"
    assert "private" not in str(captured.value)
    assert normalizer.main_agent_message_active is False


def test_tool_finish_and_failure_are_complete_and_tool_delta_is_activity_only() -> None:
    normalizer = V3EventNormalizer("Main Agent")
    normalizer.feed(
        message_envelope(
            {
                "event": "content-block-finish",
                "index": 0,
                "content": {
                    "type": "tool_call",
                    "id": "call-1",
                    "name": "read_file",
                    "args": {"path": "README.md"},
                },
            }
        )
    )
    delta = normalizer.feed(
        {
            "method": "tools",
            "params": {
                "namespace": [],
                "timestamp": 2,
                "data": {
                    "event": "tool-output-delta",
                    "tool_call_id": "call-1",
                    "output": "partial secret",
                },
            },
        }
    )
    finished = normalizer.feed(
        {
            "method": "tools",
            "params": {
                "namespace": [],
                "timestamp": 3,
                "data": {
                    "event": "tool-finished",
                    "tool_call_id": "call-1",
                    "output": "complete result",
                },
            },
        }
    )
    failed = normalizer.feed(
        {
            "method": "tools",
            "params": {
                "namespace": [],
                "timestamp": 4,
                "data": {
                    "event": "tool-failed",
                    "tool_call_id": "call-2",
                    "tool_name": "write_file",
                    "output": {"traceback": "private"},
                },
            },
        }
    )

    assert len(delta) == 1
    assert (delta[0].event_type, delta[0].phase) == ("tool_progress", "delta")
    assert delta[0].message == ""
    assert "partial secret" not in repr(delta[0])
    assert [(event.event_type, event.phase) for event in [*finished, *failed]] == [
        ("tool_result", "end"),
        ("tool_error", "error"),
    ]
    assert finished[0].message == "complete result"
    assert finished[0].values["tool_name"] == "read_file"
    assert failed[0].message == "Tool execution failed."
    assert "private" not in repr(failed)


def test_command_tool_result_uses_only_the_matching_tool_message() -> None:
    normalizer = V3EventNormalizer("Main Agent")
    command = Command(
        update={
            "messages": [
                ToolMessage(content="wrong", tool_call_id="call-other"),
                ToolMessage(
                    content="final result",
                    tool_call_id="call-1",
                    name="task",
                ),
            ]
        }
    )

    events = normalizer.feed(
        {
            "method": "tools",
            "params": {
                "namespace": [],
                "timestamp": 1,
                "data": {
                    "event": "tool-finished",
                    "tool_call_id": "call-1",
                    "output": command,
                },
            },
        }
    )

    assert len(events) == 1
    assert events[0].message == "final result"
    assert events[0].values["tool_name"] == "task"
    assert "wrong" not in repr(events)


def test_subagent_model_content_stays_private_but_lifecycle_is_available() -> None:
    normalizer = V3EventNormalizer("Main Agent")
    internal_messages = [
        message_envelope(
            {"event": "message-start", "role": "ai", "id": "sub-message"},
            run_id="run-subagent",
            agent_name="Researcher",
            namespace=["task:research"],
        ),
        message_envelope(
            {
                "event": "content-block-start",
                "index": 0,
                "content": {"type": "text", "text": ""},
            },
            run_id="run-subagent",
            agent_name="Researcher",
            namespace=["task:research"],
        ),
        message_envelope(
            {
                "event": "content-block-delta",
                "index": 0,
                "delta": {"type": "text-delta", "text": "private draft"},
            },
            run_id="run-subagent",
            agent_name="Researcher",
            namespace=["task:research"],
        ),
        message_envelope(
            {
                "event": "content-block-finish",
                "index": 0,
                "content": {"type": "text", "text": "private answer"},
            },
            run_id="run-subagent",
            agent_name="Researcher",
            namespace=["task:research"],
        ),
        message_envelope(
            {
                "event": "content-block-finish",
                "index": 1,
                "content": {
                    "type": "image",
                    "base64": "cHJpdmF0ZQ==",
                    "mime_type": "image/png",
                },
            },
            run_id="run-subagent",
            agent_name="Researcher",
            namespace=["task:research"],
        ),
        message_envelope(
            {"event": "message-finish", "usage": {}},
            run_id="run-subagent",
            agent_name="Researcher",
            namespace=["task:research"],
        ),
    ]
    lifecycle = [
        {
            "method": "lifecycle",
            "params": {
                "timestamp": 2,
                "data": {
                    "event": "started",
                    "namespace": ["task:research"],
                    "graph_name": "Researcher",
                    "cause": {"tool_call_id": "call-task"},
                },
            },
        },
        {
            "method": "lifecycle",
            "params": {
                "timestamp": 3,
                "data": {
                    "event": "completed",
                    "namespace": ["task:research"],
                },
            },
        },
    ]

    assert _normalized(normalizer, internal_messages) == []
    events = _normalized(normalizer, lifecycle)
    assert [(event.event_type, event.phase) for event in events] == [
        ("subagent", "start"),
        ("subagent", "end"),
    ]
    assert all(event.values["subagent_name"] == "Researcher" for event in events)
    assert "private" not in repr(events)


def test_unknown_internal_and_unsupported_media_events_are_not_public() -> None:
    normalizer = V3EventNormalizer("Main Agent")
    internal = normalizer.feed(
        {
            "method": "updates",
            "params": {"namespace": [], "data": {"secret": "private-state"}},
        }
    )
    unknown = normalizer.feed(
        {
            "method": "future-public-event",
            "params": {"namespace": [], "data": {"secret": "private-event"}},
        }
    )
    media = _normalized(
        normalizer,
        [
            message_envelope(
                {"event": "message-start", "role": "ai", "id": "message-media"}
            ),
            message_envelope(
                {
                    "event": "content-block-start",
                    "index": 0,
                    "content": {"type": "image"},
                }
            ),
            message_envelope(
                {
                    "event": "content-block-finish",
                    "index": 0,
                    "content": {
                        "type": "image",
                        "url": "https://secret.invalid/image.png",
                        "base64": "private-media",
                    },
                }
            ),
            message_envelope({"event": "message-finish", "usage": {}}),
        ],
    )

    assert internal == []
    assert unknown == []
    assert media == []
