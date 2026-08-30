from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.event_origin import RunEventOriginResolver, WorkflowNodeSource
from agent_shell.runtime.event_stream import RunEventStream
from agent_shell.runtime.media_events import MediaContentBlock
from agent_shell.runtime.response_presentation import (
    ResponseModelCallBoundary,
)
from agent_shell.runtime.usage import RunUsageAccumulator

from .support import message_envelope


def _resolver() -> RunEventOriginResolver:
    return RunEventOriginResolver(
        None,
        workflow_sources={
            "agent-a": WorkflowNodeSource("agent", "agent-a", "profile-main"),
        },
        main_agent_names=("Main Agent",),
        workflow_agent_names={"agent-a": "Main Agent"},
        workflow_subagent_profile_ids={
            "agent-a": {"Researcher": "profile-researcher"},
        },
    )


def _stream() -> tuple[
    RunEventStream,
    RunUsageAccumulator,
    RunEventOriginResolver,
]:
    usage = RunUsageAccumulator()
    return RunEventStream(usage), usage, _resolver()


def _consume(
    stream: RunEventStream,
    resolver: RunEventOriginResolver,
    event: dict,
):
    signals, _publish_output = stream.consume(event, resolver.resolve(event))
    return signals


def test_streamed_message_finish_closes_the_model_call_without_inventing_block_end() -> None:
    stream, usage, resolver = _stream()
    started = _consume(
        stream,
        resolver,
        message_envelope(
            {"event": "message-start", "role": "ai", "id": "message-1"}
        ),
    )
    block_start = _consume(
        stream,
        resolver,
        message_envelope({
            "event": "content-block-start",
            "index": 0,
            "content": {"type": "text", "text": ""},
        }),
    )
    delta = _consume(
        stream,
        resolver,
        message_envelope({
            "event": "content-block-delta",
            "index": 0,
            "delta": {"type": "text-delta", "text": "partial"},
        }),
    )
    finished = _consume(
        stream,
        resolver,
        message_envelope({
            "event": "message-finish",
            "usage": {
                "input_tokens": 2,
                "output_tokens": 1,
                "total_tokens": 3,
            },
            "metadata": {"finish_reason": "stop"},
        }),
    )

    assert [(type(event), event.phase) for event in started] == [
        (ResponseModelCallBoundary, "start")
    ]
    assert [(event.kind, event.phase) for event in block_start] == [
        ("content", "start")
    ]
    assert [(event.kind, event.phase) for event in delta] == [
        ("content", "delta")
    ]
    assert [(type(event), event.phase) for event in finished] == [
        (ResponseModelCallBoundary, "end")
    ]
    assert usage.snapshot == {
        "input_tokens": 2,
        "output_tokens": 1,
        "total_tokens": 3,
    }


def test_whole_ai_message_does_not_duplicate_a_streamed_model_run() -> None:
    stream, _usage, resolver = _stream()
    for event in (
        message_envelope(
            {"event": "message-start", "role": "ai", "id": "message-1"}
        ),
        message_envelope({
            "event": "message-finish",
            "usage": {},
        }),
    ):
        _consume(stream, resolver, event)

    whole = message_envelope(
        AIMessage(content="must not repeat", id="message-1"),  # type: ignore[arg-type]
    )
    events = _consume(stream, resolver, whole)

    assert [type(event) for event in events] == [
        ResponseModelCallBoundary,
        ResponseModelCallBoundary,
    ]
    assert [event.phase for event in events] == ["start", "end"]


def test_main_agent_message_error_is_redacted_and_fails_immediately() -> None:
    stream, _usage, resolver = _stream()
    _consume(
        stream,
        resolver,
        message_envelope(
            {"event": "message-start", "role": "ai", "id": "message-1"}
        ),
    )

    with pytest.raises(AgentRuntimeError) as captured:
        _consume(
            stream,
            resolver,
            message_envelope({
                "event": "error",
                "error": {"provider_body": "private"},
            }),
        )

    assert captured.value.code == "agent_execution_failed"
    assert "private" not in str(captured.value)


