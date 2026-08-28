from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from typing import Literal

from agent_shell.response_stream_policy import (
    ContentDeliveryPolicy,
    LiveWrapper,
    ResponseStreamPolicy,
)
from agent_shell.runtime.output_projection import OutputProjector, WorkflowOutputProjector
from agent_shell.runtime.output_stream import ModelCallBoundary, OutputEvent


FrameKind = Literal["content", "activity"]
FramePhase = Literal["start", "delta", "end", "atomic", "abort"]


@dataclass(frozen=True, slots=True)
class PresentationFrame:
    kind: FrameKind
    phase: FramePhase
    text: str
    lane_id: str
    source_type: str = ""
    workflow_node_id: str = ""
    agent_turn_id: str = ""
    protocol_block_id: str = ""
    continuation: bool = False
    close_reason: str = ""
    sequence: int = 0


@dataclass(slots=True)
class _LaneMeta:
    source_type: str = ""
    workflow_node_id: str = ""
    agent_name: str = ""
    node: str = ""


@dataclass(slots=True)
class _ContentBlock:
    block_id: str
    lane_id: str
    turn_id: str
    event_type: str
    delivery: str
    wrapper: LiveWrapper
    last_event: OutputEvent
    delta_text: str = ""
    pending_fragments: list[str] = field(default_factory=list)
    snapshot_text: str = ""
    strong_closed: bool = False
    queued: bool = False
    segment_count: int = 0

    @property
    def canonical_text(self) -> str:
        return self.delta_text if self.delta_text else self.snapshot_text


@dataclass(slots=True)
class _WorkItem:
    lane_id: str
    kind: Literal["live", "events", "activity"]
    turn_id: str = ""
    block_id: str = ""
    events: tuple[OutputEvent, ...] = ()
    text: str = ""


