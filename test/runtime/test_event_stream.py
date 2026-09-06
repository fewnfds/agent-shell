from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.event_origin import RunEventOriginResolver
from agent_shell.runtime.event_stream import RunEventStream
from agent_shell.runtime.usage import RunUsageAccumulator

from .support import message_envelope


def _stream() -> tuple[RunEventStream, RunUsageAccumulator, RunEventOriginResolver]:
    usage = RunUsageAccumulator()
    resolver = RunEventOriginResolver(
        None,
        main_agent_names=("Main Agent",),
        root_agent_profile_id="agent-1",
        root_subagent_profile_ids={"Researcher": "subagent-1"},
    )
    return RunEventStream(usage), usage, resolver


def _consume(
    stream: RunEventStream,
    resolver: RunEventOriginResolver,
    event: dict,
    text: str = "",
    *,
    segment_end_text: str = "",
):
    return stream.consume(
        event,
        resolver.resolve(event),
        text=text,
        segment_end_text=segment_end_text,
    )


def test_streamed_text_uses_official_start_delta_finish_boundaries() -> None:
    stream, usage, resolver = _stream()
    _consume(
        stream,
        resolver,
        message_envelope({"event": "message-start", "role": "ai", "id": "m1"}),
    )
    started = _consume(
        stream,
        resolver,
        message_envelope({
            "event": "content-block-start",
            "index": 0,
            "content": {"type": "text", "text": ""},
        }),
        "<answer>",
        segment_end_text="</answer>",
    )
    delta = _consume(
        stream,
        resolver,
        message_envelope({
            "event": "content-block-delta",
            "index": 0,
            "delta": {"type": "text-delta", "text": "hello"},
        }),
        "hello",
    )
    finished = _consume(
        stream,
        resolver,
        message_envelope({
            "event": "content-block-finish",
            "index": 0,
            "content": {"type": "text", "text": "hello"},
        }),
    )
    message_finished = _consume(
        stream,
        resolver,
        message_envelope({
            "event": "message-finish",
            "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        }),
    )

    frames = [*started.frames, *delta.frames, *finished.frames]
    assert [frame.phase for frame in frames] == ["start", "delta", "finish"]
    assert [frame.text for frame in frames] == ["<answer>", "hello", "</answer>"]
    assert message_finished.frames == ()
    assert usage.snapshot == {
        "input_tokens": 2,
        "output_tokens": 1,
        "total_tokens": 3,
    }


def test_non_streaming_text_and_tool_output_are_atomic_on_arrival() -> None:
    stream, _usage, resolver = _stream()
    text = _consume(
        stream,
        resolver,
        message_envelope({
            "event": "content-block-finish",
            "index": 0,
            "content": {"type": "text", "text": "whole"},
        }),
        "whole",
    )
    tool = {
        "method": "tools",
        "params": {
            "namespace": ["tools:call"],
            "data": {"event": "tool-finished", "tool_call_id": "call-1"},
        },
    }
    tool_projection = _consume(stream, resolver, tool, "tool complete")

    assert [(frame.phase, frame.text) for frame in text.frames] == [
        ("atomic", "whole")
    ]
    assert [(frame.phase, frame.text) for frame in tool_projection.frames] == [
        ("atomic", "tool complete")
    ]


def test_whole_ai_message_after_streamed_message_is_not_projected_twice() -> None:
    stream, _usage, resolver = _stream()
    run_id = "model-run"
    _consume(
        stream,
        resolver,
        message_envelope(
            {"event": "message-start", "role": "ai", "id": "m1"},
            run_id=run_id,
        ),
    )
    _consume(
        stream,
        resolver,
        message_envelope({"event": "message-finish", "usage": {}}, run_id=run_id),
    )

    projection = _consume(
        stream,
        resolver,
        message_envelope(AIMessage(content="duplicate"), run_id=run_id),
        "duplicate",
    )

    assert projection.frames == ()


def test_main_agent_message_error_is_redacted_and_fails_immediately() -> None:
    stream, _usage, resolver = _stream()
    _consume(
        stream,
        resolver,
        message_envelope({"event": "message-start", "role": "ai", "id": "m1"}),
    )

    with pytest.raises(AgentRuntimeError) as captured:
        _consume(
            stream,
            resolver,
            message_envelope({"event": "error", "error": {"private": "secret"}}),
        )

    assert captured.value.code == "agent_execution_failed"
    assert "secret" not in str(captured.value)


def test_completed_media_is_returned_separately_from_atomic_event_text() -> None:
    stream, _usage, resolver = _stream()
    projection = _consume(
        stream,
        resolver,
        message_envelope({
            "event": "content-block-finish",
            "index": 0,
            "content": {
                "type": "image",
                "mime_type": "image/png",
                "base64": "aW1hZ2U=",
            },
        }),
        "image ready",
    )

    assert [frame.text for frame in projection.frames] == ["image ready"]
    assert len(projection.media) == 1
    assert projection.media[0].content["type"] == "image"
