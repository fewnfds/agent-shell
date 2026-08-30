from __future__ import annotations

from dataclasses import replace

import pytest

from agent_shell.response_stream_policy import ResponseStreamPolicy
from agent_shell.runtime.response_scheduler import (
    LifecycleResponseScheduler,
    ResponseEvent,
    ResponseEventInput,
    ResponseModelCallBoundary,
)


LIFECYCLE_ID = "lifecycle-1"
RUN_ID = "run-parent"
WORKFLOW_ID = "workflow-parent"


def _policy(**updates: object) -> ResponseStreamPolicy:
    payload = ResponseStreamPolicy().model_dump(mode="json")
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key].update(value)
        else:
            payload[key] = value
    return ResponseStreamPolicy.model_validate(payload)


def _scheduler(
    policy: ResponseStreamPolicy | None = None,
) -> LifecycleResponseScheduler:
    return LifecycleResponseScheduler(
        policy or _policy(),
        lifecycle_id=LIFECYCLE_ID,
        origin_run_id=RUN_ID,
        origin_workflow_id=WORKFLOW_ID,
    )


def test_scheduler_accepts_private_response_signal() -> None:
    scheduler = _scheduler(_policy(queue={"send_interval_seconds": 0}))
    frames = scheduler.submit(
        ResponseEventInput(
            lifecycle_id=LIFECYCLE_ID,
            origin_run_id=RUN_ID,
            origin_workflow_id=WORKFLOW_ID,
            event=ResponseEvent(
                kind="event",
                phase="end",
                sequence=1,
                source_type="script",
                cycle_key="node:invocation",
            ),
            text="private-signal",
        ),
        now=0,
    )
    assert [frame.text for frame in frames] == ["private-signal"]


def _event(
    node_id: str,
    event_type: str,
    phase: str,
    sequence: int,
    *,
    message: str = "",
    stream_id: str = "",
    turn_id: str = "turn-1",
    invocation_id: str = "",
    source_type: str = "agent",
    **values: str,
) -> ResponseEvent:
    cycle_key = invocation_id or f"{node_id}:invocation"
    kind = (
        "content"
        if event_type in {"assistant_text", "reasoning"}
        else "tool"
        if event_type in {"tool_call", "tool_result", "tool_error", "tool_progress"}
        else "lifecycle"
        if event_type == "lifecycle"
        else "event"
    )
    tool_kind = {
        "tool_call": "call",
        "tool_result": "result",
        "tool_error": "error",
        "tool_progress": "progress",
    }.get(event_type, "")
    data: object
    if event_type == "assistant_text":
        data = {"type": "text", "text": message}
    elif event_type == "reasoning":
        data = {"type": "reasoning", "reasoning": message}
    else:
        data = {"message": message, **values}
    return ResponseEvent(
        kind=kind,  # type: ignore[arg-type]
        phase=phase,
        sequence=sequence,
        namespace=cycle_key,
        source_type=source_type,
        workflow_node_id=node_id,
        agent_profile_id=f"profile-{node_id}",
        data=data,
        stream_id=(f"{turn_id}:{stream_id}" if stream_id else ""),
        cycle_key=cycle_key,
        tool_kind=tool_kind,  # type: ignore[arg-type]
        tool_call_id=values.get("tool_call_id", ""),
        terminal=(event_type == "lifecycle" and phase in {"end", "error"}),
    )


def _boundary(
    node_id: str,
    turn_id: str,
    *,
    phase: str = "start",
) -> ResponseModelCallBoundary:
    return ResponseModelCallBoundary(
        run_key=turn_id,
        source_type="agent",
        workflow_node_id=node_id,
        agent_profile_id=f"profile-{node_id}",
        cycle_key=f"{node_id}:invocation",
        phase=phase,
    )


