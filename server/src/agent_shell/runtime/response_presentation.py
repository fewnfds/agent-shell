from __future__ import annotations

from collections.abc import Mapping
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from agent_shell.response_stream_policy import ResponseStreamPolicy


@dataclass(frozen=True, slots=True)
class ResponseEvent:
    """Minimal scheduler signal projected from a runtime event.

    The scheduler only needs presentation metadata and control values.  Raw
    LangGraph protocol envelopes and the normalizer's product event object stay
    on the producer side of this boundary.
    """

    kind: Literal["content", "tool", "lifecycle", "event"]
    phase: str
    sequence: int = 0
    namespace: str = "root"
    source_type: str = ""
    workflow_node_id: str = ""
    agent_profile_id: str = ""
    subagent_profile_id: str = ""
    data: object = field(default=None, repr=False)
    stream_id: str = ""
    source_key: str = ""
    cycle_key: str = ""
    tool_kind: Literal["call", "result", "error", "progress", ""] = ""
    tool_call_id: str = ""
    terminal: bool = False


@dataclass(frozen=True, slots=True)
class ResponseModelCallBoundary:
    """Scheduler signal delimiting one model message invocation."""

    run_key: str
    source_key: str = ""
    cycle_key: str = ""
    raw_seq: int = 0
    phase: Literal["start", "end"] = "start"


def to_response_signal(event: object) -> ResponseEvent | ResponseModelCallBoundary:
    """Convert a normalizer event into the scheduler's private signal shape."""

    if isinstance(event, ResponseEvent):
        return event
    if isinstance(event, ResponseModelCallBoundary) or (
        hasattr(event, "run_key") and not hasattr(event, "event_type")
    ):
        return ResponseModelCallBoundary(
            run_key=str(getattr(event, "run_key", "")),
            source_key=str(getattr(event, "source_key", "") or ""),
            cycle_key=str(getattr(event, "cycle_key", "") or ""),
            raw_seq=int(getattr(event, "raw_seq", 0) or 0),
            phase=("end" if getattr(event, "phase", "start") == "end" else "start"),
        )

    event_type = str(getattr(event, "event_type", "") or "")
    values = getattr(event, "values", {})
    if not isinstance(values, Mapping):
        values = {}
    kind = (
        "content"
        if event_type in {"assistant_text", "reasoning"}
        else "tool"
        if event_type in {"tool_call", "tool_result", "tool_error", "tool_progress"}
        else "lifecycle"
        if event_type == "lifecycle"
        else "event"
    )
    tool_kind = (
        {
            "tool_call": "call",
            "tool_result": "result",
            "tool_error": "error",
            "tool_progress": "progress",
        }.get(event_type, "")
    )
    return ResponseEvent(
        kind=kind,
        phase=str(getattr(event, "phase", "") or ""),
        sequence=int(getattr(event, "sequence", 0) or 0),
        namespace=str(getattr(event, "namespace", "root") or "root"),
        source_type=str(getattr(event, "source_type", "") or ""),
        workflow_node_id=str(getattr(event, "workflow_node_id", "") or ""),
        agent_profile_id=str(getattr(event, "agent_profile_id", "") or ""),
        subagent_profile_id=str(getattr(event, "subagent_profile_id", "") or ""),
        data=getattr(event, "data", None),
        stream_id=str(getattr(event, "stream_id", "") or ""),
        source_key=str(getattr(event, "source_key", "") or ""),
        cycle_key=str(getattr(event, "cycle_key", "") or ""),
        tool_kind=tool_kind,
        tool_call_id=str(values.get("tool_call_id") or ""),
        terminal=(
            event_type == "lifecycle"
            and bool(getattr(event, "workflow_node_id", ""))
            and str(getattr(event, "phase", "")) in {"end", "error"}
        ),
    )


FrameKind = Literal["content"]
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
    scheduling_atom_id: str = ""
    sequence: int = 0


@dataclass(slots=True)
class _LaneMeta:
    source_type: str = ""
    workflow_node_id: str = ""


