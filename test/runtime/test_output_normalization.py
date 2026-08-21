from __future__ import annotations

from langchain_core.messages import AIMessage

from agent_shell.workflow.events import WorkflowEventSourceV1

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


def test_text_stream_keeps_v3_start_delta_finish_boundaries_without_rewriting() -> None:
    normalizer = V3EventNormalizer("Main Agent")
    envelopes = [
        {
            "method": "values",
            "params": {
                "namespace": [],
                "timestamp": 1,
                "data": {"messages": ["private state"]},
            },
        },
        message_envelope(
            {"event": "message-start", "role": "ai", "id": "message-1"},
            timestamp=1_000,
        ),
        message_envelope(
            {
                "event": "content-block-start",
                "index": 0,
                "content": {"type": "text", "text": ""},
            },
            timestamp=2_000,
        ),
        *[
            message_envelope(
                {
                    "event": "content-block-delta",
                    "index": 0,
                    "delta": {
                        "type": "text-delta",
                        "text": f"partial-{index}",
                    },
                },
                timestamp=3_000 + index,
            )
            for index in range(100)
        ],
        message_envelope(
            {
                "event": "content-block-finish",
                "index": 0,
                "content": {"type": "text", "text": "<complete answer>"},
            },
            timestamp=9_000,
        ),
        message_envelope(
            {
                "event": "message-finish",
                "usage": {
                    "input_tokens": 7,
                    "output_tokens": 3,
                    "total_tokens": 10,
                    "output_token_details": {"reasoning": 2},
                },
            },
            timestamp=10_000,
        ),
    ]

    events = _normalized(normalizer, envelopes)

    assert [(event.event_type, event.phase) for event in events] == [
        ("assistant_text", "start"),
        *[("assistant_text", "delta") for _ in range(100)],
        ("assistant_text", "end"),
    ]
    assert events[0].timestamp == "1970-01-01T00:00:02.000Z"
    assert events[-1].timestamp == "1970-01-01T00:00:09.000Z"
    assert events[-1].message == "<complete answer>"
    assert "partial-0" in repr(events)
    assert "private state" not in repr(events)
    assert normalizer.usage == {
        "input_tokens": 7,
        "output_tokens": 3,
        "total_tokens": 10,
        "reasoning_tokens": 2,
    }
    assert normalizer.main_agent_message_active is False


def test_usage_counts_main_and_subagent_model_runs_once_across_event_shapes() -> None:
    main_agent_id = "11111111-1111-4111-8111-111111111111"
    subagent_id = "22222222-2222-4222-8222-222222222222"
    normalizer = V3EventNormalizer(
        "Main Agent",
        workflow_sources={
            "agent-a": WorkflowEventSourceV1(
                source_type="agent",
                workflow_node_id="agent-a",
                agent_profile_id=main_agent_id,
            )
        },
        main_agent_names=("Main Agent",),
        workflow_agent_names={"agent-a": "Main Agent"},
        workflow_subagent_profile_ids={
            "agent-a": {"Researcher": subagent_id}
        },
    )
    main_usage = {
        "input_tokens": 5,
        "output_tokens": 3,
        "total_tokens": 8,
        "output_token_details": {"reasoning": 1},
    }
    subagent_usage = {
        "input_tokens": 7,
        "output_tokens": 2,
        "total_tokens": 9,
    }

    main_events = normalizer.feed(
        message_envelope(
            AIMessage(content="main", usage_metadata=main_usage),
            run_id="model-main",
            namespace=["agent-a:invocation", "model:model-main"],
        )
    )
    normalizer.feed(
        message_envelope(
            {"event": "message-finish", "usage": main_usage},
            run_id="model-main",
            namespace=["agent-a:invocation", "model:model-main"],
        )
    )
    subagent_events = normalizer.feed(
        message_envelope(
            AIMessage(content="delegated", usage_metadata=subagent_usage),
            run_id="model-subagent",
            agent_name="Researcher",
            namespace=["agent-a:invocation", "task:call-1", "model:model-subagent"],
        )
    )
    normalizer.feed(
        message_envelope(
            {"event": "message-finish", "usage": subagent_usage},
            run_id="model-subagent",
            agent_name="Researcher",
            namespace=["agent-a:invocation", "task:call-1", "model:model-subagent"],
        )
    )

    assert any(isinstance(event, OutputEvent) for event in main_events)
    assert subagent_events == []
    assert normalizer.usage == {
        "input_tokens": 12,
        "output_tokens": 5,
        "total_tokens": 17,
        "reasoning_tokens": 1,
    }