def _submit(
    scheduler: LifecycleResponseScheduler,
    event: ResponseEvent | ResponseModelCallBoundary,
    now: float,
) -> list[str]:
    text = ""
    segment_end_text = ""
    if isinstance(event, ResponseEvent):
        text, segment_end_text = _projected_text(event)
    return [
        frame.text
        for frame in scheduler.submit(
            ResponseEventInput(
                lifecycle_id=LIFECYCLE_ID,
                origin_run_id=RUN_ID,
                origin_workflow_id=WORKFLOW_ID,
                event=event,
                text=text,
                segment_end_text=segment_end_text,
            ), now=now,
        )
    ]


def _projected_text(event: ResponseEvent) -> tuple[str, str]:
    """Supply already-rendered text to scheduler tests.

    Runtime tests call the public extension before this stream. Scheduler
    tests start at the private projected-event boundary and therefore pass
    text explicitly instead of invoking an Event Output package.
    """

    data = event.data if isinstance(event.data, dict) else {}
    block_type = str(data.get("type") or "")
    message = str(
        data.get("text")
        or data.get("reasoning")
        or data.get("message")
        or ""
    )
    if event.kind == "content" and block_type != "reasoning":
        if isinstance(event.data, dict) and event.data.get("type") in {
            "image",
            "audio",
            "video",
            "file",
        }:
            return f"<text>{message}</text>", ""
        return (
            (message if event.phase == "delta" else ""),
            "",
        )
    if event.kind == "content" and block_type == "reasoning":
        if event.phase == "start":
            return '<details type="agent"><summary>Reasoning</summary>', "</details>\n"
        if event.phase == "delta":
            return message, ""
        if event.phase == "end":
            return "", "</details>\n"
        return "", ""
    templates = {
        "tool_call": "<call id={tool_call_id}>{message}</call>",
        "tool_result": "<result id={tool_call_id}>{message}</result>",
        "tool_error": "<error id={tool_call_id}>{message}</error>",
        "custom": "<custom>{message}</custom>",
    }
    event_type = {
        ("tool", "call"): "tool_call",
        ("tool", "result"): "tool_result",
        ("tool", "error"): "tool_error",
        ("event", ""): "custom",
    }.get((event.kind, event.tool_kind))
    template = templates.get(event_type or "")
    if template is None:
        return "", ""
    fields = {key: value for key, value in data.items() if key != "message"}
    return template.format(message=message, **fields), ""


def test_request_atom_holds_competing_request_until_idle_timeout() -> None:
    scheduler = _scheduler()
    assert _submit(scheduler, _boundary("agent-a", "turn-a"), 0) == []
    assert _submit(
        scheduler,
        _event("agent-a", "reasoning", "start", 1, stream_id="0", turn_id="turn-a"),
        0,
    ) == ['<details type="agent"><summary>Reasoning</summary>']
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "reasoning",
            "delta",
            2,
            stream_id="0",
            turn_id="turn-a",
            message="A1",
        ),
        0.1,
    ) == ["A1"]

    assert _submit(scheduler, _boundary("agent-b", "turn-b"), 0.2) == []
    assert _submit(
        scheduler,
        _event("agent-b", "assistant_text", "start", 3, stream_id="0", turn_id="turn-b"),
        0.2,
    ) == []
    assert _submit(
        scheduler,
        _event(
            "agent-b",
            "assistant_text",
            "delta",
            4,
            stream_id="0",
            turn_id="turn-b",
            message="B",
        ),
        0.3,
    ) == []
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "reasoning",
            "delta",
            5,
            stream_id="0",
            turn_id="turn-a",
            message="A2",
        ),
        0.4,
    ) == ["A2"]
    released = _submit(
        scheduler,
        _event(
            "agent-a",
            "reasoning",
            "end",
            6,
            stream_id="0",
            turn_id="turn-a",
            message="snapshot is ignored",
        ),
        0.5,
    )
    assert released == ["</details>\n"]
    assert scheduler.advance(now=2.49) == []
    assert [frame.text for frame in scheduler.advance(now=2.5)] == ["", "B"]
    assert _submit(
        scheduler,
        _event(
            "agent-b",
            "assistant_text",
            "end",
            7,
            stream_id="0",
            turn_id="turn-b",
            message="B",
        ),
        2.6,
    ) == [""]


