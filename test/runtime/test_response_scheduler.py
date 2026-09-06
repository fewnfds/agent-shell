from __future__ import annotations

import pytest

from agent_shell.response_stream_policy import ResponseStreamPolicy
from agent_shell.runtime.response_presentation import PresentationFrame
from agent_shell.runtime.response_scheduler import (
    LifecycleResponseScheduler,
    ResponseFrameInput,
)


LIFECYCLE_ID = "lifecycle-1"
ENTRY = ("thread-entry", "run-entry")
CHILD = ("thread-child", "run-child")


def _policy(**updates: object) -> ResponseStreamPolicy:
    payload = ResponseStreamPolicy().model_dump(mode="json")
    payload["queue"].update(updates)
    return ResponseStreamPolicy.model_validate(payload)


def _scheduler(**updates: object) -> LifecycleResponseScheduler:
    return LifecycleResponseScheduler(
        _policy(**updates),
        lifecycle_id=LIFECYCLE_ID,
    )


def _publish(
    scheduler: LifecycleResponseScheduler,
    key: tuple[str, str],
    frame: PresentationFrame,
    *,
    now: float,
) -> list[PresentationFrame]:
    scheduler.publish(
        ResponseFrameInput(
            lifecycle_id=LIFECYCLE_ID,
            thread_id=key[0],
            run_id=key[1],
            frame=frame,
        ),
        now=now,
    )
    return scheduler.take_published()


def _texts(frames: list[PresentationFrame]) -> list[str]:
    return [frame.text for frame in frames]


def test_registered_silent_owner_times_out_and_gives_ready_run_writer() -> None:
    scheduler = _scheduler(idle_timeout_seconds=2, send_interval_seconds=0)
    scheduler.register_run(*ENTRY, now=0)
    scheduler.register_run(*CHILD, now=0.1)
    assert _texts(
        _publish(
            scheduler,
            CHILD,
            PresentationFrame(phase="atomic", text="child"),
            now=0.2,
        )
    ) == []

    scheduler.advance_published(now=1.99)
    assert scheduler.take_published() == []
    scheduler.advance_published(now=2)

    assert _texts(scheduler.take_published()) == ["child"]


def test_owner_keeps_all_frames_until_idle_then_resumed_run_queues_at_tail() -> None:
    scheduler = _scheduler(idle_timeout_seconds=2, send_interval_seconds=0)
    scheduler.register_run(*ENTRY, now=0)
    scheduler.register_run(*CHILD, now=0)
    assert _texts(
        _publish(
            scheduler,
            ENTRY,
            PresentationFrame(phase="atomic", text="entry-1"),
            now=0.1,
        )
    ) == ["entry-1"]
    assert _texts(
        _publish(
            scheduler,
            CHILD,
            PresentationFrame(phase="atomic", text="child"),
            now=0.2,
        )
    ) == []
    scheduler.advance_published(now=2.1)
    assert _texts(scheduler.take_published()) == ["child"]

    assert _texts(
        _publish(
            scheduler,
            ENTRY,
            PresentationFrame(phase="atomic", text="entry-2"),
            now=2.2,
        )
    ) == []
    scheduler.finish_run(*CHILD, now=2.3)

    assert _texts(scheduler.take_published()) == ["entry-2"]


def test_idle_handoff_closes_stream_and_resume_starts_a_continuation() -> None:
    scheduler = _scheduler(idle_timeout_seconds=2, send_interval_seconds=0)
    scheduler.register_run(*ENTRY, now=0)
    scheduler.register_run(*CHILD, now=0)
    first = []
    first += _publish(
        scheduler,
        ENTRY,
        PresentationFrame(
            phase="start",
            text="<answer>",
            block_id="block-1",
            segment_end_text="</answer>",
        ),
        now=0.1,
    )
    first += _publish(
        scheduler,
        ENTRY,
        PresentationFrame(phase="delta", text="one", block_id="block-1"),
        now=0.2,
    )
    _publish(
        scheduler,
        CHILD,
        PresentationFrame(phase="atomic", text="child"),
        now=0.3,
    )
    scheduler.advance_published(now=2.2)
    switched = scheduler.take_published()

    assert _texts(first + switched) == ["<answer>", "one", "</answer>", "child"]
    assert [frame.phase for frame in switched] == ["finish", "atomic"]

    scheduler.finish_run(*CHILD, now=2.3)
    resumed = _publish(
        scheduler,
        ENTRY,
        PresentationFrame(phase="delta", text="two", block_id="block-1"),
        now=2.4,
    )
    assert _texts(resumed) == ["<answer>", "two"]
    assert resumed[0].phase == "start"
    assert resumed[0].continuation is True


def test_terminal_owner_immediately_switches_and_terminal_non_owner_drains() -> None:
    scheduler = _scheduler(idle_timeout_seconds=20, send_interval_seconds=0)
    scheduler.register_run(*ENTRY, now=0)
    scheduler.register_run(*CHILD, now=0)
    _publish(
        scheduler,
        CHILD,
        PresentationFrame(phase="atomic", text="child"),
        now=0.1,
    )
    scheduler.finish_run(*CHILD, now=0.2)
    scheduler.finish_run(*ENTRY, now=0.3)

    assert _texts(scheduler.take_published()) == ["child"]
    assert scheduler.all_runs_terminal
    assert scheduler.response_complete


def test_tool_like_atomic_frames_are_not_paired_or_reordered() -> None:
    scheduler = _scheduler(send_interval_seconds=0)
    scheduler.register_run(*ENTRY, now=0)
    frames = []
    frames += _publish(
        scheduler,
        ENTRY,
        PresentationFrame(phase="atomic", text="tool call"),
        now=0.1,
    )
    frames += _publish(
        scheduler,
        ENTRY,
        PresentationFrame(phase="atomic", text="progress"),
        now=0.2,
    )
    frames += _publish(
        scheduler,
        ENTRY,
        PresentationFrame(phase="atomic", text="tool result"),
        now=0.3,
    )

    assert _texts(frames) == ["tool call", "progress", "tool result"]


def test_batch_size_and_send_interval_only_delay_publication() -> None:
    scheduler = _scheduler(max_batch_kb=0.003, send_interval_seconds=1)
    scheduler.register_run(*ENTRY, now=0)
    first = _publish(
        scheduler,
        ENTRY,
        PresentationFrame(phase="atomic", text="aaa"),
        now=0,
    )
    second = _publish(
        scheduler,
        ENTRY,
        PresentationFrame(phase="atomic", text="bbb"),
        now=0.1,
    )
    assert _texts(first) == ["aaa"]
    assert second == []

    scheduler.advance_published(now=1)
    assert _texts(scheduler.take_published()) == ["bbb"]


def test_input_identity_is_thread_and_run_pair() -> None:
    scheduler = _scheduler()
    scheduler.register_run(*ENTRY, now=0)

    with pytest.raises(ValueError):
        _publish(
            scheduler,
            (ENTRY[0], "another-run"),
            PresentationFrame(phase="atomic", text="wrong"),
            now=0,
        )


def test_lifecycle_finishes_only_after_every_registered_run_is_terminal() -> None:
    scheduler = _scheduler(send_interval_seconds=0)
    scheduler.register_run(*ENTRY, now=0)
    scheduler.register_run(*CHILD, now=0)
    scheduler.finish_run(*ENTRY, now=0)

    with pytest.raises(RuntimeError):
        scheduler.finish(now=0)

    scheduler.finish_run(*CHILD, now=0)
    assert scheduler.finish(now=0) == []
