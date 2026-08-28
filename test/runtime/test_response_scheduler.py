from __future__ import annotations

from copy import deepcopy

import pytest

from agent_shell.response_stream_policy import ResponseStreamPolicy
from agent_shell.runtime.output_projection import OutputProjector
from agent_shell.runtime.output_stream import ModelCallBoundary, OutputEvent
from agent_shell.runtime.response_scheduler import (
    LifecycleResponseScheduler,
    ResponseEventInput,
)

from .support import output_renderer


LIFECYCLE_ID = "lifecycle-1"
RUN_ID = "run-parent"
WORKFLOW_ID = "workflow-parent"


def _policy(**updates: object) -> ResponseStreamPolicy:
    payload = ResponseStreamPolicy().model_dump(mode="json")
    payload["activity"] = {
        "announce_start": False,
        "announce_queued": False,
        "hidden_delta_pulse_seconds": None,
        "quiet_notice_after_seconds": None,
        "quiet_notice_repeat_seconds": None,
    }
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key].update(value)
        else:
            payload[key] = value
    return ResponseStreamPolicy.model_validate(payload)


def _scheduler(
    policy: ResponseStreamPolicy | None = None,
) -> LifecycleResponseScheduler:
    projector = OutputProjector(
        output_renderer(
            {
                "assistant_text": "<text>{{message}}</text>",
                "reasoning": "<reasoning>{{message}}</reasoning>",
                "tool_call": "<call id={{tool_call_id}}>{{message}}</call>",
                "tool_result": "<result id={{tool_call_id}}>{{message}}</result>",
                "tool_error": "<error id={{tool_call_id}}>{{message}}</error>",
                "custom": "<custom>{{message}}</custom>",
            }
        )
    )
    return LifecycleResponseScheduler(
        projector,
        policy or _policy(),
        lifecycle_id=LIFECYCLE_ID,
        origin_run_id=RUN_ID,
        origin_workflow_id=WORKFLOW_ID,
    )


def _event(
    node_id: str,
    event_type: str,
    phase: str,
    sequence: int,
    *,
    message: str = "",
    stream_id: str = "",
    turn_id: str = "turn-1",
    source_type: str = "agent",
    **values: str,
) -> OutputEvent:
    return OutputEvent(
        event_type=event_type,
        phase=phase,
        sequence=sequence,
        timestamp="2026-08-28T00:00:00Z",
        namespace=f"{node_id}:invocation",
        agent_name=node_id,
        node="model",
        source_type=source_type,
        workflow_node_id=node_id,
        agent_profile_id=f"profile-{node_id}",
        message=message,
        values=values,
        stream_id=(f"{turn_id}:{stream_id}" if stream_id else ""),
        source_key=f"{source_type}|{node_id}|profile-{node_id}|",
        cycle_key=f"{node_id}:invocation",
    )


def _boundary(
    node_id: str,
    turn_id: str,
    *,
    phase: str = "start",
) -> ModelCallBoundary:
    return ModelCallBoundary(
        run_key=turn_id,
        source_key=f"agent|{node_id}|profile-{node_id}|",
        cycle_key=f"{node_id}:invocation",
        phase=phase,
    )


def _submit(
    scheduler: LifecycleResponseScheduler,
    event: OutputEvent | ModelCallBoundary,
    now: float,
) -> list[str]:
    return [
        frame.text
        for frame in scheduler.submit(
            ResponseEventInput(
                lifecycle_id=LIFECYCLE_ID,
                origin_run_id=RUN_ID,
                origin_workflow_id=WORKFLOW_ID,
                event=event,
            ),
            now=now,
        )
    ]


def test_live_delta_is_immediate_and_competing_lane_never_interleaves() -> None:
    scheduler = _scheduler()
    assert _submit(scheduler, _boundary("agent-a", "turn-a"), 0) == []
    assert _submit(
        scheduler,
        _event("agent-a", "reasoning", "start", 1, stream_id="0", turn_id="turn-a"),
        0,
    ) == []
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
    ) == ['<details type="agent"><summary>Reasoning</summary>', "A1"]

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
    assert released == ["</details>\n", "", "B"]
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
        0.6,
    ) == [""]