def test_filtered_content_does_not_refresh_request_atom_idle_deadline() -> None:
    scheduler = _scheduler()
    _submit(scheduler, _boundary("agent-a", "turn-a"), 0)
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "reasoning",
            "start",
            1,
            stream_id="0",
            turn_id="turn-a",
        ),
        0,
    ) == ['<details type="agent"><summary>Reasoning</summary>']
    assert scheduler.next_deadline() == pytest.approx(2)

    _submit(scheduler, _boundary("agent-b", "turn-b"), 0.1)
    _submit(
        scheduler,
        _event(
            "agent-b",
            "assistant_text",
            "start",
            2,
            stream_id="0",
            turn_id="turn-b",
        ),
        0.1,
    )
    assert _submit(
        scheduler,
        _event(
            "agent-b",
            "assistant_text",
            "delta",
            3,
            stream_id="0",
            turn_id="turn-b",
            message="B",
        ),
        0.2,
    ) == []

    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "reasoning",
            "delta",
            4,
            stream_id="0",
            turn_id="turn-a",
            message="",
        ),
        1.9,
    ) == []
    assert scheduler.next_deadline() == pytest.approx(2)
    assert [
        frame.text
        for frame in scheduler.advance(now=2)
        if frame.text
    ] == ["</details>\n", "B"]


def test_model_boundary_end_does_not_refresh_or_terminate_request_atom() -> None:
    scheduler = _scheduler()
    _submit(scheduler, _boundary("agent-a", "turn-a"), 0)
    _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "start",
            1,
            stream_id="0",
            turn_id="turn-a",
        ),
        0,
    )
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "delta",
            2,
            stream_id="0",
            turn_id="turn-a",
            message="A",
        ),
        0,
    ) == ["", "A"]

    _submit(scheduler, _boundary("agent-b", "turn-b"), 0.1)
    _submit(
        scheduler,
        _event(
            "agent-b",
            "assistant_text",
            "start",
            3,
            stream_id="0",
            turn_id="turn-b",
        ),
        0.1,
    )
    assert _submit(
        scheduler,
        _event(
            "agent-b",
            "assistant_text",
            "delta",
            4,
            stream_id="0",
            turn_id="turn-b",
            message="B",
        ),
        0.2,
    ) == []

    assert [
        text
        for text in _submit(
            scheduler,
            _boundary("agent-a", "turn-a", phase="end"),
            0.3,
        )
        if text
    ] == []
    assert scheduler.next_deadline() == pytest.approx(2)
    assert [
        frame.text
        for frame in scheduler.advance(now=2)
        if frame.text
    ] == ["B"]


def test_next_model_request_releases_the_previous_request_atom() -> None:
    scheduler = _scheduler(_policy(queue={"idle_timeout_seconds": 30}))
    _submit(scheduler, _boundary("agent-a", "turn-a"), 0)
    _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "start",
            1,
            stream_id="0",
            turn_id="turn-a",
        ),
        0,
    )
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "delta",
            2,
            stream_id="0",
            turn_id="turn-a",
            message="first",
        ),
        0.1,
    ) == ["", "first"]
    _submit(scheduler, _boundary("agent-a", "turn-a", phase="end"), 0.2)

    assert _submit(scheduler, _boundary("agent-a", "turn-b"), 0.3) == []
    _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "start",
            3,
            stream_id="0",
            turn_id="turn-b",
        ),
        0.3,
    )
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "delta",
            4,
            stream_id="0",
            turn_id="turn-b",
            message="second",
        ),
        0.4,
    ) == ["", "second"]


