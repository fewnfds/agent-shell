from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from agent_shell.response_stream_policy import ResponseStreamPolicy
from agent_shell.runtime.output_projection import EventOutputProjectionStream
from agent_shell.runtime.response_presentation import (
    PresentationFrame,
    ResponsePresentationWriter,
)
from agent_shell.runtime.output_stream import ModelCallBoundary, OutputEvent


@dataclass(frozen=True, slots=True)
class ResponseEventInput:
    lifecycle_id: str
    origin_run_id: str
    origin_workflow_id: str
    event: OutputEvent | ModelCallBoundary
    text: str = ""
    segment_end_text: str = ""


@dataclass(slots=True)
class _ToolTransaction:
    lane_id: str
    turn_id: str
    call_id: str
    declaration: OutputEvent | None = None
    declaration_text: str = ""
    outcome: OutputEvent | None = None
    outcome_text: str = ""
    queued: bool = False


class LifecycleResponseScheduler:
    """Validate lifecycle input and serialize projected output through one writer."""

    def __init__(
        self,
        policy: ResponseStreamPolicy,
        *,
        projection_stream: EventOutputProjectionStream,
        lifecycle_id: str,
        origin_run_id: str,
        origin_workflow_id: str,
    ) -> None:
        self.policy = policy.model_copy(deep=True)
        self.lifecycle_id = lifecycle_id
        self.origin_run_id = origin_run_id
        self.origin_workflow_id = origin_workflow_id
        self.projection_stream = projection_stream
        self._writer = ResponsePresentationWriter(self.policy)
        self._tools: dict[tuple[str, str, str], _ToolTransaction] = {}
        self._pending_frames: deque[PresentationFrame] = deque()
        self._last_batch_at: float | None = None
        self._finished = False

    def submit(self, item: ResponseEventInput, *, now: float) -> list[PresentationFrame]:
        self._writer.begin(now=now)
        self._validate_input(item)
        event = item.event
        if isinstance(event, ModelCallBoundary):
            self._writer.handle_boundary(event)
        else:
            lane_id = self._writer.event_lane_id(event)
            self._writer.remember_lane(lane_id, event)
            if event.event_type in {"assistant_text", "reasoning"}:
                self._writer.handle_content(
                    event,
                    lane_id=lane_id,
                    text=item.text,
                    segment_end_text=item.segment_end_text,
                )
            elif event.event_type in {
                "tool_call",
                "tool_result",
                "tool_error",
                "tool_progress",
            }:
                self._handle_tool(event, item.text, lane_id=lane_id)
            else:
                self._writer.queue_text(
                    lane_id,
                    item.text,
                    turn_id=self._writer.turn_id(event, lane_id),
                )
            if (
                event.event_type == "lifecycle"
                and event.workflow_node_id
                and event.phase in {"end", "error"}
            ):
                self._writer.mark_terminal(lane_id)
        self._writer.expire_owner(now)
        self._writer.drain()
        self._collect_output()
        return self._take_due_batch(now)

    def advance(self, *, now: float) -> list[PresentationFrame]:
        self._writer.begin(now=now)
        if not self._finished:
            self._writer.expire_owner(now)
            self._writer.drain()
        self._collect_output()
        return self._take_due_batch(now)

    def next_deadline(self) -> float | None:
        deadlines = [
            value
            for value in (
                self._writer.next_deadline(),
                self._batch_deadline(),
            )
            if value is not None
        ]
        return min(deadlines) if deadlines else None

    def finish(self, *, now: float) -> list[PresentationFrame]:
        self._writer.begin(now=now)
        self._writer.finish_content()
        self._flush_terminal_tools()
        self._writer.drain()
        self._collect_output()
        self._finished = True
        return self._take_due_batch(now)

    def abort(self) -> list[PresentationFrame]:
        self._writer.begin()
        self._writer.abort()
        self._tools.clear()
        self._collect_output()
        output = list(self._pending_frames)
        self._pending_frames.clear()
        self._last_batch_at = None
        return output

    def discard(self) -> None:
        self._writer.discard()
        self._tools.clear()
        self._pending_frames.clear()

    @property
    def has_pending_output(self) -> bool:
        return bool(self._pending_frames)

    def _validate_input(self, item: ResponseEventInput) -> None:
        if (
            item.lifecycle_id != self.lifecycle_id
            or item.origin_run_id != self.origin_run_id
            or item.origin_workflow_id != self.origin_workflow_id
        ):
            raise ValueError("ResponseEventInput does not belong to this lifecycle scheduler")

    def _handle_tool(
        self,
        event: OutputEvent,
        text: str,
        *,
        lane_id: str,
    ) -> None:
        if event.event_type == "tool_progress":
            self._writer.queue_text(
                lane_id,
                text,
                turn_id=self._writer.turn_id(event, lane_id),
            )
            return
        if event.event_type == "tool_call":
            turn_id = self._writer.turn_id(event, lane_id)
            self._writer.note_non_content_successor(
                lane_id=lane_id,
                turn_id=turn_id,
                token=f"tool:{event.sequence}",
            )
            if event.phase not in {"end", "error"}:
                return
            call_id = event.values.get("tool_call_id", "")
            if not call_id:
                self._writer.queue_text(lane_id, text, turn_id=turn_id)
                return
            transaction = self._tools.setdefault(
                (lane_id, turn_id, call_id),
                _ToolTransaction(lane_id, turn_id, call_id),
            )
            transaction.declaration = event
            transaction.declaration_text = text
            self._queue_tool_if_ready(transaction)
            return
        call_id = event.values.get("tool_call_id", "")
        transaction = self._find_tool_transaction(lane_id, call_id)
        if transaction is None:
            turn_id = self._writer.turn_id(event, lane_id)
            transaction = self._tools.setdefault(
                (lane_id, turn_id, call_id),
                _ToolTransaction(lane_id, turn_id, call_id),
            )
        transaction.outcome = event
        transaction.outcome_text = text
        self._queue_tool_if_ready(transaction)

    def _queue_tool_if_ready(self, transaction: _ToolTransaction) -> None:
        if (
            transaction.queued
            or transaction.declaration is None
            or transaction.outcome is None
        ):
            return
        transaction.queued = True
        self._writer.queue_text(
            transaction.lane_id,
            transaction.declaration_text + transaction.outcome_text,
            turn_id=transaction.turn_id,
        )

    def _find_tool_transaction(
        self,
        lane_id: str,
        call_id: str,
    ) -> _ToolTransaction | None:
        candidates = [
            transaction
            for (candidate_lane, _turn_id, candidate_call), transaction
            in self._tools.items()
            if candidate_lane == lane_id
            and candidate_call == call_id
            and transaction.outcome is None
        ]
        return candidates[-1] if candidates else None

    def _flush_terminal_tools(self) -> None:
        for transaction in self._tools.values():
            if (
                transaction.declaration is None
                and transaction.outcome is not None
                and not transaction.queued
            ):
                transaction.queued = True
                self._writer.queue_text(
                    transaction.lane_id,
                    transaction.outcome_text,
                    turn_id=transaction.turn_id,
                )
                continue

    def _collect_output(self) -> None:
        self._pending_frames.extend(self._writer.take_output())

    def _take_due_batch(self, now: float) -> list[PresentationFrame]:
        if not self._pending_frames:
            return []
        deadline = self._batch_deadline()
        if deadline is not None and now < deadline:
            return []

        maximum_bytes = self.policy.queue.max_batch_kb * 1024
        batch: list[PresentationFrame] = []
        batch_bytes = 0
        while self._pending_frames:
            frame = self._pending_frames[0]
            frame_bytes = len(frame.text.encode("utf-8"))
            if batch and batch_bytes + frame_bytes > maximum_bytes:
                break
            batch.append(self._pending_frames.popleft())
            batch_bytes += frame_bytes

        if any(frame.text for frame in batch):
            self._last_batch_at = now
        return batch

    def _batch_deadline(self) -> float | None:
        if not self._pending_frames:
            return None
        if self._last_batch_at is None:
            return 0.0
        return self._last_batch_at + self.policy.queue.send_interval_seconds

__all__ = [
    "LifecycleResponseScheduler",
    "PresentationFrame",
    "ResponseEventInput",
]
