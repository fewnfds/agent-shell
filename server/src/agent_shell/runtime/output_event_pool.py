from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from agent_shell.runtime.output_projection import OutputProjector, WorkflowOutputProjector
from agent_shell.runtime.output_stream import OutputEvent

TOOL_OUTCOME_TYPES = {"tool_result", "tool_error"}


@dataclass(slots=True)
class _PendingEvent:
    event: OutputEvent
    source_key: str
    cycle_key: str
    ready: bool = False
    boundary_closed: bool = False


@dataclass(slots=True)
class _SourceState:
    source_key: str
    pending: _PendingEvent


class OutputEventRectifier:
    """Buffer model blocks and serialize complete semantic output events."""

    def __init__(
        self,
        projector: OutputProjector | WorkflowOutputProjector,
    ) -> None:
        self._projector = projector
        self._queue: deque[_PendingEvent] = deque()
        self._sources: dict[tuple[str, str], _SourceState] = {}

    def feed(self, event: OutputEvent) -> list[str]:
        if event.stream_id:
            self._feed_source_event(event)
        else:
            self._feed_atomic_event(event)
        return self._drain()

    @staticmethod
    def event_source_key(event: OutputEvent) -> str:
        explicit = str(getattr(event, "source_key", "") or "").strip()
        if explicit:
            return explicit
        identity = (
            event.workflow_node_id,
            event.source_type,
            event.agent_profile_id,
            event.subagent_profile_id,
        )
        stable = "|".join(str(item or "") for item in identity)
        runtime = event.namespace.strip()
        if runtime and runtime != "root":
            return f"{stable}|{runtime}"
        return stable or f"{event.agent_name}|{event.node}"

    @staticmethod
    def event_cycle_key(event: OutputEvent) -> str:
        explicit = str(getattr(event, "cycle_key", "") or "").strip()
        if explicit:
            return explicit
        return event.namespace.strip() or "root"

    def flush_source(self, source_key: str) -> list[str]:
        return self._flush_scope(source_key=source_key)

    def flush_cycle(self, source_key: str, cycle_key: str) -> list[str]:
        return self._flush_scope(source_key=source_key, cycle_key=cycle_key)

    def flush(self) -> list[str]:
        for item in self._queue:
            item.boundary_closed = True
        parts = self._drain()
        self.discard()
        return parts

    def _flush_scope(
        self, *, source_key: str, cycle_key: str | None = None
    ) -> list[str]:
        retained: deque[_PendingEvent] = deque()
        for item in self._queue:
            if self._matches_scope(
                item, source_key=source_key, cycle_key=cycle_key
            ):
                item.boundary_closed = True
                if item.ready:
                    retained.append(item)
            else:
                retained.append(item)
        self._queue = retained
        for state_key, source in tuple(self._sources.items()):
            pending = source.pending
            if source.source_key == source_key and (
                cycle_key is None or pending.cycle_key == cycle_key
            ):
                self._sources.pop(state_key, None)
        return self._drain()

    @staticmethod
    def _matches_scope(
        item: _PendingEvent,
        *,
        source_key: str,
        cycle_key: str | None,
    ) -> bool:
        return item.source_key == source_key and (
            cycle_key is None or item.cycle_key == cycle_key
        )

    def abort(self) -> list[str]:
        self.discard()
        return []

    def discard(self) -> None:
        self._queue.clear()
        self._sources.clear()

    def _feed_source_event(self, event: OutputEvent) -> None:
        source_key = self.event_source_key(event)
        source_state_key = (source_key, event.stream_id)
        source = self._sources.get(source_state_key)
        if event.phase == "start":
            if not self._projector.enabled(event) or source is not None:
                return
            pending = _PendingEvent(
                event=event,
                source_key=source_key,
                cycle_key=self.event_cycle_key(event),
            )
            self._sources[source_state_key] = _SourceState(
                source_key=source_key,
                pending=pending,
            )
            self._queue.append(pending)
            return
        if source is None:
            if event.phase == "end":
                self._feed_atomic_event(event)
            return
        if event.phase == "end":
            source.pending.event = event
            source.pending.ready = True

    def _feed_atomic_event(self, event: OutputEvent) -> None:
        if not self._projector.enabled(event):
            return
        self._queue.append(
            _PendingEvent(
                event=event,
                source_key=self.event_source_key(event),
                cycle_key=self.event_cycle_key(event),
                ready=True,
            )
        )

    def _drain(self) -> list[str]:
        parts: list[str] = []
        while self._queue:
            item = self._next_ready_item()
            if item is None:
                break
            self._queue.remove(item)
            parts.extend(self._render_atomic_with_pair(item))
        return parts

    def _next_ready_item(self) -> _PendingEvent | None:
        """Keep tool calls local until their outcome or an invocation boundary."""

        unmatched_tool_call_seen = False
        for candidate in self._queue:
            if not candidate.ready:
                continue
            event_type = candidate.event.event_type
            if event_type == "tool_call":
                call_id = candidate.event.values.get("tool_call_id", "")
                if not call_id or candidate.boundary_closed:
                    return candidate
                if self._find_tool_partner(candidate) is None:
                    unmatched_tool_call_seen = True
                    continue
                if not unmatched_tool_call_seen:
                    return candidate
                continue
            if event_type in TOOL_OUTCOME_TYPES:
                if self._find_tool_partner(candidate) is None:
                    return candidate
                continue
            return candidate
        return None

    def _render_atomic_with_pair(self, item: _PendingEvent) -> list[str]:
        partner = self._take_tool_partner(item)
        ordered = [item]
        if partner is not None:
            ordered = (
                [partner, item]
                if item.event.event_type in TOOL_OUTCOME_TYPES
                else [item, partner]
            )
        return [
            rendered
            for candidate in ordered
            if (rendered := self._projector.render(candidate.event))
        ]

    def _take_tool_partner(self, item: _PendingEvent) -> _PendingEvent | None:
        partner = self._find_tool_partner(item)
        if partner is not None:
            self._queue.remove(partner)
        return partner

    def _find_tool_partner(self, item: _PendingEvent) -> _PendingEvent | None:
        event_type = item.event.event_type
        if event_type != "tool_call" and event_type not in TOOL_OUTCOME_TYPES:
            return None
        call_id = item.event.values.get("tool_call_id", "")
        if not call_id:
            return None
        for candidate in self._queue:
            candidate_type = candidate.event.event_type
            complementary = (
                event_type == "tool_call" and candidate_type in TOOL_OUTCOME_TYPES
            ) or (
                event_type in TOOL_OUTCOME_TYPES and candidate_type == "tool_call"
            )
            if (
                candidate.ready
                and complementary
                and candidate.source_key == item.source_key
                and candidate.cycle_key == item.cycle_key
                and candidate.event.values.get("tool_call_id", "") == call_id
            ):
                return candidate
        return None


__all__ = ["OutputEventRectifier"]