def test_node_terminal_releases_the_last_request_atom() -> None:
    scheduler = _scheduler(_policy(queue={"idle_timeout_seconds": 30}))
    _submit(scheduler, _boundary("agent-a", "turn-a"), 0)
    _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "start",
            1,
            stream_id="0",
            turn_id="turn-a",
        ),
        0,
    )
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "delta",
            2,
            stream_id="0",
            turn_id="turn-a",
            message="A",
        ),
        0.1,
    ) == ["", "A"]
    _submit(scheduler, _boundary("agent-a", "turn-a", phase="end"), 0.2)

    _submit(scheduler, _boundary("agent-b", "turn-b"), 0.3)
    _submit(
        scheduler,
        _event(
            "agent-b",
            "assistant_text",
            "start",
            3,
            stream_id="0",
            turn_id="turn-b",
        ),
        0.3,
    )
    assert _submit(
        scheduler,
        _event(
            "agent-b",
            "assistant_text",
            "delta",
            4,
            stream_id="0",
            turn_id="turn-b",
            message="B",
        ),
        0.4,
    ) == []

    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "lifecycle",
            "end",
            5,
            message="completed",
            status="completed",
        ),
        0.5,
    ) == ["", "B"]


def test_idle_timeout_closes_only_presentation_and_late_delta_continues() -> None:
    scheduler = _scheduler()
    _submit(scheduler, _boundary("agent-a", "turn-a"), 0)
    _submit(
        scheduler,
        _event("agent-a", "reasoning", "start", 1, stream_id="0", turn_id="turn-a"),
        0,
    )
    _submit(
        scheduler,
        _event("agent-a", "reasoning", "delta", 2, stream_id="0", turn_id="turn-a", message="R1"),
        0.1,
    )
    _submit(
        scheduler,
        _event("agent-a", "assistant_text", "start", 3, stream_id="1", turn_id="turn-a"),
        0.2,
    )
    assert _submit(
        scheduler,
        _event("agent-a", "assistant_text", "delta", 4, stream_id="1", turn_id="turn-a", message="T"),
        0.3,
    ) == []
    assert scheduler.next_deadline() == pytest.approx(2.3)
    assert scheduler.advance(now=2.29) == []
    switched = scheduler.advance(now=2.3)
    assert [frame.text for frame in switched] == ["</details>\n", "", "T"]
    assert switched[0].close_reason == "idle_timeout"

    assert _submit(
        scheduler,
        _event("agent-a", "reasoning", "delta", 5, stream_id="0", turn_id="turn-a", message="R2"),
        2.4,
    ) == []
    continued = scheduler.advance(now=4.4)
    assert [frame.text for frame in continued] == [
        "",
        '<details type="agent"><summary>Reasoning</summary>',
        "R2",
    ]
    assert continued[1].continuation is True


def test_content_projection_is_additive_and_media_remains_atomic() -> None:
    scheduler = _scheduler()
    assert _submit(
        scheduler,
        _event("agent-a", "assistant_text", "start", 1, stream_id="0"),
        0,
    ) == []
    assert _submit(
        scheduler,
        _event("agent-a", "assistant_text", "delta", 2, stream_id="0", message="delta "),
        0.1,
    ) == ["", "delta "]
    assert _submit(
        scheduler,
        _event("agent-a", "assistant_text", "delta", 3, stream_id="0", message="wins"),
        0.2,
    ) == ["wins"]
    assert _submit(
        scheduler,
        _event("agent-a", "assistant_text", "end", 4, stream_id="0", message="different snapshot"),
        0.3,
    ) == [""]

    media = _event(
        "agent-a",
        "assistant_text",
        "end",
        5,
        message="[image]",
        stream_id="media",
    )
    object.__setattr__(media, "data", {"type": "image", "text": "[image]"})
    assert _submit(scheduler, media, 0.4) == ["<text>[image]</text>"]


def test_non_streaming_whole_content_is_emitted_from_one_end_signal() -> None:
    scheduler = LifecycleResponseScheduler(
        _policy(queue={"send_interval_seconds": 0}),
        lifecycle_id=LIFECYCLE_ID,
        origin_run_id=RUN_ID,
        origin_workflow_id=WORKFLOW_ID,
    )

    def submit_projected(
        event: ResponseEvent,
        *,
        text: str,
        segment_end_text: str = "",
    ) -> list[str]:
        return [
            frame.text
            for frame in scheduler.submit(
                ResponseEventInput(
                    lifecycle_id=LIFECYCLE_ID,
                    origin_run_id=RUN_ID,
                    origin_workflow_id=WORKFLOW_ID,
                    event=event,
                    text=text,
                    segment_end_text=segment_end_text,
                ),
                now=0,
            )
        ]

    assert _submit(scheduler, _boundary("agent-a", "turn-1"), 0) == []
    rendered = submit_projected(
        _event(
            "agent-a",
            "assistant_text",
            "end",
            1,
            stream_id="whole",
            message="complete response",
        ),
        text="complete response",
    )
    rendered.extend(_submit(
        scheduler,
        _boundary("agent-a", "turn-1", phase="end"),
        0,
    ))

    assert rendered == ["", "complete response"]