def test_tool_channels_emit_only_scheduler_control_shape() -> None:
    stream, _usage, resolver = _stream()
    declaration = _consume(
        stream,
        resolver,
        message_envelope({
            "event": "content-block-finish",
            "index": 0,
            "content": {
                "type": "tool_call",
                "id": "call-1",
                "name": "read_file",
                "args": {"path": "README.md"},
            },
        }),
    )
    delta_event = {
        "method": "tools",
        "params": {
            "namespace": ["agent-a:invoke-1"],
            "timestamp": 2,
            "data": {
                "event": "tool-output-delta",
                "tool_call_id": "call-1",
                "output": "partial private output",
            },
        },
    }
    finish_event = {
        "method": "tools",
        "params": {
            "namespace": ["agent-a:invoke-1"],
            "timestamp": 3,
            "data": {
                "event": "tool-finished",
                "tool_call_id": "call-1",
                "output": "complete result",
            },
        },
    }
    failure_event = {
        "method": "tools",
        "params": {
            "namespace": ["agent-a:invoke-1"],
            "timestamp": 4,
            "data": {
                "event": "tool-failed",
                "tool_call_id": "call-2",
                "output": {"traceback": "private"},
            },
        },
    }
    delta = _consume(stream, resolver, delta_event)
    finished = _consume(stream, resolver, finish_event)
    failed = _consume(stream, resolver, failure_event)

    assert [(event.tool_kind, event.phase, event.tool_call_id) for event in declaration] == [
        ("call", "end", "call-1")
    ]
    assert [(event.tool_kind, event.phase) for event in delta] == [
        ("progress", "delta")
    ]
    assert [(event.tool_kind, event.phase) for event in (*finished, *failed)] == [
        ("result", "end"),
        ("error", "error"),
    ]
    assert "private" not in repr((*delta, *failed))


def test_subagent_content_and_lifecycle_keep_subagent_origin() -> None:
    stream, _usage, resolver = _stream()
    lifecycle = {
        "method": "lifecycle",
        "params": {
            "namespace": [],
            "timestamp": 1,
            "data": {
                "event": "started",
                "namespace": ["agent-a:invoke-1", "task:research"],
                "graph_name": "Researcher",
            },
        },
    }
    lifecycle_origin = resolver.resolve(lifecycle)
    lifecycle_signals, _ = stream.consume(lifecycle, lifecycle_origin)
    content = message_envelope(
        {
            "event": "content-block-finish",
            "index": 0,
            "content": {"type": "text", "text": "research result"},
        },
        run_id="run-subagent",
        agent_name="Researcher",
        namespace=["agent-a:invoke-1", "task:research"],
    )
    content_origin = resolver.resolve(content)
    content_signals, _ = stream.consume(content, content_origin)

    assert lifecycle_origin.source_type == "subagent"
    assert lifecycle_origin.subagent_profile_id == "profile-researcher"
    assert [(event.kind, event.phase) for event in lifecycle_signals] == [
        ("event", "start")
    ]
    assert content_origin.source_type == "subagent"
    assert content_origin.subagent_profile_id == "profile-researcher"
    assert [(event.kind, event.phase) for event in content_signals] == [
        ("content", "end")
    ]


def test_media_blocks_are_owned_separately_and_unhandled_channels_are_ignored() -> None:
    stream, _usage, resolver = _stream()
    media = message_envelope({
        "event": "content-block-finish",
        "index": 0,
        "content": {
            "type": "image",
            "mime_type": "image/png",
            "base64": "aW1hZ2U=",
        },
    })
    media_events = _consume(stream, resolver, media)
    updates = {
        "method": "updates",
        "params": {"namespace": [], "data": {"private": "state"}},
    }
    unknown = {
        "method": "future-channel",
        "params": {"namespace": [], "data": {"private": "event"}},
    }

    assert len(media_events) == 1
    assert isinstance(media_events[0], MediaContentBlock)
    assert _consume(stream, resolver, updates) == ()
    assert _consume(stream, resolver, unknown) == ()