def test_successor_grace_closes_only_presentation_and_late_delta_continues() -> None:
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
    assert switched[0].close_reason == "successor_grace"

    assert _submit(
        scheduler,
        _event("agent-a", "reasoning", "delta", 5, stream_id="0", turn_id="turn-a", message="R2"),
        2.4,
    ) == []
    continued = scheduler.advance(now=4.4)
    assert [frame.text for frame in continued] == [
        "",
        "[Continued: agent-a]\n<details type=\"agent\"><summary>Reasoning</summary>",
        "R2",
    ]
    assert continued[1].continuation is True


def test_complete_delivery_uses_delta_canonical_text_and_media_is_atomic() -> None:
    policy = _policy(
        assistant_text={
            "delivery": "complete",
            "live_wrapper": {"start": "", "end": ""},
        }
    )
    scheduler = _scheduler(policy)
    assert _submit(
        scheduler,
        _event("agent-a", "assistant_text", "start", 1, stream_id="0"),
        0,
    ) == []
    assert _submit(
        scheduler,
        _event("agent-a", "assistant_text", "delta", 2, stream_id="0", message="delta "),
        0.1,
    ) == []
    assert _submit(
        scheduler,
        _event("agent-a", "assistant_text", "delta", 3, stream_id="0", message="wins"),
        0.2,
    ) == []
    assert _submit(
        scheduler,
        _event("agent-a", "assistant_text", "end", 4, stream_id="0", message="different snapshot"),
        0.3,
    ) == ["<text>delta wins</text>"]

    media = _event(
        "agent-a",
        "assistant_text",
        "end",
        5,
        message="[image]",
        stream_id="media",
    )
    object.__setattr__(media, "data", {"type": "image"})
    assert _submit(scheduler, media, 0.4) == ["<text>[image]</text>"]


def test_message_finish_is_a_strong_boundary_before_content_finish_arrives() -> None:
    policy = _policy(
        assistant_text={
            "delivery": "complete",
            "live_wrapper": {"start": "", "end": ""},
        }
    )
    scheduler = _scheduler(policy)
    _submit(scheduler, _boundary("agent-a", "turn-a"), 0)
    _submit(
        scheduler,
        _event("agent-a", "assistant_text", "start", 1, stream_id="0", turn_id="turn-a"),
        0,
    )
    _submit(
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
    )

    assert _submit(
        scheduler,
        _boundary("agent-a", "turn-a", phase="end"),
        0.2,
    ) == ["<text>available now</text>"]


def test_slow_tools_yield_and_completed_pairs_use_completion_order() -> None:
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
    ) == [
        "<call id=call-b>args-call-b</call><result id=call-b>result-b</result>"
    ]
    assert _submit(
        scheduler,
        _event("agent-a", "tool_result", "end", 7, message="result-a", tool_call_id="call-a", tool_name="tool"),
        5,
    ) == [
        "<call id=call-a>args-call-a</call><result id=call-a>result-a</result>"
    ]


def test_quiet_notice_closes_live_segment_and_resume_is_continuation() -> None:
    policy = _policy(
        activity={
            "announce_start": False,
            "announce_queued": False,
            "hidden_delta_pulse_seconds": None,
            "quiet_notice_after_seconds": 3,
            "quiet_notice_repeat_seconds": None,
        }
    )
    scheduler = _scheduler(policy)
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
    assert scheduler.next_deadline() == pytest.approx(4)
    waiting = scheduler.advance(now=4)
    assert [frame.text for frame in waiting] == ["", "\n[Activity] agent-a: waiting\n"]
    resumed = _submit(
        scheduler,
        _event("agent-a", "assistant_text", "delta", 3, stream_id="0", message=" again"),
        5,
    )
    assert resumed == ["[Continued: agent-a]\n", " again"]


def test_strict_source_holds_other_lanes_until_node_terminal() -> None:
    policy = _policy(
        queue={"mode": "strict_source", "successor_grace_seconds": 2},
        workflow_lifecycle={"delivery": "hidden"},
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


def test_unresolved_tool_is_safely_closed_at_run_terminal() -> None:
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

    assert [frame.text for frame in scheduler.finish(now=10)] == [
        "<call id=call-unresolved>args</call>"
        "<error id=call-unresolved>Tool execution did not produce a terminal outcome.</error>"
    ]