def test_message_finish_is_a_strong_boundary_before_content_finish_arrives() -> None:
    scheduler = _scheduler()
    _submit(scheduler, _boundary("agent-a", "turn-a"), 0)
    assert _submit(
        scheduler,
        _event("agent-a", "assistant_text", "start", 1, stream_id="0", turn_id="turn-a"),
        0,
    ) == []
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "delta",
            2,
            stream_id="0",
            turn_id="turn-a",
            message="available now",
        ),
        0.1,
    ) == ["", "available now"]

    assert _submit(
        scheduler,
        _boundary("agent-a", "turn-a", phase="end"),
        0.2,
    ) == [""]
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "end",
            3,
            stream_id="0",
            turn_id="turn-a",
            message="available now",
        ),
        0.3,
    ) == []


def test_scheduler_preserves_nonempty_projected_content_error() -> None:
    scheduler = _scheduler()
    event = _event(
        "agent-a",
        "assistant_text",
        "error",
        1,
        stream_id="0",
        message="upstream details remain private",
    )

    frames = scheduler.submit(
        ResponseEventInput(
            lifecycle_id=LIFECYCLE_ID,
            origin_run_id=RUN_ID,
            origin_workflow_id=WORKFLOW_ID,
            event=event,
            text="visible failure",
        ),
        now=0,
    )

    assert [frame.text for frame in frames] == ["", "visible failure", ""]


def test_slow_tools_resume_at_queue_tail_in_completion_order() -> None:
    scheduler = _scheduler()
    for sequence, call_id in ((1, "call-a"), (2, "call-b")):
        assert _submit(
            scheduler,
            _event(
                "agent-a",
                "tool_call",
                "end",
                sequence,
                message=f"args-{call_id}",
                stream_id=str(sequence),
                tool_call_id=call_id,
                tool_name="tool",
            ),
            float(sequence),
        ) == []

    assert _submit(
        scheduler,
        _event("agent-b", "assistant_text", "start", 3, stream_id="0", turn_id="turn-b"),
        3,
    ) == []
    assert _submit(
        scheduler,
        _event("agent-b", "assistant_text", "delta", 4, stream_id="0", turn_id="turn-b", message="B works"),
        3.1,
    ) == ["", "B works"]
    assert _submit(
        scheduler,
        _event("agent-b", "assistant_text", "end", 5, stream_id="0", turn_id="turn-b", message="B works"),
        3.2,
    ) == [""]

    assert _submit(
        scheduler,
        _event("agent-a", "tool_result", "end", 6, message="result-b", tool_call_id="call-b", tool_name="tool"),
        4,
    ) == []
    assert _submit(
        scheduler,
        _event("agent-a", "tool_result", "end", 7, message="result-a", tool_call_id="call-a", tool_name="tool"),
        5,
    ) == []
    assert [frame.text for frame in scheduler.advance(now=5.2)] == [
        "<call id=call-b>args-call-b</call><result id=call-b>result-b</result>",
        "<call id=call-a>args-call-a</call><result id=call-a>result-a</result>"
    ]


def test_idle_timeout_does_not_synthesize_activity_output() -> None:
    scheduler = _scheduler()
    _submit(
        scheduler,
        _event("agent-a", "assistant_text", "start", 1, stream_id="0"),
        0,
    )
    _submit(
        scheduler,
        _event("agent-a", "assistant_text", "delta", 2, stream_id="0", message="hello"),
        1,
    )
    assert scheduler.next_deadline() == pytest.approx(3)
    assert [frame.text for frame in scheduler.advance(now=3)] == [""]
    assert scheduler.advance(now=4) == []
    resumed = _submit(
        scheduler,
        _event("agent-a", "assistant_text", "delta", 3, stream_id="0", message=" again"),
        5,
    )
    assert resumed == ["", " again"]


