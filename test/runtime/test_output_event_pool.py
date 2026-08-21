from __future__ import annotations

from langchain_core.messages import AIMessage

from agent_shell.runtime.output_projection import WorkflowOutputProjector

from .support import *


def _event(
    event_type: str,
    phase: str,
    *,
    sequence: int,
    stream_id: str = "",
    message: str = "",
    **values: str,
) -> OutputEvent:
    return OutputEvent(
        event_type=event_type,
        phase=phase,
        sequence=sequence,
        timestamp="2026-08-01T00:00:00Z",
        agent_name="Main Agent",
        node="model",
        message=message,
        values=values,
        stream_id=stream_id,
    )


def _rectifier() -> OutputEventRectifier:
    output = output_renderer({
        "reasoning": "<reasoning>{{message}}</reasoning>",
        "assistant_text": "<text>{{message}}</text>",
        "tool_call": "<call id={{tool_call_id}}>{{message}}</call>",
        "tool_result": "<result id={{tool_call_id}}>{{message}}</result>",
    })
    return OutputEventRectifier(OutputProjector(output))


def test_competing_streams_render_once_on_complete_blocks_in_source_order() -> None:
    pool = _rectifier()

    assert pool.feed(
        _event("reasoning", "start", sequence=1, stream_id="run:0")
    ) == []
    assert pool.feed(
        _event(
            "reasoning",
            "delta",
            sequence=2,
            stream_id="run:0",
            message="think",
        )
    ) == []
    assert pool.feed(
        _event("assistant_text", "start", sequence=3, stream_id="run:1")
    ) == []
    assert pool.feed(
        _event(
            "assistant_text",
            "delta",
            sequence=4,
            stream_id="run:1",
            message="answer",
        )
    ) == []
    assert pool.feed(
        _event(
            "reasoning",
            "end",
            sequence=5,
            stream_id="run:0",
            message="think",
        )
    ) == ["<reasoning>think</reasoning>"]
    assert pool.feed(
        _event(
            "assistant_text",
            "end",
            sequence=6,
            stream_id="run:1",
            message="answer",
        )
    ) == ["<text>answer</text>"]
    assert pool.flush() == []


def test_tool_call_waits_for_an_outcome_within_the_current_cycle() -> None:
    pool = _rectifier()
    pool.feed(_event("reasoning", "start", sequence=1, stream_id="run:0"))
    pool.feed(
        _event(
            "tool_call",
            "end",
            sequence=2,
            message='{"path":"README.md"}',
            tool_call_id="call-1",
            tool_name="read_file",
        )
    )
    assert pool.feed(
        _event(
            "tool_result",
            "end",
            sequence=3,
            message="done",
            tool_call_id="call-1",
            tool_name="read_file",
        )
    ) == [
        '<call id=call-1>{"path":"README.md"}</call>',
        "<result id=call-1>done</result>",
    ]
    assert pool.flush() == []

    pool = _rectifier()
    assert pool.feed(
        _event(
            "tool_call",
            "end",
            sequence=1,
            message="args",
            tool_call_id="call-missing",
        )
    ) == []
    assert pool.flush() == ["<call id=call-missing>args</call>"]

    pool = _rectifier()
    pool.feed(_event("reasoning", "start", sequence=1, stream_id="run:0"))
    parts: list[str] = []
    for sequence, event_type, call_id, message in (
        (2, "tool_call", "call-a", "args-a"),
        (3, "tool_call", "call-b", "args-b"),
        (4, "tool_result", "call-b", "result-b"),
        (5, "tool_result", "call-a", "result-a"),
    ):
        parts.extend(pool.feed(
            _event(
                event_type,
                "end",
                sequence=sequence,
                message=message,
                tool_call_id=call_id,
                tool_name="same_tool",
            )
        ))

    parts.extend(pool.flush())
    assert parts == [
        "<call id=call-a>args-a</call>",
        "<result id=call-a>result-a</result>",
        "<call id=call-b>args-b</call>",
        "<result id=call-b>result-b</result>",
    ]

    pool = _rectifier()
    for sequence, event_type, call_id, message in (
        (1, "tool_call", "call-a", "args-a"),
        (2, "tool_call", "call-b", "args-b"),
        (3, "tool_result", "call-b", "result-b"),
    ):
        assert pool.feed(
            _event(
                event_type,
                "end",
                sequence=sequence,
                message=message,
                tool_call_id=call_id,
                tool_name="same_tool",
            )
        ) == []
    assert pool.feed(
        _event(
            "tool_result",
            "end",
            sequence=4,
            message="result-a",
            tool_call_id="call-a",
            tool_name="same_tool",
        )
    ) == [
        "<call id=call-a>args-a</call>",
        "<result id=call-a>result-a</result>",
        "<call id=call-b>args-b</call>",
        "<result id=call-b>result-b</result>",
    ]


