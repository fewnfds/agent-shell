from __future__ import annotations

from dataclasses import dataclass

from agent_shell.response_stream_policy import (
    ContentDeliveryPolicy,
    LiveWrapper,
    ResponseStreamPolicy,
)
from agent_shell.runtime.response_presentation import (
    PresentationFrame,
    ResponsePresentationWriter,
)
from agent_shell.runtime.output_projection import OutputProjector, WorkflowOutputProjector
from agent_shell.runtime.output_stream import ModelCallBoundary, OutputEvent


@dataclass(frozen=True, slots=True)
class ResponseEventInput:
    lifecycle_id: str
    origin_run_id: str
    origin_workflow_id: str
    event: OutputEvent | ModelCallBoundary


@dataclass(slots=True)
class _ToolTransaction:
    lane_id: str
    turn_id: str
    call_id: str
    declaration: OutputEvent | None = None
    outcome: OutputEvent | None = None
    queued: bool = False


class LifecycleResponseScheduler:
    """Authorize normalized input and route it to one response presentation writer."""

    def __init__(
        self,
        projector: OutputProjector | WorkflowOutputProjector,
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
        self._writer = ResponsePresentationWriter(projector, self.policy)
        self._source_overrides = {
            item.workflow_node_id: item.visibility
            for item in self.policy.source_overrides
        }
        self._tools: dict[tuple[str, str, str], _ToolTransaction] = {}
        self._last_upstream_at: float | None = None
        self._last_event_lane = ""
        self._quiet_notice_at: float | None = None
        self._quiet_announced = False
        self._pulse_last_at: dict[str, float] = {}
        self._pulse_due: dict[str, float] = {}

    def submit(self, item: ResponseEventInput, *, now: float) -> list[PresentationFrame]:
        self._writer.begin()
        self._validate_input(item)
        self._mark_upstream(now)
        event = item.event
        if isinstance(event, ModelCallBoundary):
            self._last_event_lane = self._writer.boundary_lane_id(event)
            self._writer.handle_boundary(event)
        else:
            lane_id = self._writer.event_lane_id(event)
            self._writer.remember_lane(lane_id, event)
            self._last_event_lane = lane_id
            if event.event_type in {"assistant_text", "reasoning"}:
                delivery = self._content_delivery(event)
                self._writer.handle_content(
                    event,
                    lane_id=lane_id,
                    now=now,
                    delivery_policy=delivery,
                )
                if event.phase == "delta" and delivery.delivery == "activity":
                    self._record_hidden_progress(lane_id, now=now)
            elif event.event_type in {
                "tool_call",
                "tool_result",
                "tool_error",
                "tool_progress",
            }:
                self._handle_tool(event, lane_id=lane_id, now=now)
            elif event.event_type == "custom":
                self._handle_custom(event, lane_id=lane_id)
            elif event.event_type in {"lifecycle", "subagent"}:
                self._handle_lifecycle(event, lane_id=lane_id)
            if (
                event.event_type == "lifecycle"
                and event.workflow_node_id
                and event.phase in {"end", "error"}
            ):
                self._writer.mark_terminal(lane_id)
        self._writer.expire_successor(now)
        self._writer.drain()
        return self._writer.take_output()

    def advance(self, *, now: float) -> list[PresentationFrame]:
        self._writer.begin()
        self._writer.expire_successor(now)
        self._emit_due_pulses(now)
        quiet_deadline = self._quiet_deadline()
        if quiet_deadline is not None and now >= quiet_deadline:
            lane_id = self._writer.preferred_waiting_lane(self._last_event_lane)
            self._writer.close_for_quiet()
            self._writer.queue_activity(lane_id, "waiting")
            self._quiet_announced = True
            self._quiet_notice_at = now
        self._writer.drain()
        return self._writer.take_output()

    def next_deadline(self) -> float | None:
        deadlines = [
            value
            for value in (
                self._writer.next_deadline(),
                self._quiet_deadline(),
                min(self._pulse_due.values()) if self._pulse_due else None,
            )
            if value is not None
        ]
        return min(deadlines) if deadlines else None

    def finish(self, *, now: float) -> list[PresentationFrame]:
        self._writer.begin()
        self._writer.finish_content()
        self._queue_unresolved_tools()
        self._writer.drain()
        return self._writer.take_output()

    def abort(self) -> list[PresentationFrame]:
        self._writer.begin()
        self._writer.abort()
        self._tools.clear()
        self._pulse_due.clear()
        return self._writer.take_output()

    def discard(self) -> None:
        self._writer.discard()
        self._tools.clear()
        self._pulse_due.clear()

    def _validate_input(self, item: ResponseEventInput) -> None:
        if (
            item.lifecycle_id != self.lifecycle_id
            or item.origin_run_id != self.origin_run_id
            or item.origin_workflow_id != self.origin_workflow_id
        ):
            raise ValueError("ResponseEventInput does not belong to this lifecycle scheduler")

    def _mark_upstream(self, now: float) -> None:
        self._last_upstream_at = now
        self._quiet_notice_at = None
        self._quiet_announced = False

    def _handle_tool(self, event: OutputEvent, *, lane_id: str, now: float) -> None:
        delivery = self._effective_visibility(event, self.policy.tools.delivery)
        if event.event_type == "tool_progress":
            if delivery in {"paired", "activity"}:
                if event.phase == "start" and self.policy.activity.announce_start:
                    self._writer.queue_activity(lane_id, "started")
                elif event.phase == "delta":
                    self._record_hidden_progress(lane_id, now=now)
            return
        if event.event_type == "tool_call":
            turn_id = self._writer.turn_id(event, lane_id)
            self._writer.note_non_content_successor(
                lane_id=lane_id,
                turn_id=turn_id,
                token=f"tool:{event.sequence}",
                now=now,
            )
            if event.phase not in {"end", "error"}:
                return
            if delivery == "activity":
                self._writer.queue_activity(lane_id, "started")
                return
            if delivery != "paired":
                return
            call_id = event.values.get("tool_call_id", "")
            if not call_id:
                self._writer.queue_events(lane_id, (event,), turn_id=turn_id)
                return
            transaction = self._tools.setdefault(
                (lane_id, turn_id, call_id),
                _ToolTransaction(lane_id, turn_id, call_id),
            )
            transaction.declaration = event
            self._queue_tool_if_ready(transaction)
            return
        if delivery == "activity":
            self._writer.queue_activity(
                lane_id,
                "failed" if event.event_type == "tool_error" else "completed",
            )
            return
        if delivery != "paired":
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
        self._queue_tool_if_ready(transaction)

    def _handle_custom(self, event: OutputEvent, *, lane_id: str) -> None:
        delivery = self._effective_visibility(
            event,
            self.policy.workflow_custom.delivery,
        )
        if delivery == "complete":
            self._writer.queue_events(lane_id, (event,))
        elif delivery == "activity":
            self._writer.queue_activity(lane_id, "producing")

    def _handle_lifecycle(self, event: OutputEvent, *, lane_id: str) -> None:
        configured = (
            self.policy.subagent_lifecycle.delivery
            if event.event_type == "subagent"
            else self.policy.workflow_lifecycle.delivery
        )
        delivery = self._effective_visibility(event, configured)
        if delivery == "complete":
            self._writer.queue_events(lane_id, (event,))
            return
        if delivery != "activity":
            return
        if event.phase == "start":
            if self.policy.activity.announce_start:
                self._writer.queue_activity(lane_id, "started")
            return
        status = event.values.get("status", event.message)
        self._writer.queue_activity(
            lane_id,
            "failed" if event.phase == "error" else status or "completed",
        )

    def _content_delivery(self, event: OutputEvent) -> ContentDeliveryPolicy:
        if event.source_type == "subagent":
            configured = ContentDeliveryPolicy(
                delivery=self.policy.subagent_content.delivery,
                live_wrapper=LiveWrapper(),
            )
        elif event.event_type == "reasoning":
            configured = self.policy.reasoning
        else:
            configured = self.policy.assistant_text
        visibility = self._source_overrides.get(event.workflow_node_id)
        if visibility == "hidden":
            return ContentDeliveryPolicy(delivery="hidden")
        if visibility == "activity_only":
            return ContentDeliveryPolicy(delivery="activity")
        return configured

    def _effective_visibility(self, event: OutputEvent, configured: str) -> str:
        visibility = self._source_overrides.get(event.workflow_node_id)
        if visibility == "hidden":
            return "hidden"
        if visibility == "activity_only":
            return "activity"
        return configured

    def _queue_tool_if_ready(self, transaction: _ToolTransaction) -> None:
        if (
            transaction.queued
            or transaction.declaration is None
            or transaction.outcome is None
        ):
            return
        transaction.queued = True
        self._writer.queue_events(
            transaction.lane_id,
            (transaction.declaration, transaction.outcome),
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

    def _queue_unresolved_tools(self) -> None:
        sequence = max(
            (
                transaction.declaration.sequence
                for transaction in self._tools.values()
                if transaction.declaration is not None
            ),
            default=0,
        )
        for transaction in self._tools.values():
            if (
                transaction.declaration is None
                and transaction.outcome is not None
                and not transaction.queued
            ):
                transaction.queued = True
                self._writer.queue_events(
                    transaction.lane_id,
                    (transaction.outcome,),
                    turn_id=transaction.turn_id,
                )
                continue
            if transaction.declaration is None or transaction.outcome is not None:
                continue
            sequence += 1
            declaration = transaction.declaration
            transaction.outcome = OutputEvent(
                event_type="tool_error",
                phase="error",
                sequence=sequence,
                timestamp=declaration.timestamp,
                namespace=declaration.namespace,
                agent_name=declaration.agent_name,
                node=declaration.node,
                source_type=declaration.source_type,
                workflow_node_id=declaration.workflow_node_id,
                agent_profile_id=declaration.agent_profile_id,
                subagent_profile_id=declaration.subagent_profile_id,
                message="Tool execution did not produce a terminal outcome.",
                values={
                    "tool_name": declaration.values.get("tool_name", ""),
                    "tool_call_id": transaction.call_id,
                    "status": "unresolved",
                    "error_code": "tool_outcome_unresolved",
                },
                source_key=declaration.source_key,
                cycle_key=declaration.cycle_key,
            )
            self._queue_tool_if_ready(transaction)

    def _record_hidden_progress(self, lane_id: str, *, now: float) -> None:
        interval = self.policy.activity.hidden_delta_pulse_seconds
        if interval is None:
            return
        last = self._pulse_last_at.get(lane_id)
        if last is None or now - last >= interval:
            self._writer.queue_activity(lane_id, "producing")
            self._pulse_last_at[lane_id] = now
            self._pulse_due.pop(lane_id, None)
            return
        self._pulse_due[lane_id] = last + interval

    def _emit_due_pulses(self, now: float) -> None:
        for lane_id, deadline in tuple(self._pulse_due.items()):
            if now < deadline:
                continue
            self._pulse_due.pop(lane_id, None)
            self._pulse_last_at[lane_id] = now
            self._writer.queue_activity(lane_id, "producing")

    def _quiet_deadline(self) -> float | None:
        after = self.policy.activity.quiet_notice_after_seconds
        if after is None or self._last_upstream_at is None:
            return None
        if not self._quiet_announced:
            return self._last_upstream_at + after
        repeat = self.policy.activity.quiet_notice_repeat_seconds
        if repeat is None or self._quiet_notice_at is None:
            return None
        return self._quiet_notice_at + repeat


__all__ = [
    "LifecycleResponseScheduler",
    "PresentationFrame",
    "ResponseEventInput",
]