class ResponsePresentationWriter:
    """Own lane scheduling, presentation segments, and the single response writer."""

    def __init__(
        self,
        projector: OutputProjector | WorkflowOutputProjector,
        policy: ResponseStreamPolicy,
    ) -> None:
        self._projector = projector
        self._policy = policy
        self._lanes: dict[str, deque[_WorkItem]] = {}
        self._ready_order: deque[str] = deque()
        self._ready_set: set[str] = set()
        self._lane_meta: dict[str, _LaneMeta] = {}
        self._lane_turns: dict[str, str] = {}
        self._terminal_lanes: set[str] = set()
        self._queued_announced: set[str] = set()
        self._blocks: dict[str, _ContentBlock] = {}
        self._open_block_id: str | None = None
        self._successor_order: list[str] = []
        self._successor_deadline: float | None = None
        self._strict_owner: str | None = None
        self._frame_sequence = 0
        self._last_emitted_activity_text = ""
        self._has_public_text = False
        self._public_ends_newline = True
        self._out: list[PresentationFrame] = []

    def begin(self) -> None:
        if self._out:
            raise RuntimeError("presentation output was not collected")

    def take_output(self) -> list[PresentationFrame]:
        output = self._out
        self._out = []
        return output

    def remember_lane(self, lane_id: str, event: OutputEvent) -> None:
        self._lane_meta[lane_id] = _LaneMeta(
            source_type=event.source_type,
            workflow_node_id=event.workflow_node_id,
            agent_name=event.agent_name,
            node=event.node,
        )

    def handle_boundary(self, event: ModelCallBoundary) -> None:
        lane_id = self.boundary_lane_id(event)
        if event.phase == "start":
            previous = self._lane_turns.get(lane_id)
            if previous and previous != event.run_key and self._open_block_id is not None:
                open_block = self._blocks[self._open_block_id]
                if open_block.lane_id == lane_id:
                    self._close_open("next_turn")
            self._lane_turns[lane_id] = event.run_key
            return
        self._close_turn_blocks(lane_id, event.run_key)
        if self._lane_turns.get(lane_id) == event.run_key:
            self._lane_turns.pop(lane_id, None)

    def handle_content(
        self,
        event: OutputEvent,
        *,
        lane_id: str,
        now: float,
        delivery_policy: ContentDeliveryPolicy,
    ) -> None:
        if self._is_media(event):
            if delivery_policy.delivery == "complete":
                self.queue_events(lane_id, (event,))
            elif delivery_policy.delivery == "activity":
                self.queue_activity(lane_id, "completed")
            return

        block_id = self._block_id(event, lane_id)
        turn_id = self.turn_id(event, lane_id)
        block = self._blocks.get(block_id)
        if block is None:
            block = _ContentBlock(
                block_id=block_id,
                lane_id=lane_id,
                turn_id=turn_id,
                event_type=event.event_type,
                delivery=delivery_policy.delivery,
                wrapper=delivery_policy.live_wrapper.model_copy(deep=True),
                last_event=event,
            )
            self._blocks[block_id] = block
        block.last_event = event

        if self._is_successor(block):
            self._note_successor(block_id, now=now)

        if event.phase == "start":
            if block.delivery == "activity" and self._policy.activity.announce_start:
                self.queue_activity(lane_id, "started")
            return
        if event.phase == "delta":
            if event.message:
                block.delta_text += event.message
            if block.delivery == "live" and event.message:
                if self._open_block_id == block_id:
                    self._emit(
                        "content",
                        "delta",
                        event.message,
                        block,
                        continuation=block.segment_count > 1,
                    )
                    if self._successor_order:
                        self._successor_deadline = (
                            now + self._policy.queue.successor_grace_seconds
                        )
                else:
                    block.pending_fragments.append(event.message)
                    if block_id not in self._successor_order:
                        self._queue_live_block(block)
            return
        if event.phase not in {"end", "error"}:
            return
        block.snapshot_text = event.message
        block.strong_closed = True
        if block.delivery == "live":
            if not block.delta_text and block.snapshot_text:
                block.pending_fragments.append(block.snapshot_text)
            if self._open_block_id == block_id:
                self._close_open("protocol_finish")
            elif block.pending_fragments and block_id not in self._successor_order:
                self._queue_live_block(block)
        elif block.delivery == "complete" and block.canonical_text:
            complete = replace(event, message=block.canonical_text)
            self.queue_events(lane_id, (complete,), turn_id=turn_id)
        elif block.delivery == "activity":
            self.queue_activity(lane_id, "completed")

    def note_non_content_successor(
        self,
        *,
        lane_id: str,
        turn_id: str,
        token: str,
        now: float,
    ) -> None:
        if self._open_block_id is None:
            return
        current = self._blocks[self._open_block_id]
        if current.lane_id == lane_id and current.turn_id == turn_id:
            self._note_successor(token, now=now)

    def expire_successor(self, now: float) -> None:
        if self._successor_deadline is None or now < self._successor_deadline:
            return
        self._successor_deadline = None
        if self._open_block_id is not None:
            self._close_open("successor_grace")

    def next_deadline(self) -> float | None:
        return self._successor_deadline

    def preferred_waiting_lane(self, fallback: str) -> str:
        if self._open_block_id is not None:
            lane_id = self._blocks[self._open_block_id].lane_id
        else:
            lane_id = self._strict_owner or fallback or "workflow"
        meta = self._lane_meta.get(lane_id)
        if (
            meta is not None
            and self._policy.source_overrides
            and any(
                item.workflow_node_id == meta.workflow_node_id
                and item.visibility == "hidden"
                for item in self._policy.source_overrides
            )
        ):
            return "workflow"
        return lane_id

    def close_for_quiet(self) -> None:
        if self._open_block_id is not None:
            self._close_open("quiet")

    def queue_events(
        self,
        lane_id: str,
        events: tuple[OutputEvent, ...],
        *,
        turn_id: str = "",
    ) -> None:
        self._enqueue(
            _WorkItem(
                lane_id=lane_id,
                kind="events",
                turn_id=turn_id,
                events=events,
            )
        )

    def queue_activity(self, lane_id: str, status: str) -> None:
        self._enqueue(
            _WorkItem(
                lane_id=lane_id,
                kind="activity",
                text=self._activity_text(lane_id, status),
            )
        )

    def mark_terminal(self, lane_id: str) -> None:
        self._terminal_lanes.add(lane_id)

    def finish_content(self) -> None:
        self._successor_deadline = None
        if self._open_block_id is not None:
            self._close_open("run_terminal")
        for block in self._blocks.values():
            if block.strong_closed:
                continue
            block.strong_closed = True
            if block.delivery == "live":
                self._queue_live_block(block)
            elif block.delivery == "complete" and block.canonical_text:
                event = replace(
                    block.last_event,
                    phase="end",
                    message=block.canonical_text,
                )
                self.queue_events(
                    block.lane_id,
                    (event,),
                    turn_id=block.turn_id,
                )
        self._strict_owner = None

    def abort(self) -> None:
        if self._open_block_id is not None:
            self._close_open("abort", phase="abort")
        self._clear_pending()

    def discard(self) -> None:
        self.begin()
        self._clear_pending()
        self._out.clear()

    def drain(self) -> None:
        while self._open_block_id is None:
            lane_id = self._next_lane()
            if lane_id is None:
                return
            queue = self._lanes[lane_id]
            item = queue.popleft()
            self._queued_announced.discard(lane_id)
            if item.kind == "live":
                self._run_live(item)
            elif item.kind == "events":
                text = "".join(
                    rendered
                    for event in item.events
                    if (rendered := self._projector.render(event))
                )
                if text:
                    self._emit_atomic("content", text, lane_id, item.turn_id)
            else:
                self._emit_atomic("activity", item.text, lane_id, item.turn_id)

            if queue:
                same_turn = bool(
                    item.turn_id
                    and queue[0].turn_id
                    and queue[0].turn_id == item.turn_id
                )
                self._ready(
                    lane_id,
                    front=(
                        self._policy.queue.mode == "strict_source" or same_turn
                    ),
                )
            elif lane_id in self._terminal_lanes and self._strict_owner == lane_id:
                self._strict_owner = None
            if self._open_block_id is not None:
                return

    def turn_id(self, event: OutputEvent, lane_id: str) -> str:
        if event.stream_id and ":" in event.stream_id:
            return event.stream_id.rsplit(":", 1)[0]
        return self._lane_turns.get(lane_id, "")

    @staticmethod
    def event_lane_id(event: OutputEvent) -> str:
        source_key = event.source_key.strip()
        if not source_key:
            source_key = "|".join(
                str(item or "")
                for item in (
                    event.source_type,
                    event.workflow_node_id,
                    event.agent_profile_id,
                    event.subagent_profile_id,
                )
            )
        cycle_key = event.cycle_key.strip() or event.namespace.strip() or "root"
        return f"{source_key}|{cycle_key}"

    @staticmethod
    def boundary_lane_id(event: ModelCallBoundary) -> str:
        return f"{event.source_key or 'unknown'}|{event.cycle_key or 'root'}"

    def _close_turn_blocks(self, lane_id: str, turn_id: str) -> None:
        if self._open_block_id is not None:
            open_block = self._blocks[self._open_block_id]
            if open_block.lane_id == lane_id and open_block.turn_id == turn_id:
                open_block.strong_closed = True
                self._close_open("message_finish")
        for block in self._blocks.values():
            if (
                block.lane_id != lane_id
                or block.turn_id != turn_id
                or block.strong_closed
            ):
                continue
            block.strong_closed = True
            if block.delivery == "live":
                self._queue_live_block(block)
            elif block.delivery == "complete" and block.canonical_text:
                complete = replace(
                    block.last_event,
                    phase="end",
                    message=block.canonical_text,
                )
                self.queue_events(lane_id, (complete,), turn_id=turn_id)
        self._activate_successors(prefer_lane=lane_id)

    def _queue_live_block(self, block: _ContentBlock) -> None:
        if block.queued or not block.pending_fragments:
            return
        block.queued = True
        self._enqueue(
            _WorkItem(
                lane_id=block.lane_id,
                kind="live",
                turn_id=block.turn_id,
                block_id=block.block_id,
            )
        )

    def _enqueue(self, item: _WorkItem) -> None:
        queue = self._lanes.setdefault(item.lane_id, deque())
        was_empty = not queue
        if (
            was_empty
            and self._writer_blocks(item.lane_id)
            and item.kind != "activity"
            and self._policy.activity.announce_queued
            and item.lane_id not in self._queued_announced
        ):
            queue.append(
                _WorkItem(
                    lane_id=item.lane_id,
                    kind="activity",
                    text=self._activity_text(item.lane_id, "queued"),
                )
            )
            self._queued_announced.add(item.lane_id)
        queue.append(item)
        if was_empty:
            self._ready(item.lane_id)

    def _ready(self, lane_id: str, *, front: bool = False) -> None:
        if lane_id in self._ready_set:
            return
        if front:
            self._ready_order.appendleft(lane_id)
        else:
            self._ready_order.append(lane_id)
        self._ready_set.add(lane_id)

    def _next_lane(self) -> str | None:
        if self._policy.queue.mode == "strict_source" and self._strict_owner is not None:
            owner = self._strict_owner
            queue = self._lanes.get(owner)
            if queue:
                self._remove_ready(owner)
                return owner
            if owner in self._terminal_lanes:
                self._strict_owner = None
            else:
                return None
        while self._ready_order:
            lane_id = self._ready_order.popleft()
            self._ready_set.discard(lane_id)
            if not self._lanes.get(lane_id):
                continue
            if (
                self._policy.queue.mode == "strict_source"
                and self._reservable_lane(lane_id)
            ):
                self._strict_owner = lane_id
            return lane_id
        return None

    def _remove_ready(self, lane_id: str) -> None:
        if lane_id not in self._ready_set:
            return
        self._ready_set.discard(lane_id)
        self._ready_order = deque(item for item in self._ready_order if item != lane_id)

    def _run_live(self, item: _WorkItem) -> None:
        block = self._blocks[item.block_id]
        block.queued = False
        if not block.pending_fragments:
            return
        continuation = block.segment_count > 0
        block.segment_count += 1
        prefix = (
            f"[Continued: {self._source_label(block.lane_id)}]\n"
            if continuation
            else ""
        )
        self._emit(
            "content",
            "start",
            prefix + block.wrapper.start,
            block,
            continuation=continuation,
        )
        body = "".join(block.pending_fragments)
        block.pending_fragments.clear()
        if body:
            self._emit(
                "content",
                "delta",
                body,
                block,
                continuation=continuation,
            )
        self._open_block_id = block.block_id
        if block.strong_closed:
            self._close_open("protocol_finish")

    def _close_open(
        self,
        reason: str,
        *,
        phase: FramePhase = "end",
    ) -> None:
        block_id = self._open_block_id
        if block_id is None:
            return
        block = self._blocks[block_id]
        self._emit(
            "content",
            phase,
            block.wrapper.end,
            block,
            continuation=block.segment_count > 1,
            close_reason=reason,
        )
        self._open_block_id = None
        self._activate_successors(prefer_lane=block.lane_id)

    def _is_successor(self, block: _ContentBlock) -> bool:
        if self._open_block_id is None or self._open_block_id == block.block_id:
            return False
        current = self._blocks[self._open_block_id]
        return current.lane_id == block.lane_id and current.turn_id == block.turn_id

    def _note_successor(self, token: str, *, now: float) -> None:
        if token not in self._successor_order:
            self._successor_order.append(token)
        self._successor_deadline = now + self._policy.queue.successor_grace_seconds
        self.expire_successor(now)

    def _activate_successors(self, *, prefer_lane: str) -> None:
        tokens = self._successor_order
        self._successor_order = []
        self._successor_deadline = None
        for token in tokens:
            block = self._blocks.get(token)
            if block is not None:
                self._queue_live_block(block)
        if self._lanes.get(prefer_lane):
            self._remove_ready(prefer_lane)
            self._ready(prefer_lane, front=True)

    def _writer_blocks(self, lane_id: str) -> bool:
        if self._open_block_id is not None:
            return self._blocks[self._open_block_id].lane_id != lane_id
        return self._strict_owner is not None and self._strict_owner != lane_id

    def _reservable_lane(self, lane_id: str) -> bool:
        meta = self._lane_meta.get(lane_id)
        return bool(
            meta is not None
            and meta.workflow_node_id
            and meta.source_type in {"agent", "subagent", "script"}
        )

    def _source_label(self, lane_id: str) -> str:
        meta = self._lane_meta.get(lane_id, _LaneMeta())
        label = meta.agent_name or meta.workflow_node_id or meta.node or "workflow"
        return (
            " ".join(label.replace("[", "").replace("]", "").splitlines()).strip()
            or "workflow"
        )

    def _activity_text(self, lane_id: str, status: str) -> str:
        return f"[Activity] {self._source_label(lane_id)}: {status}\n"

    def _emit_atomic(
        self,
        kind: FrameKind,
        text: str,
        lane_id: str,
        turn_id: str = "",
    ) -> None:
        if not text:
            return
        if kind == "activity":
            if text == self._last_emitted_activity_text:
                return
            self._last_emitted_activity_text = text
            if self._has_public_text and not self._public_ends_newline:
                text = "\n" + text
        else:
            self._last_emitted_activity_text = ""
        self._has_public_text = True
        self._public_ends_newline = text.endswith("\n")
        self._frame_sequence += 1
        meta = self._lane_meta.get(lane_id, _LaneMeta())
        self._out.append(
            PresentationFrame(
                kind=kind,
                phase="atomic",
                text=text,
                lane_id=lane_id,
                source_type=meta.source_type,
                workflow_node_id=meta.workflow_node_id,
                agent_turn_id=turn_id,
                sequence=self._frame_sequence,
            )
        )

    def _emit(
        self,
        kind: FrameKind,
        phase: FramePhase,
        text: str,
        block: _ContentBlock,
        *,
        continuation: bool,
        close_reason: str = "",
    ) -> None:
        if not text and phase not in {"start", "end", "abort"}:
            return
        self._last_emitted_activity_text = ""
        if text:
            self._has_public_text = True
            self._public_ends_newline = text.endswith("\n")
        self._frame_sequence += 1
        meta = self._lane_meta.get(block.lane_id, _LaneMeta())
        self._out.append(
            PresentationFrame(
                kind=kind,
                phase=phase,
                text=text,
                lane_id=block.lane_id,
                source_type=meta.source_type,
                workflow_node_id=meta.workflow_node_id,
                agent_turn_id=block.turn_id,
                protocol_block_id=block.block_id,
                continuation=continuation,
                close_reason=close_reason,
                sequence=self._frame_sequence,
            )
        )

    @staticmethod
    def _block_id(event: OutputEvent, lane_id: str) -> str:
        return f"{lane_id}|{event.stream_id or f'atomic:{event.sequence}'}"

    @staticmethod
    def _is_media(event: OutputEvent) -> bool:
        return (
            isinstance(event.data, dict)
            and event.data.get("type") in {"image", "audio", "video", "file"}
        )

    def _clear_pending(self) -> None:
        self._lanes.clear()
        self._ready_order.clear()
        self._ready_set.clear()
        self._blocks.clear()
        self._open_block_id = None
        self._successor_order.clear()
        self._successor_deadline = None
        self._strict_owner = None


__all__ = ["PresentationFrame", "ResponsePresentationWriter"]