def test_tool_pairing_isolated_by_workflow_source_for_reused_call_ids() -> None:
    output_a = output_renderer({
        "tool_call": "A-call:{{message}}",
        "tool_result": "A-result:{{message}}",
    })
    output_b = output_renderer({
        "tool_call": "B-call:{{message}}",
        "tool_result": "B-result:{{message}}",
    })
    pool = OutputEventRectifier(
        WorkflowOutputProjector({"node-a": output_a, "node-b": output_b})
    )

    def event(node_id: str, event_type: str, message: str, sequence: int) -> OutputEvent:
        return OutputEvent(
            event_type=event_type,
            phase="end",
            sequence=sequence,
            timestamp="2026-08-01T00:00:00Z",
            namespace=f"{node_id}:invocation",
            workflow_node_id=node_id,
            agent_profile_id=node_id,
            message=message,
            values={"tool_call_id": "reused-call-id"},
        )

    assert pool.feed(event("node-a", "tool_call", "a-args", 1)) == []
    assert pool.feed(event("node-b", "tool_call", "b-args", 2)) == []
    assert pool.feed(event("node-b", "tool_result", "b-result", 3)) == []
    assert pool.feed(event("node-a", "tool_result", "a-result", 4)) == [
        "A-call:a-args",
        "A-result:a-result",
        "B-call:b-args",
        "B-result:b-result",
    ]


def test_complete_streams_are_isolated_by_workflow_source() -> None:
    output_a = output_renderer({"assistant_text": "<A>{{message}}</A>"})
    output_b = output_renderer({"assistant_text": "<B>{{message}}</B>"})
    pool = OutputEventRectifier(
        WorkflowOutputProjector({"node-a": output_a, "node-b": output_b})
    )

    def event(node_id: str, phase: str, message: str = "") -> OutputEvent:
        return OutputEvent(
            event_type="assistant_text",
            phase=phase,
            sequence=1,
            timestamp="2026-08-01T00:00:00Z",
            namespace=f"{node_id}:invocation",
            workflow_node_id=node_id,
            agent_profile_id=node_id,
            message=message,
            # Synthetic collision proves stream bookkeeping is source-scoped.
            stream_id="shared-run:0",
        )

    assert pool.feed(event("node-a", "start")) == []
    assert pool.feed(event("node-a", "delta", "a1")) == []
    assert pool.feed(event("node-b", "start")) == []
    assert pool.feed(event("node-b", "delta", "b1")) == []
    assert pool.feed(event("node-a", "delta", "a2")) == []
    assert pool.feed(event("node-a", "end", "a1a2")) == [
        "<A>a1a2</A>"
    ]
    assert pool.feed(event("node-b", "end", "b1")) == ["<B>b1</B>"]


def test_pure_tool_output_does_not_require_reasoning_or_text() -> None:
    output = output_renderer({
        "tool_call": "CALL={{message}}",
        "tool_result": "RESULT={{message}}",
    })
    pool = OutputEventRectifier(OutputProjector(output))

    assert pool.feed(
        _event(
            "tool_call",
            "end",
            sequence=1,
            message="arguments",
            tool_call_id="call-1",
        )
    ) == []
    assert pool.feed(
        _event(
            "tool_result",
            "end",
            sequence=2,
            message="output",
            tool_call_id="call-1",
        )
    ) == ["CALL=arguments", "RESULT=output"]