def test_usage_applies_only_growth_from_later_run_snapshot() -> None:
    normalizer = V3EventNormalizer("Main Agent")
    normalizer.feed(
        message_envelope(
            {
                "event": "message-finish",
                "usage": {
                    "input_tokens": 2,
                    "output_tokens": 1,
                    "total_tokens": 3,
                },
            },
            run_id="model-main",
        )
    )
    normalizer.feed(
        message_envelope(
            {
                "event": "message-finish",
                "usage": {
                    "input_tokens": 4,
                    "output_tokens": 2,
                    "total_tokens": 6,
                },
            },
            run_id="model-main",
        )
    )

    assert normalizer.usage == {
        "input_tokens": 4,
        "output_tokens": 2,
        "total_tokens": 6,
    }


def test_complete_blocks_and_atomic_events_keep_v3_arrival_order() -> None:
    normalizer = V3EventNormalizer("Main Agent")
    envelopes = [
        message_envelope(
            {"event": "message-start", "role": "ai", "id": "message-1"}
        ),
        message_envelope(
            {
                "event": "content-block-start",
                "index": 0,
                "content": {"type": "reasoning", "reasoning": ""},
            }
        ),
        message_envelope(
            {
                "event": "content-block-delta",
                "index": 0,
                "delta": {"type": "reasoning-delta", "reasoning": "draft"},
            }
        ),
        message_envelope(
            {
                "event": "content-block-finish",
                "index": 0,
                "content": {"type": "reasoning", "reasoning": "final thought"},
            }
        ),
        {
            "method": "custom:progress",
            "params": {
                "namespace": [],
                "timestamp": 2,
                "data": {"status": "ready"},
            },
        },
        message_envelope(
            {
                "event": "content-block-finish",
                "index": 1,
                "content": {"type": "text", "text": "final answer"},
            }
        ),
        message_envelope(
            {
                "event": "content-block-start",
                "index": 2,
                "content": {
                    "type": "tool_call",
                    "id": "call-1",
                    "name": "read_file",
                    "args": {},
                },
            }
        ),
        message_envelope(
            {
                "event": "content-block-finish",
                "index": 2,
                "content": {
                    "type": "tool_call",
                    "id": "call-1",
                    "name": "read_file",
                    "args": {"path": "README.md"},
                },
            }
        ),
        message_envelope({"event": "message-finish", "usage": {}}),
    ]

    events = _normalized(normalizer, envelopes)

    assert [(event.event_type, event.phase) for event in events] == [
        ("reasoning", "start"),
        ("reasoning", "delta"),
        ("reasoning", "end"),
        ("custom", "end"),
        ("assistant_text", "end"),
        ("tool_call", "start"),
        ("tool_call", "end"),
    ]
    assert [event.message for event in events] == [
        "",
        "draft",
        "final thought",
        '{"status":"ready"}',
        "final answer",
        "{}",
        '{"path":"README.md"}',
    ]
    assert events[3].values == {
        "channel": "progress",
        "data_json": '{"status":"ready"}',
    }
    assert events[6].values["arguments"] == '{"path":"README.md"}'


def test_projector_uses_event_scripts_without_a_separate_filter_layer() -> None:
    tool_result = OutputEvent(
        event_type="tool_result",
        phase="end",
        sequence=1,
        timestamp="2026-01-01T00:00:00Z",
        agent_name="Main Agent",
        node="tools",
        message="<unsafe>",
        values={"tool_name": "commit", "status": "completed"},
    )
    tool_call = OutputEvent(
        event_type="tool_call",
        phase="end",
        sequence=2,
        timestamp="2026-01-01T00:00:01Z",
        agent_name="Main Agent",
        node="tools",
        message="call",
        values={"tool_name": "commit"},
    )

    projector = OutputProjector(output_renderer({
        "tool_result": "{{message}}",
        "tool_call": "{{message}}",
    }))

    assert projector.render(tool_result) == "<unsafe>"
    assert projector.render(tool_call) == "call"
