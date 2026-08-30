from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, replace

from agent_shell.response_stream_policy import ResponseStreamPolicy
from agent_shell.runtime.response_presentation import (
    PresentationFrame,
    ResponseEvent,
    ResponseModelCallBoundary,
    ResponsePresentationWriter,
    to_response_signal,
)


@dataclass(frozen=True, slots=True)
class ResponseEventInput:
    lifecycle_id: str
    origin_run_id: str
    origin_workflow_id: str
    event: ResponseEvent | ResponseModelCallBoundary
    text: str = ""
    segment_end_text: str = ""


@dataclass(slots=True)
class _ToolTransaction:
    lane_id: str
    turn_id: str
    call_id: str
    declaration: ResponseEvent | None = None
    declaration_text: str = ""
    outcome: ResponseEvent | None = None
    outcome_text: str = ""
    queued: bool = False


class LifecycleResponseScheduler:
    """Validate lifecycle input and serialize projected output through one writer."""

    def __init__(
        self,
        policy: ResponseStreamPolicy,
        *,
        lifecycle_id: str,
        origin_run_id: str,
        origin_workflow_id: str,
    ) -> None:
        self.policy = policy.model_copy(deep=True)
        self.lifecycle_id = lifecycle_id
        self.origin_run_id = origin_run_id
        self.origin_workflow_id = origin_workflow_id
        self._writer = ResponsePresentationWriter(self.policy)
        self._tools: dict[tuple[str, str, str], _ToolTransaction] = {}
        self._pending_frames: deque[PresentationFrame] = deque()
        self._published_frames: deque[PresentationFrame] = deque()
        self._origins: dict[str, str] = {
            origin_run_id: origin_workflow_id,
        }
        self._finished_origins: set[str] = set()
        self._wakeup = asyncio.Event()
        self._last_batch_at: float | None = None
        self._finished = False

    def register_origin(self, run_id: str, workflow_id: str) -> None:
        existing = self._origins.get(run_id)
        if existing is not None and existing != workflow_id:
            raise ValueError("response origin Run is already bound to another Workflow")
        if self._finished:
            return
        self._origins[run_id] = workflow_id
        self._finished_origins.discard(run_id)

    def accepting(self, run_id: str, workflow_id: str) -> bool:
        return (
            not self._finished
            and self._origins.get(run_id) == workflow_id
            and run_id not in self._finished_origins
        )

    def submit(self, item: ResponseEventInput, *, now: float) -> list[PresentationFrame]:
        if self._finished:
            return []
        self._writer.begin(now=now)
        self._validate_input(item)
        event = self._scoped_event(
            to_response_signal(item.event),
            run_id=item.origin_run_id,
        )
        if isinstance(event, ResponseModelCallBoundary):
            self._writer.handle_boundary(event)
        else:
            lane_id = self._writer.event_lane_id(event)
            self._writer.remember_lane(lane_id, event)
            if event.kind == "content":
                self._writer.handle_content(
                    event,
                    lane_id=lane_id,
                    text=item.text,
                    segment_end_text=item.segment_end_text,
                )
            elif event.kind == "tool":
                self._handle_tool(event, item.text, lane_id=lane_id)
            else:
                self._writer.queue_text(
                    lane_id,
                    item.text,
                    turn_id=self._writer.turn_id(event, lane_id),
                )
            if (
                event.terminal
            ):
                self._writer.mark_terminal(lane_id)
        self._writer.expire_owner(now)
        self._writer.drain()
        self._collect_output()
        return self._take_due_batch(now)

    def publish(self, item: ResponseEventInput, *, now: float) -> None:
        if not self.accepting(item.origin_run_id, item.origin_workflow_id):
            return
        self._published_frames.extend(self.submit(item, now=now))
        self._wakeup.set()

    def advance_published(self, *, now: float) -> None:
        if self._finished:
            return
        self._published_frames.extend(self.advance(now=now))

    def take_published(self) -> list[PresentationFrame]:
        output = list(self._published_frames)
        self._published_frames.clear()
        return output

    def clear_wakeup(self) -> None:
        self._wakeup.clear()

    async def wait_for_wakeup(self) -> None:
        await self._wakeup.wait()

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
        output = self._take_due_batch(now)
        self._wakeup.set()
        return output

    def finish_origin(
        self,
        run_id: str,
        workflow_id: str,
        *,
        now: float,
    ) -> None:
        if not self.accepting(run_id, workflow_id):
            return
        lane_prefix = self._lane_prefix(run_id)
        self._writer.begin(now=now)
        self._flush_terminal_tools(lane_prefix=lane_prefix)
        self._writer.finish_lanes(lane_prefix)
        self._writer.drain()
        self._collect_output()
        self._published_frames.extend(self._take_due_batch(now))
        self._finished_origins.add(run_id)
        self._wakeup.set()

    def abort_origin(
        self,
        run_id: str,
        workflow_id: str,
        *,
        now: float,
    ) -> None:
        if not self.accepting(run_id, workflow_id):
            return
        lane_prefix = self._lane_prefix(run_id)
        self._writer.begin(now=now)
        self._writer.abort_lanes(lane_prefix)
        self._tools = {
            key: value
            for key, value in self._tools.items()
            if not value.lane_id.startswith(lane_prefix)
        }
        self._writer.drain()
        self._collect_output()
        self._published_frames.extend(self._take_due_batch(now))
        self._wakeup.set()

    def abort(self) -> list[PresentationFrame]:
        self._writer.begin()
        self._writer.abort()
        self._tools.clear()
        self._collect_output()
        output = [*self._published_frames, *self._pending_frames]
        self._published_frames.clear()
        self._pending_frames.clear()
        self._last_batch_at = None
        return output

    def discard(self) -> None:
        self._writer.discard()
        self._tools.clear()
        self._pending_frames.clear()
        self._published_frames.clear()
        self._finished = True
        self._wakeup.set()

    @property
    def has_pending_output(self) -> bool:
        return bool(self._published_frames or self._pending_frames)

    def _validate_input(self, item: ResponseEventInput) -> None:
        if (
            item.lifecycle_id != self.lifecycle_id
            or self._origins.get(item.origin_run_id) != item.origin_workflow_id
            or item.origin_run_id in self._finished_origins
        ):
            raise ValueError("ResponseEventInput does not belong to this lifecycle scheduler")

    @staticmethod
    def _lane_prefix(run_id: str) -> str:
        return f"run:{run_id}|"

    def _scoped_event(
        self,
        event: ResponseEvent | ResponseModelCallBoundary,
        *,
        run_id: str,
    ) -> ResponseEvent | ResponseModelCallBoundary:
        prefix = self._lane_prefix(run_id)
        if isinstance(event, ResponseModelCallBoundary):
            return replace(
                event,
                source_key=prefix + (event.source_key or "unknown"),
            )
        source_key = event.source_key.strip() or "|".join(
            str(value or "")
            for value in (
                event.source_type,
                event.workflow_node_id,
                event.agent_profile_id,
                event.subagent_profile_id,
            )
        )
        return replace(event, source_key=prefix + source_key)

    def _handle_tool(
        self,
        event: ResponseEvent,
        text: str,
        *,
        lane_id: str,
    ) -> None:
        if event.tool_kind == "progress":
            self._writer.queue_text(
                lane_id,
                text,
                turn_id=self._writer.turn_id(event, lane_id),
            )
            return
        if event.tool_kind == "call":
            turn_id = self._writer.turn_id(event, lane_id)
            self._writer.note_non_content_successor(
                lane_id=lane_id,
                turn_id=turn_id,
                token=f"tool:{event.sequence}",
            )
            if event.phase not in {"end", "error"}:
                return
            call_id = event.tool_call_id
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
        call_id = event.tool_call_id
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

    def _flush_terminal_tools(self, *, lane_prefix: str = "") -> None:
        for transaction in self._tools.values():
            if (
                (not lane_prefix or transaction.lane_id.startswith(lane_prefix))
                and transaction.declaration is None
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
    "ResponseEvent",
    "ResponseEventInput",
    "ResponseModelCallBoundary",
]