def test_non_streaming_model_messages_use_the_same_tool_pairing_cycle() -> None:
    async def scenario() -> list[str]:
        output = output_renderer({
            "assistant_text": "{{message}}",
            "tool_call": "<call id={{tool_call_id}}>{{message}}</call>",
            "tool_result": "<result id={{tool_call_id}}>{{message}}</result>",
        })
        first_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "echo",
                    "args": {"value": "one"},
                    "id": "call-a",
                    "type": "tool_call",
                },
                {
                    "name": "echo",
                    "args": {"value": "two"},
                    "id": "call-b",
                    "type": "tool_call",
                },
                {
                    "name": "echo",
                    "args": {"value": "missing"},
                    "id": "call-missing",
                    "type": "tool_call",
                },
            ],
        )
        events = [
            message_envelope(first_response, run_id="nonstream-1"),
            {
                "method": "tools",
                "params": {
                    "namespace": [],
                    "timestamp": 2,
                    "data": {
                        "event": "tool-finished",
                        "tool_call_id": "call-b",
                        "output": "two",
                    },
                },
            },
            {
                "method": "tools",
                "params": {
                    "namespace": [],
                    "timestamp": 3,
                    "data": {
                        "event": "tool-finished",
                        "tool_call_id": "call-a",
                        "output": "one",
                    },
                },
            },
            message_envelope(
                AIMessage(content="done"), run_id="nonstream-2", timestamp=4
            ),
        ]
        execution = RunExecution(
            graph=EventGraph(events),
            input_state={"messages": []},
            rectifier=OutputEventRectifier(OutputProjector(output)),
            normalizer=V3EventNormalizer("Main Agent"),
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
        )
        return [part async for part in execution.stream_text()]

    assert asyncio.run(scenario()) == [
        '<call id=call-a>{"value":"one"}</call>',
        "<result id=call-a>one</result>",
        '<call id=call-b>{"value":"two"}</call>',
        "<result id=call-b>two</result>",
        '<call id=call-missing>{"value":"missing"}</call>',
        "done",
    ]


def test_next_model_start_drains_compat_bridge_order_before_the_new_call() -> None:
    async def scenario() -> list[str]:
        output = output_renderer({
            "reasoning": "<reasoning>{{message}}</reasoning>",
            "assistant_text": "<text>{{message}}</text>",
            "tool_call": "<call>{{message}}</call>",
            "tool_result": "<result>{{message}}</result>",
        })
        events = [
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
                    "delta": {"type": "reasoning-delta", "reasoning": "think"},
                }
            ),
            message_envelope(
                {
                    "event": "content-block-start",
                    "index": 1,
                    "content": {"type": "text", "text": ""},
                }
            ),
            message_envelope(
                {
                    "event": "content-block-delta",
                    "index": 1,
                    "delta": {"type": "text-delta", "text": "answer"},
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
                    "index": 0,
                    "content": {"type": "reasoning", "reasoning": "think"},
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
            message_envelope(
                {
                    "event": "content-block-finish",
                    "index": 1,
                    "content": {"type": "text", "text": "answer"},
                }
            ),
            message_envelope(
                {
                    "event": "message-finish",
                    "usage": {},
                    "metadata": {"finish_reason": "stop"},
                }
            ),
            {
                "method": "tools",
                "params": {
                    "namespace": [],
                    "timestamp": 2,
                    "data": {
                        "event": "tool-finished",
                        "tool_call_id": "call-1",
                        "output": "file contents",
                    },
                },
            },
            message_envelope(
                {"event": "message-start", "role": "ai", "id": "message-2"},
                run_id="run-next",
            ),
            message_envelope(
                {"event": "message-finish", "usage": {}}, run_id="run-next"
            ),
        ]
        execution = RunExecution(
            graph=EventGraph(events),
            input_state={"messages": []},
            rectifier=OutputEventRectifier(OutputProjector(output)),
            normalizer=V3EventNormalizer("Main Agent"),
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
        )
        return [part async for part in execution.stream_text()]

    assert asyncio.run(scenario()) == [
        "<reasoning>think</reasoning>",
        "<text>answer</text>",
        '<call>{"path":"README.md"}</call>',
        "<result>file contents</result>",
    ]
