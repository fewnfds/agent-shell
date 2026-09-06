from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field

from agent_shell.response_stream_policy import ResponseStreamPolicy
from agent_shell.runtime.response_presentation import PresentationFrame


RunKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class ResponseFrameInput:
    lifecycle_id: str
    thread_id: str
    run_id: str
    frame: PresentationFrame


@dataclass(slots=True)
class _ProtocolBlock:
    start_text: str
    segment_end_text: str
    segment_count: int = 0


@dataclass(slots=True)
class _RunOutput:
    pending: deque[PresentationFrame] = field(default_factory=deque)
    blocks: dict[str, _ProtocolBlock] = field(default_factory=dict)
    open_block_id: str | None = None
    terminal: bool = False
    aborted: bool = False
    parked: bool = False


class LifecycleResponseScheduler:
    """Serialize already-projected frames one registered Graph Run at a time."""

    def __init__(self, policy: ResponseStreamPolicy, *, lifecycle_id: str) -> None:
        self.policy = policy.model_copy(deep=True)
        self.lifecycle_id = lifecycle_id
        self._runs: dict[RunKey, _RunOutput] = {}
        self._ready: deque[RunKey] = deque()
        self._ready_set: set[RunKey] = set()
        self._owner: RunKey | None = None
        self._owner_deadline: float | None = None
        self._pending_frames: deque[PresentationFrame] = deque()
        self._published_frames: deque[PresentationFrame] = deque()
        self._wakeup = asyncio.Event()
        self._last_batch_at: float | None = None
        self._frame_sequence = 0
        self._finished = False

    def register_run(self, thread_id: str, run_id: str, *, now: float) -> None:
        key = (thread_id, run_id)
        if self._finished:
            raise RuntimeError("lifecycle response scheduler is already finished")
        if key in self._runs:
            return
        self._runs[key] = _RunOutput()
        self._enqueue_ready(key)
        self._assign_owner(now)
        self._wakeup.set()

    def accepting(self, thread_id: str, run_id: str) -> bool:
        state = self._runs.get((thread_id, run_id))
        return not self._finished and state is not None and not state.terminal

    def publish(self, item: ResponseFrameInput, *, now: float) -> None:
        if self._finished:
            return
        self._validate_input(item)
        key = (item.thread_id, item.run_id)
        state = self._runs[key]
        state.pending.append(item.frame)
        if state.parked:
            state.parked = False
            self._enqueue_ready(key)
        if self._owner is None:
            self._assign_owner(now)
        if self._owner == key:
            self._drain_owner(now)
        self._expire_owner(now)
        self._assign_owner(now)
        self._published_frames.extend(self._take_due_batch(now))
        self._wakeup.set()

    def finish_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        now: float,
        aborted: bool = False,
    ) -> None:
        key = (thread_id, run_id)
        state = self._runs.get(key)
        if state is None or state.terminal:
            return
        was_owner = self._owner == key
        state.terminal = True
        state.aborted = aborted
        state.parked = False
        if self._owner == key:
            self._drain_owner(now)
            self._finish_owner(now)
        elif state.pending:
            self._enqueue_ready(key)
        else:
            self._remove_ready(key)
            state.blocks.clear()
        if was_owner:
            self._published_frames.extend(self._take_due_batch(now, force=True))
        self._assign_owner(now)
        self._published_frames.extend(self._take_due_batch(now))
        self._wakeup.set()

    def advance_published(self, *, now: float) -> None:
        if self._finished:
            return
        self._expire_owner(now)
        self._assign_owner(now)
        self._published_frames.extend(self._take_due_batch(now))

    def take_published(self) -> list[PresentationFrame]:
        output = list(self._published_frames)
        self._published_frames.clear()
        return output

    def clear_wakeup(self) -> None:
        self._wakeup.clear()

    async def wait_for_wakeup(self) -> None:
        await self._wakeup.wait()

    def next_deadline(self) -> float | None:
        deadlines = [
            deadline
            for deadline in (self._owner_deadline, self._batch_deadline())
            if deadline is not None
        ]
        return min(deadlines) if deadlines else None

    @property
    def all_runs_terminal(self) -> bool:
        return bool(self._runs) and all(state.terminal for state in self._runs.values())

    @property
    def response_complete(self) -> bool:
        return bool(
            self.all_runs_terminal
            and self._owner is None
            and not self._ready
            and not any(state.pending for state in self._runs.values())
            and not self._pending_frames
            and not self._published_frames
        )

    @property
    def has_pending_output(self) -> bool:
        return bool(
            self._published_frames
            or self._pending_frames
            or any(state.pending for state in self._runs.values())
        )

    def finish(self, *, now: float) -> list[PresentationFrame]:
        """Seal a fully terminal Lifecycle after its consumer has drained it."""

        if not self.all_runs_terminal:
            raise RuntimeError("cannot finish a Lifecycle with active Runs")
        self._expire_owner(now)
        self._assign_owner(now)
        output = [*self.take_published(), *self._take_due_batch(now, force=True)]
        if self._owner is not None or self._ready or any(
            state.pending for state in self._runs.values()
        ):
            raise RuntimeError("cannot finish a Lifecycle with pending Run frames")
        self._finished = True
        self._wakeup.set()
        return output

    def discard(self) -> None:
        self._runs.clear()
        self._ready.clear()
        self._ready_set.clear()
        self._owner = None
        self._owner_deadline = None
        self._pending_frames.clear()
        self._published_frames.clear()
        self._last_batch_at = None
        self._finished = True
        self._wakeup.set()

    def _validate_input(self, item: ResponseFrameInput) -> None:
        if item.lifecycle_id != self.lifecycle_id or not self.accepting(
            item.thread_id, item.run_id
        ):
            raise ValueError("ResponseFrameInput does not belong to this lifecycle scheduler")

    def _assign_owner(self, now: float) -> None:
        while self._owner is None and self._ready:
            key = self._ready.popleft()
            self._ready_set.discard(key)
            state = self._runs[key]
            if state.terminal and not state.pending:
                state.blocks.clear()
                continue
            self._owner = key
            self._owner_deadline = now + self.policy.idle_timeout_seconds
            self._drain_owner(now)
            if state.terminal:
                self._finish_owner(now)

    def _drain_owner(self, now: float) -> None:
        key = self._owner
        if key is None:
            return
        state = self._runs[key]
        while state.pending:
            frame = state.pending.popleft()
            before = len(self._pending_frames)
            self._present(state, frame)
            if any(item.text for item in tuple(self._pending_frames)[before:]):
                self._owner_deadline = now + self.policy.idle_timeout_seconds

    def _present(self, state: _RunOutput, frame: PresentationFrame) -> None:
        if frame.phase == "atomic":
            self._close_public_segment(state, "atomic_boundary")
            if frame.text:
                self._emit("atomic", frame.text)
            return

        block_id = frame.block_id
        if not block_id:
            if frame.text:
                self._emit("atomic", frame.text)
            return

        if frame.phase == "start":
            self._close_public_segment(state, "protocol_successor")
            block = _ProtocolBlock(frame.text, frame.segment_end_text)
            state.blocks[block_id] = block
            self._open_segment(state, block_id, block)
            return

        block = state.blocks.get(block_id)
        if block is None:
            if frame.text:
                self._emit("atomic", frame.text)
            return

        if frame.phase == "delta":
            if state.open_block_id != block_id:
                self._close_public_segment(state, "protocol_resume")
                self._open_segment(state, block_id, block)
            if frame.text:
                self._emit(
                    "delta",
                    frame.text,
                    block_id=block_id,
                    continuation=block.segment_count > 1,
                )
            return

        if frame.phase in {"finish", "abort"}:
            if state.open_block_id != block_id and frame.text:
                self._close_public_segment(state, "protocol_resume")
                self._open_segment(state, block_id, block)
            if state.open_block_id == block_id:
                self._emit(
                    frame.phase,
                    frame.text or block.segment_end_text,
                    block_id=block_id,
                    continuation=block.segment_count > 1,
                    close_reason="protocol_finish" if frame.phase == "finish" else "abort",
                )
                state.open_block_id = None
            state.blocks.pop(block_id, None)

    def _open_segment(
        self,
        state: _RunOutput,
        block_id: str,
        block: _ProtocolBlock,
    ) -> None:
        continuation = block.segment_count > 0
        block.segment_count += 1
        self._emit(
            "start",
            block.start_text,
            block_id=block_id,
            segment_end_text=block.segment_end_text,
            continuation=continuation,
        )
        state.open_block_id = block_id

    def _close_public_segment(self, state: _RunOutput, reason: str) -> None:
        block_id = state.open_block_id
        if block_id is None:
            return
        block = state.blocks.get(block_id)
        if block is not None:
            self._emit(
                "finish",
                block.segment_end_text,
                block_id=block_id,
                continuation=block.segment_count > 1,
                close_reason=reason,
            )
        state.open_block_id = None

    def _expire_owner(self, now: float) -> None:
        if (
            self._owner is None
            or self._owner_deadline is None
            or now < self._owner_deadline
        ):
            return
        key = self._owner
        state = self._runs[key]
        self._close_public_segment(state, "idle_timeout")
        state.parked = not state.terminal
        self._release_owner()

    def _finish_owner(self, now: float) -> None:
        key = self._owner
        if key is None:
            return
        state = self._runs[key]
        self._close_public_segment(
            state,
            "run_abort" if state.aborted else "run_terminal",
        )
        state.blocks.clear()
        self._release_owner()

    def _release_owner(self) -> None:
        self._owner = None
        self._owner_deadline = None

    def _enqueue_ready(self, key: RunKey) -> None:
        if key == self._owner or key in self._ready_set:
            return
        self._ready.append(key)
        self._ready_set.add(key)

    def _remove_ready(self, key: RunKey) -> None:
        if key not in self._ready_set:
            return
        self._ready_set.discard(key)
        self._ready = deque(item for item in self._ready if item != key)

    def _emit(
        self,
        phase: str,
        text: str,
        *,
        block_id: str = "",
        segment_end_text: str = "",
        continuation: bool = False,
        close_reason: str = "",
    ) -> None:
        self._frame_sequence += 1
        self._pending_frames.append(
            PresentationFrame(
                phase=phase,  # type: ignore[arg-type]
                text=text,
                block_id=block_id,
                segment_end_text=segment_end_text,
                continuation=continuation,
                close_reason=close_reason,
                sequence=self._frame_sequence,
            )
        )

    def _take_due_batch(
        self,
        now: float,
        *,
        force: bool = False,
    ) -> list[PresentationFrame]:
        if not self._pending_frames:
            return []
        deadline = self._batch_deadline()
        if not force and deadline is not None and now < deadline:
            return []

        maximum_bytes = self.policy.max_batch_kb * 1024
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
        return self._last_batch_at + self.policy.send_interval_seconds


__all__ = [
    "LifecycleResponseScheduler",
    "PresentationFrame",
    "ResponseFrameInput",
]