def test_node_invocation_atom_releases_other_invocation_at_terminal() -> None:
    policy = _policy(
        queue={"strategy": "node_invocation"},
    )
    scheduler = _scheduler(policy)
    _submit(
        scheduler,
        _event("agent-a", "assistant_text", "start", 1, stream_id="0"),
        0,
    )
    _submit(
        scheduler,
        _event("agent-a", "assistant_text", "delta", 2, stream_id="0", message="A"),
        0.1,
    )
    _submit(
        scheduler,
        _event("agent-a", "assistant_text", "end", 3, stream_id="0", message="A"),
        0.2,
    )
    _submit(
        scheduler,
        _event("agent-b", "assistant_text", "start", 4, stream_id="0", turn_id="turn-b"),
        0.3,
    )
    assert _submit(
        scheduler,
        _event("agent-b", "assistant_text", "delta", 5, stream_id="0", turn_id="turn-b", message="B"),
        0.4,
    ) == []
    assert _submit(
        scheduler,
        _event("agent-a", "lifecycle", "end", 6, message="completed", status="completed"),
        0.5,
    ) == ["", "B"]


def test_empty_node_terminal_closes_content_and_releases_invocation() -> None:
    scheduler = _scheduler(_policy(queue={"strategy": "node_invocation"}))
    assert _submit(
        scheduler,
        _event("agent-a", "reasoning", "start", 1, stream_id="0"),
        0,
    ) == ['<details type="agent"><summary>Reasoning</summary>']
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "reasoning",
            "delta",
            2,
            stream_id="0",
            message="A",
        ),
        0.1,
    ) == ["A"]
    _submit(
        scheduler,
        _event(
            "agent-b",
            "assistant_text",
            "start",
            3,
            stream_id="0",
            turn_id="turn-b",
        ),
        0.2,
    )
    assert _submit(
        scheduler,
        _event(
            "agent-b",
            "assistant_text",
            "delta",
            4,
            stream_id="0",
            turn_id="turn-b",
            message="B",
        ),
        0.3,
    ) == []

    assert [
        text
        for text in _submit(
            scheduler,
            _event(
                "agent-a",
                "lifecycle",
                "end",
                5,
                message="completed",
                status="completed",
            ),
            0.4,
        )
        if text
    ] == ["</details>\n", "B"]


def test_reentering_the_same_node_uses_a_distinct_invocation_atom() -> None:
    policy = _policy(
        queue={"strategy": "node_invocation"},
    )
    scheduler = _scheduler(policy)
    first = "agent-a:invocation-1"
    second = "agent-a:invocation-2"

    _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "start",
            1,
            stream_id="0",
            invocation_id=first,
        ),
        0,
    )
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "delta",
            2,
            message="first",
            stream_id="0",
            invocation_id=first,
        ),
        0.1,
    ) == ["", "first"]
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "end",
            3,
            message="first",
            stream_id="0",
            invocation_id=first,
        ),
        0.2,
    ) == [""]

    _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "start",
            4,
            stream_id="0",
            invocation_id=second,
        ),
        0.3,
    )
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "assistant_text",
            "delta",
            5,
            message="second",
            stream_id="0",
            invocation_id=second,
        ),
        0.4,
    ) == []
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "lifecycle",
            "end",
            6,
            message="completed",
            invocation_id=first,
            status="completed",
        ),
        0.5,
    ) == ["", "second"]