@dataclass(slots=True)
class _ContentBlock:
    block_id: str
    lane_id: str
    turn_id: str
    atom_id: str
    start_text: str = ""
    end_text: str = ""
    pending_fragments: list[str] = field(default_factory=list)
    strong_closed: bool = False
    queued: bool = False
    segment_count: int = 0


@dataclass(slots=True)
class _WorkItem:
    lane_id: str
    kind: Literal["live", "events"]
    atom_id: str = ""
    turn_id: str = ""
    block_id: str = ""
    text: str = ""


class ResponsePresentationWriter:
    """Own lane scheduling, presentation segments, and the single response writer."""

    def __init__(
        self,
        policy: ResponseStreamPolicy,
    ) -> None:
        self._policy = policy
        self._atoms: dict[str, deque[_WorkItem]] = {}
        self._ready_order: deque[str] = deque()
        self._ready_set: set[str] = set()
        self._atom_kinds: dict[str, Literal["request", "node_invocation", "event"]] = {}
        self._atom_lanes: dict[str, str] = {}
        self._terminal_atoms: set[str] = set()
        self._atom_sequence = 0
        self._lane_meta: dict[str, _LaneMeta] = {}
        self._lane_turns: dict[str, str] = {}
        self._completed_turns: dict[str, str] = {}
        self._blocks: dict[str, _ContentBlock] = {}
        self._open_block_id: str | None = None
        self._successor_order: list[str] = []
        self._owner_atom_id: str | None = None
        self._owner_deadline: float | None = None
        self._now = 0.0
        self._finishing = False
        self._frame_sequence = 0
        self._out: list[PresentationFrame] = []

    def begin(self, *, now: float = 0.0) -> None:
        if self._out:
            raise RuntimeError("presentation output was not collected")
        self._now = now

    def take_output(self) -> list[PresentationFrame]:
        output = self._out
        self._out = []
        return output

    def remember_lane(self, lane_id: str, event: ResponseEvent) -> None:
        self._lane_meta[lane_id] = _LaneMeta(
            source_type=event.source_type,
            workflow_node_id=event.workflow_node_id,
        )

    def handle_boundary(self, event: ResponseModelCallBoundary) -> None:
        lane_id = self.boundary_lane_id(event)
        if event.phase == "start":
            previous = self._lane_turns.get(lane_id) or self._completed_turns.get(
                lane_id
            )
            self._completed_turns.pop(lane_id, None)
            if previous and previous != event.run_key:
                self._mark_request_terminal(lane_id, previous)
            self._lane_turns[lane_id] = event.run_key
            return
        self._close_turn_blocks(lane_id, event.run_key)
        if self._lane_turns.get(lane_id) == event.run_key:
            self._lane_turns.pop(lane_id, None)
            self._completed_turns[lane_id] = event.run_key

    def handle_content(
        self,
        event: ResponseEvent,
        *,
        lane_id: str,
        text: str,
        segment_end_text: str,
    ) -> None:
        if self._is_media(event):
            turn_id = self.turn_id(event, lane_id)
            self.queue_text(lane_id, text, turn_id=turn_id)
            return

        block_id = self._block_id(event, lane_id)
        turn_id = self.turn_id(event, lane_id)
        atom_id = self._stable_atom_id(lane_id, turn_id)
        block = self._blocks.get(block_id)
        if block is None:
            atom_id = atom_id or self._new_event_atom(lane_id)
            block = _ContentBlock(
                block_id=block_id,
                lane_id=lane_id,
                turn_id=turn_id,
                atom_id=atom_id,
            )
            self._blocks[block_id] = block
        if text:
            self._touch_atom(block.atom_id)

        is_successor = self._is_successor(block)
        if is_successor:
            self._note_successor(block_id)

        if event.phase == "start":
            block.start_text = text
            block.end_text = segment_end_text
            if block.start_text and not is_successor:
                self._queue_live_block(block)
            return
        if event.phase == "delta":
            if text:
                if self._open_block_id == block_id:
                    self._emit(
                        "delta",
                        text,
                        block,
                        continuation=block.segment_count > 1,
                    )
                else:
                    block.pending_fragments.append(text)
                    if block_id not in self._successor_order:
                        self._queue_live_block(block)
            return
        if event.phase not in {"end", "error"}:
            return
        if event.phase == "error" and text:
            if self._open_block_id == block_id:
                self._emit(
                    "delta",
                    text,
                    block,
                    continuation=block.segment_count > 1,
                )
            else:
                block.pending_fragments.append(text)
        block.strong_closed = True
        if event.phase == "end":
            block.end_text = text or block.end_text
        if self._open_block_id == block_id:
            self._close_open("protocol_finish")
        elif (
            block.pending_fragments
            or (block.segment_count == 0 and block.end_text)
        ) and block_id not in self._successor_order:
            self._queue_live_block(block)

    def note_non_content_successor(
        self,
        *,
        lane_id: str,
        turn_id: str,
        token: str,
    ) -> None:
        if self._open_block_id is None:
            return
        current = self._blocks[self._open_block_id]
        if current.lane_id == lane_id and current.turn_id == turn_id:
            self._note_successor(token)

    def expire_owner(self, now: float) -> None:
        owner = self._owner_atom_id
        if owner is None or self._owner_deadline is None or now < self._owner_deadline:
            return
        self._owner_deadline = None
        if self._open_block_id is not None:
            block = self._blocks[self._open_block_id]
            if block.atom_id == owner:
                self._close_open("idle_timeout", refresh_owner=False)
        if self._atoms.get(owner):
            return
        self._release_owner()

    def next_deadline(self) -> float | None:
        return self._owner_deadline

    def queue_text(
        self,
        lane_id: str,
        text: str,
        *,
        turn_id: str = "",
    ) -> None:
        if not text:
            return
        atom_id = self._stable_atom_id(lane_id, turn_id)
        self._enqueue(
            _WorkItem(
                lane_id=lane_id,
                kind="events",
                atom_id=atom_id or self._new_event_atom(lane_id),
                turn_id=turn_id,
                text=text,
            )
        )

    def mark_terminal(self, lane_id: str) -> None:
        turn_id = self._lane_turns.pop(lane_id, None) or self._completed_turns.pop(
            lane_id,
            None,
        )
        if turn_id is not None:
            self._mark_request_terminal(lane_id, turn_id)
        atom_id = self._invocation_atom_id(lane_id)
        if atom_id is not None:
            self._terminal_atoms.add(atom_id)
            self._close_atom_blocks(atom_id, "node_terminal")

    def finish_content(self) -> None:
        self._owner_deadline = None
        self._finishing = True
        if self._open_block_id is not None:
            self._close_open("run_terminal", refresh_owner=False)
        for block in self._blocks.values():
            if block.strong_closed:
                continue
            block.strong_closed = True
            if block.pending_fragments or (
                block.segment_count == 0
                and (block.start_text or block.end_text)
            ):
                self._queue_live_block(block)
        self._release_owner()

    def finish_lanes(self, lane_prefix: str) -> None:
        """Close one Run's lanes without finishing the Lifecycle writer."""

        matching_atoms = {
            atom_id
            for atom_id, lane_id in self._atom_lanes.items()
            if lane_id.startswith(lane_prefix)
        }
        self._terminal_atoms.update(matching_atoms)
        if self._open_block_id is not None:
            block = self._blocks[self._open_block_id]
            if block.lane_id.startswith(lane_prefix):
                block.strong_closed = True
                self._close_open("run_terminal", refresh_owner=False)
        for block in self._blocks.values():
            if (
                not block.lane_id.startswith(lane_prefix)
                or block.strong_closed
            ):
                continue
            block.strong_closed = True
            if block.pending_fragments or (
                block.segment_count == 0
                and (block.start_text or block.end_text)
            ):
                self._queue_live_block(block)
        owner = self._owner_atom_id
        if (
            owner in matching_atoms
            and not self._atoms.get(owner)
            and self._open_block_id is None
        ):
            self._release_owner()

    def abort_lanes(self, lane_prefix: str) -> None:
        """Abort and discard one Run's unfinished lanes only."""

        matching_atoms = {
            atom_id
            for atom_id, lane_id in self._atom_lanes.items()
            if lane_id.startswith(lane_prefix)
        }
        if self._open_block_id is not None:
            block = self._blocks[self._open_block_id]
            if block.lane_id.startswith(lane_prefix):
                self._close_open(
                    "abort",
                    phase="abort",
                    refresh_owner=False,
                )
        for atom_id in matching_atoms:
            self._atoms.pop(atom_id, None)
            self._atom_kinds.pop(atom_id, None)
            self._atom_lanes.pop(atom_id, None)
            self._terminal_atoms.discard(atom_id)
            self._ready_set.discard(atom_id)
        self._ready_order = deque(
            atom_id
            for atom_id in self._ready_order
            if atom_id not in matching_atoms
        )
        matching_blocks = {
            block_id
            for block_id, block in self._blocks.items()
            if block.lane_id.startswith(lane_prefix)
        }
        for block_id in matching_blocks:
            self._blocks.pop(block_id, None)
        self._successor_order = [
            token for token in self._successor_order if token not in matching_blocks
        ]
        matching_lanes = {
            lane_id
            for lane_id in self._lane_meta
            if lane_id.startswith(lane_prefix)
        }
        for lane_id in matching_lanes:
            self._lane_meta.pop(lane_id, None)
            self._lane_turns.pop(lane_id, None)
            self._completed_turns.pop(lane_id, None)
        if self._owner_atom_id in matching_atoms:
            self._release_owner()

    def abort(self) -> None:
        if self._open_block_id is not None:
            self._close_open("abort", phase="abort")
        self._clear_pending()

    def discard(self) -> None:
        self.begin(now=self._now)
        self._clear_pending()
        self._out.clear()

    def drain(self) -> None:
        while self._open_block_id is None:
            atom_id = self._next_atom()
            if atom_id is None:
                return
            queue = self._atoms[atom_id]
            item = queue.popleft()
            if item.kind == "live":
                self._run_live(item)
            else:
                self._emit_atomic(
                    item.text,
                    item.lane_id,
                    item.turn_id,
                    atom_id=item.atom_id,
                )

            self._touch_atom(atom_id)
            if queue:
                self._ready(atom_id, front=True)
            elif (
                self._finishing
                or atom_id in self._terminal_atoms
                or self._atom_kinds.get(atom_id) == "event"
            ):
                self._release_owner()
            if self._open_block_id is not None:
                return

    def turn_id(self, event: ResponseEvent, lane_id: str) -> str:
        if event.stream_id and ":" in event.stream_id:
            return event.stream_id.rsplit(":", 1)[0]
        return self._lane_turns.get(lane_id, "")

    @staticmethod
    def event_lane_id(event: ResponseEvent) -> str:
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
    def boundary_lane_id(event: ResponseModelCallBoundary) -> str:
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
            if block.pending_fragments or (
                block.segment_count == 0
                and (block.start_text or block.end_text)
            ):
                self._queue_live_block(block)
        self._activate_successors()

    def _close_atom_blocks(self, atom_id: str, reason: str) -> None:
        if self._open_block_id is not None:
            open_block = self._blocks[self._open_block_id]
            if open_block.atom_id == atom_id:
                open_block.strong_closed = True
                self._close_open(reason, refresh_owner=False)
        for block in self._blocks.values():
            if block.atom_id != atom_id or block.strong_closed:
                continue
            block.strong_closed = True
            if block.pending_fragments or (
                block.segment_count == 0
                and (block.start_text or block.end_text)
            ):
                self._queue_live_block(block)
        self._activate_successors()

    def _queue_live_block(self, block: _ContentBlock) -> None:
        initial_boundary = block.segment_count == 0 and (
            block.start_text or (block.strong_closed and block.end_text)
        )
        if block.queued or (not block.pending_fragments and not initial_boundary):
            return
        block.queued = True
        self._enqueue(
            _WorkItem(
                lane_id=block.lane_id,
                kind="live",
                atom_id=block.atom_id,
                turn_id=block.turn_id,
                block_id=block.block_id,
            )
        )

    def _enqueue(self, item: _WorkItem) -> None:
        queue = self._atoms.setdefault(item.atom_id, deque())
        was_empty = not queue
        queue.append(item)
        self._touch_atom(item.atom_id)
        if was_empty:
            self._ready(item.atom_id)

    def _ready(self, atom_id: str, *, front: bool = False) -> None:
        if atom_id in self._ready_set:
            return
        if front:
            self._ready_order.appendleft(atom_id)
        else:
            self._ready_order.append(atom_id)
        self._ready_set.add(atom_id)

    def _next_atom(self) -> str | None:
        if self._owner_atom_id is not None:
            owner = self._owner_atom_id
            queue = self._atoms.get(owner)
            if queue:
                self._remove_ready(owner)
                return owner
            if not (
                self._finishing
                or owner in self._terminal_atoms
                or self._atom_kinds.get(owner) == "event"
            ):
                return None
            self._release_owner()
        while self._ready_order:
            atom_id = self._ready_order.popleft()
            self._ready_set.discard(atom_id)
            if not self._atoms.get(atom_id):
                continue
            self._owner_atom_id = atom_id
            self._touch_atom(atom_id)
            return atom_id
        return None

    def _remove_ready(self, atom_id: str) -> None:
        if atom_id not in self._ready_set:
            return
        self._ready_set.discard(atom_id)
        self._ready_order = deque(item for item in self._ready_order if item != atom_id)

    def _release_owner(self) -> None:
        self._owner_atom_id = None
        self._owner_deadline = None

    def _run_live(self, item: _WorkItem) -> None:
        block = self._blocks[item.block_id]
        block.queued = False
        initial_boundary = block.segment_count == 0 and (
            block.start_text or (block.strong_closed and block.end_text)
        )
        if not block.pending_fragments and not initial_boundary:
            return
        continuation = block.segment_count > 0
        block.segment_count += 1
        self._emit(
            "start",
            block.start_text,
            block,
            continuation=continuation,
        )
        fragments = tuple(block.pending_fragments)
        block.pending_fragments.clear()
        for fragment in fragments:
            self._emit(
                "delta",
                fragment,
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
        refresh_owner: bool = True,
    ) -> None:
        block_id = self._open_block_id
        if block_id is None:
            return
        block = self._blocks[block_id]
        self._emit(
            phase,
            block.end_text,
            block,
            continuation=block.segment_count > 1,
            close_reason=reason,
            refresh_owner=refresh_owner,
        )
        self._open_block_id = None
        self._activate_successors()

    def _is_successor(self, block: _ContentBlock) -> bool:
        if self._open_block_id is None or self._open_block_id == block.block_id:
            return False
        current = self._blocks[self._open_block_id]
        return current.lane_id == block.lane_id and current.turn_id == block.turn_id

    def _note_successor(self, token: str) -> None:
        if token not in self._successor_order:
            self._successor_order.append(token)

    def _activate_successors(self) -> None:
        tokens = self._successor_order
        self._successor_order = []
        for token in tokens:
            block = self._blocks.get(token)
            if block is not None:
                self._queue_live_block(block)
        owner = self._owner_atom_id
        if owner is not None and self._atoms.get(owner):
            self._remove_ready(owner)
            self._ready(owner, front=True)

    def _reservable_lane(self, lane_id: str) -> bool:
        meta = self._lane_meta.get(lane_id)
        return bool(
            meta is not None
            and meta.workflow_node_id
            and meta.source_type in {"agent", "subagent", "script"}
        )

    def _stable_atom_id(self, lane_id: str, turn_id: str) -> str | None:
        if self._policy.queue.strategy == "request":
            return self._request_atom_id(lane_id, turn_id)
        return self._invocation_atom_id(lane_id)

    def _request_atom_id(self, lane_id: str, turn_id: str) -> str | None:
        if self._policy.queue.strategy != "request" or not turn_id:
            return None
        atom_id = f"request|{lane_id}|{turn_id}"
        return self._ensure_atom(atom_id, lane_id, "request")

    def _invocation_atom_id(self, lane_id: str) -> str | None:
        if (
            self._policy.queue.strategy != "node_invocation"
            or not self._reservable_lane(lane_id)
        ):
            return None
        atom_id = f"node_invocation|{lane_id}"
        return self._ensure_atom(atom_id, lane_id, "node_invocation")

    def _new_event_atom(self, lane_id: str) -> str:
        self._atom_sequence += 1
        atom_id = f"event|{self._atom_sequence}"
        return self._ensure_atom(atom_id, lane_id, "event")

    def _ensure_atom(
        self,
        atom_id: str,
        lane_id: str,
        kind: Literal["request", "node_invocation", "event"],
    ) -> str:
        self._atom_kinds.setdefault(atom_id, kind)
        self._atom_lanes.setdefault(atom_id, lane_id)
        return atom_id

    def _mark_request_terminal(self, lane_id: str, turn_id: str) -> None:
        atom_id = self._request_atom_id(lane_id, turn_id)
        if atom_id is not None:
            self._terminal_atoms.add(atom_id)
            self._close_atom_blocks(atom_id, "request_terminal")

    def _touch_atom(self, atom_id: str) -> None:
        if atom_id != self._owner_atom_id:
            return
        self._owner_deadline = self._now + self._policy.queue.idle_timeout_seconds

    def _emit_atomic(
        self,
        text: str,
        lane_id: str,
        turn_id: str = "",
        *,
        atom_id: str,
    ) -> None:
        if not text:
            return
        self._frame_sequence += 1
        meta = self._lane_meta.get(lane_id, _LaneMeta())
        self._out.append(
            PresentationFrame(
                kind="content",
                phase="atomic",
                text=text,
                lane_id=lane_id,
                source_type=meta.source_type,
                workflow_node_id=meta.workflow_node_id,
                agent_turn_id=turn_id,
                scheduling_atom_id=atom_id,
                sequence=self._frame_sequence,
            )
        )

    def _emit(
        self,
        phase: FramePhase,
        text: str,
        block: _ContentBlock,
        *,
        continuation: bool,
        close_reason: str = "",
        refresh_owner: bool = True,
    ) -> None:
        if not text and phase not in {"start", "end", "abort"}:
            return
        self._frame_sequence += 1
        meta = self._lane_meta.get(block.lane_id, _LaneMeta())
        self._out.append(
            PresentationFrame(
                kind="content",
                phase=phase,
                text=text,
                lane_id=block.lane_id,
                source_type=meta.source_type,
                workflow_node_id=meta.workflow_node_id,
                agent_turn_id=block.turn_id,
                protocol_block_id=block.block_id,
                continuation=continuation,
                close_reason=close_reason,
                scheduling_atom_id=block.atom_id,
                sequence=self._frame_sequence,
            )
        )
        if refresh_owner and text:
            self._touch_atom(block.atom_id)

    @staticmethod
    def _block_id(event: ResponseEvent, lane_id: str) -> str:
        return f"{lane_id}|{event.stream_id or f'atomic:{event.sequence}'}"

    @staticmethod
    def _is_media(event: ResponseEvent) -> bool:
        return (
            isinstance(event.data, dict)
            and event.data.get("type") in {"image", "audio", "video", "file"}
        )

    def _clear_pending(self) -> None:
        self._atoms.clear()
        self._ready_order.clear()
        self._ready_set.clear()
        self._atom_kinds.clear()
        self._atom_lanes.clear()
        self._terminal_atoms.clear()
        self._lane_turns.clear()
        self._completed_turns.clear()
        self._blocks.clear()
        self._open_block_id = None
        self._successor_order.clear()
        self._owner_atom_id = None
        self._owner_deadline = None


__all__ = [
    "PresentationFrame",
    "ResponseEvent",
    "ResponseModelCallBoundary",
    "ResponsePresentationWriter",
    "to_response_signal",
]