def test_soft_batch_size_groups_small_events_and_keeps_oversized_event_whole() -> None:
    policy = _policy(
        queue={
            "max_batch_kb": 0.04,
            "send_interval_seconds": 0.05,
        },
    )
    scheduler = _scheduler(policy)

    assert _submit(
        scheduler,
        _event("script", "custom", "end", 1, message="first"),
        0,
    ) == ["<custom>first</custom>"]
    for sequence, message in ((2, "aa"), (3, "bb"), (4, "cc")):
        assert _submit(
            scheduler,
            _event("script", "custom", "end", sequence, message=message),
            0.01,
        ) == []

    assert [frame.text for frame in scheduler.advance(now=0.05)] == [
        "<custom>aa</custom>",
        "<custom>bb</custom>",
    ]
    assert [frame.text for frame in scheduler.advance(now=0.1)] == [
        "<custom>cc</custom>",
    ]

    oversized = _policy(
        queue={"max_batch_kb": 0.001, "send_interval_seconds": 0},
    )
    oversized_scheduler = _scheduler(oversized)
    assert _submit(
        oversized_scheduler,
        _event("script", "custom", "end", 5, message="larger-than-soft-limit"),
        0,
    ) == ["<custom>larger-than-soft-limit</custom>"]


def test_input_port_rejects_unregistered_run_identity() -> None:
    scheduler = _scheduler()
    with pytest.raises(ValueError, match="does not belong"):
        scheduler.submit(
            ResponseEventInput(
                lifecycle_id=LIFECYCLE_ID,
                origin_run_id="child-run",
                origin_workflow_id=WORKFLOW_ID,
                event=_event("agent-a", "assistant_text", "start", 1),
            ),
            now=0,
        )


def test_registered_child_and_parent_events_share_one_fifo_batch_queue() -> None:
    scheduler = _scheduler(
        _policy(
            queue={
                "send_interval_seconds": 0.1,
            }
        )
    )
    scheduler.register_origin("child-run", "child-workflow")

    def submit(
        run_id: str,
        workflow_id: str,
        message: str,
        sequence: int,
        now: float,
    ) -> list[str]:
        event = _event(
            "script",
            "custom",
            "end",
            sequence,
            message=message,
            source_type="script",
        )
        text, segment_end_text = _projected_text(event)
        return [
            frame.text
            for frame in scheduler.submit(
                ResponseEventInput(
                    lifecycle_id=LIFECYCLE_ID,
                    origin_run_id=run_id,
                    origin_workflow_id=workflow_id,
                    event=event,
                    text=text,
                    segment_end_text=segment_end_text,
                ),
                now=now,
            )
        ]

    assert submit(RUN_ID, WORKFLOW_ID, "parent-first", 1, 0) == [
        "<custom>parent-first</custom>"
    ]
    assert submit(
        "child-run",
        "child-workflow",
        "child-second",
        2,
        0.01,
    ) == []
    assert submit(RUN_ID, WORKFLOW_ID, "parent-third", 3, 0.02) == []
    assert [frame.text for frame in scheduler.advance(now=0.1)] == [
        "<custom>child-second</custom>",
        "<custom>parent-third</custom>",
    ]


def test_aborting_child_lanes_keeps_parent_content_owner_open() -> None:
    scheduler = _scheduler(
        _policy(
            queue={
                "idle_timeout_seconds": 30,
                "send_interval_seconds": 0,
            }
        )
    )
    scheduler.register_origin("child-run", "child-workflow")

    def submit(
        run_id: str,
        workflow_id: str,
        event: ResponseEvent,
        text: str,
        now: float,
    ) -> list[str]:
        return [
            frame.text
            for frame in scheduler.submit(
                ResponseEventInput(
                    lifecycle_id=LIFECYCLE_ID,
                    origin_run_id=run_id,
                    origin_workflow_id=workflow_id,
                    event=event,
                    text=text,
                ),
                now=now,
            )
            if frame.text
        ]

    parent_start = _event(
        "shared-agent",
        "assistant_text",
        "start",
        1,
        stream_id="0",
        turn_id="parent-turn",
    )
    parent_delta = replace(
        parent_start,
        phase="delta",
        sequence=2,
        data={"type": "text", "text": "parent"},
    )
    child_start = _event(
        "shared-agent",
        "assistant_text",
        "start",
        1,
        stream_id="0",
        turn_id="child-turn",
    )
    child_delta = replace(
        child_start,
        phase="delta",
        sequence=2,
        data={"type": "text", "text": "child"},
    )

    assert submit(RUN_ID, WORKFLOW_ID, parent_start, "", 0) == []
    assert submit(RUN_ID, WORKFLOW_ID, parent_delta, "parent", 0) == ["parent"]
    assert submit(
        "child-run",
        "child-workflow",
        child_start,
        "",
        0.01,
    ) == []
    assert submit(
        "child-run",
        "child-workflow",
        child_delta,
        "child",
        0.01,
    ) == []

    scheduler.abort_origin(
        "child-run",
        "child-workflow",
        now=0.02,
    )
    scheduler.finish_origin(
        "child-run",
        "child-workflow",
        now=0.02,
    )
    parent_continuation = replace(
        parent_delta,
        sequence=3,
        data={"type": "text", "text": "-continues"},
    )
    assert submit(
        RUN_ID,
        WORKFLOW_ID,
        parent_continuation,
        "-continues",
        0.03,
    ) == ["-continues"]


def test_same_tool_call_identity_in_two_runs_does_not_cross_pair() -> None:
    scheduler = _scheduler(_policy(queue={"send_interval_seconds": 0}))
    scheduler.register_origin("child-run", "child-workflow")

    def submit(
        run_id: str,
        workflow_id: str,
        event: ResponseEvent,
        text: str,
        now: float,
    ) -> list[str]:
        return [
            frame.text
            for frame in scheduler.submit(
                ResponseEventInput(
                    lifecycle_id=LIFECYCLE_ID,
                    origin_run_id=run_id,
                    origin_workflow_id=workflow_id,
                    event=event,
                    text=text,
                ),
                now=now,
            )
            if frame.text
        ]

    parent_call = _event(
        "shared-agent",
        "tool_call",
        "end",
        1,
        message="parent-call",
        tool_call_id="shared-call",
    )
    child_result = _event(
        "shared-agent",
        "tool_result",
        "end",
        2,
        message="child-result",
        tool_call_id="shared-call",
    )
    child_call = replace(
        parent_call,
        sequence=3,
        data={"message": "child-call", "tool_call_id": "shared-call"},
    )
    parent_result = replace(
        child_result,
        sequence=4,
        data={"message": "parent-result", "tool_call_id": "shared-call"},
    )

    assert submit(
        RUN_ID,
        WORKFLOW_ID,
        parent_call,
        "<parent-call>",
        0,
    ) == []
    assert submit(
        "child-run",
        "child-workflow",
        child_result,
        "<child-result>",
        0.01,
    ) == []
    assert submit(
        "child-run",
        "child-workflow",
        child_call,
        "<child-call>",
        0.02,
    ) == ["<child-call><child-result>"]
    assert submit(
        RUN_ID,
        WORKFLOW_ID,
        parent_result,
        "<parent-result>",
        0.03,
    ) == ["<parent-call><parent-result>"]


def test_parent_response_seal_rejects_late_child_output() -> None:
    scheduler = _scheduler(_policy(queue={"send_interval_seconds": 0}))
    scheduler.register_origin("child-run", "child-workflow")

    scheduler.finish_origin(RUN_ID, WORKFLOW_ID, now=0)
    assert scheduler.finish(now=0) == []
    assert not scheduler.accepting("child-run", "child-workflow")

    scheduler.publish(
        ResponseEventInput(
            lifecycle_id=LIFECYCLE_ID,
            origin_run_id="child-run",
            origin_workflow_id="child-workflow",
            event=_event(
                "child-script",
                "custom",
                "end",
                1,
                message="too-late",
                source_type="script",
            ),
            text="<custom>too-late</custom>",
        ),
        now=0.01,
    )

    assert scheduler.take_published() == []
    assert not scheduler.has_pending_output


def test_unresolved_tool_declaration_remains_withheld_at_run_terminal() -> None:
    scheduler = _scheduler()
    assert _submit(
        scheduler,
        _event(
            "agent-a",
            "tool_call",
            "end",
            1,
            message="args",
            stream_id="0",
            tool_call_id="call-unresolved",
            tool_name="slow_tool",
        ),
        0,
    ) == []

    assert scheduler.finish(now=10) == []
