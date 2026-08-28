from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from agent_shell.event_output_packages import EventOutputCallable
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.output_stream import ModelCallBoundary, OutputEvent


class EventOutputError(AgentRuntimeError):
    """Safe wrapper for user-authored public output failures."""

    def __init__(self) -> None:
        super().__init__(
            "event_output.execution_failed",
            "The event output extension failed.",
            status_code=502,
        )


class OutputProjector:
    """Render stable Agent events through one configuration-owned package."""

    def __init__(self, output: EventOutputCallable | None) -> None:
        self._output = output

    def enabled(self, event: OutputEvent) -> bool:
        return self._output is not None

    def render(self, event: OutputEvent) -> str:
        if self._output is None:
            return ""
        try:
            value = self._output(event.output_dict())
            if not isinstance(value, str):
                raise TypeError("output(event) must return a string")
            return value
        except Exception as exc:
            raise EventOutputError() from exc


class WorkflowOutputProjector:
    """Route Agent node policies and Workflow-owned non-Agent event scripts."""

    def __init__(
        self,
        outputs_by_node: Mapping[str, EventOutputCallable],
        *,
        workflow_output: EventOutputCallable | None = None,
    ) -> None:
        self._projectors = {
            node_id: OutputProjector(output)
            for node_id, output in outputs_by_node.items()
        }
        self._workflow_projector = OutputProjector(workflow_output)

    def _for(self, event: OutputEvent) -> OutputProjector | None:
        if event.source_type in {"agent", "subagent"}:
            if not event.workflow_node_id:
                return None
            return self._projectors.get(event.workflow_node_id)
        return self._workflow_projector

    def enabled(self, event: OutputEvent) -> bool:
        projector = self._for(event)
        return projector.enabled(event) if projector is not None else False

    def render(self, event: OutputEvent) -> str:
        projector = self._for(event)
        return projector.render(event) if projector is not None else ""


@dataclass(frozen=True, slots=True)
class ProjectedOutputEvent:
    event: OutputEvent | ModelCallBoundary
    text: str = ""
    segment_end_text: str = ""


@dataclass(slots=True)
class _ContentProjectionState:
    event: OutputEvent
    end_text: str
    has_delta: bool = False


class EventOutputProjectionStream:
    """Apply the selected Event Output before text reaches response scheduling."""

    def __init__(self, projector: OutputProjector | WorkflowOutputProjector) -> None:
        self._projector = projector
        self._content: dict[str, _ContentProjectionState] = {}
        self._closed_content: set[str] = set()

    def project(
        self,
        item: OutputEvent | ModelCallBoundary,
    ) -> tuple[ProjectedOutputEvent, ...]:
        if isinstance(item, ModelCallBoundary):
            projected: list[ProjectedOutputEvent] = []
            if item.phase == "end":
                projected.extend(self._close_turn(item.run_key))
            projected.append(ProjectedOutputEvent(item))
            return tuple(projected)
        if item.event_type not in {"assistant_text", "reasoning"} or self._is_media(item):
            return (ProjectedOutputEvent(item, self._projector.render(item)),)

        key = self._content_key(item)
        if item.phase == "start":
            self._closed_content.discard(key)
            start_text = self._projector.render(item)
            end = replace(item, phase="end", message="")
            end_text = self._projector.render(end)
            self._content[key] = _ContentProjectionState(item, end_text=end_text)
            return (
                ProjectedOutputEvent(
                    item,
                    start_text,
                    segment_end_text=end_text,
                ),
            )
        if item.phase == "delta":
            state = self._content.get(key)
            if state is None:
                self._closed_content.discard(key)
                end = replace(item, phase="end", message="")
                state = _ContentProjectionState(
                    item,
                    end_text=self._projector.render(end),
                )
                self._content[key] = state
            state.event = item
            state.has_delta = True
            return (ProjectedOutputEvent(item, self._projector.render(item)),)
        if item.phase not in {"end", "error"}:
            return (ProjectedOutputEvent(item, self._projector.render(item)),)

        state = self._content.pop(key, None)
        if state is None and item.phase == "end" and key in self._closed_content:
            return ()
        self._closed_content.add(key)
        if item.phase == "error":
            return (ProjectedOutputEvent(item, self._projector.render(item)),)
        projected = []
        if state is None:
            start = replace(item, phase="start", message="")
            start_text = self._projector.render(start)
            delta = replace(item, phase="delta") if item.message else None
            delta_text = self._projector.render(delta) if delta is not None else ""
            end = replace(item, message="")
            end_text = self._projector.render(end)
            projected.append(ProjectedOutputEvent(
                start,
                start_text,
                segment_end_text=end_text,
            ))
            if delta is not None:
                projected.append(ProjectedOutputEvent(delta, delta_text))
        else:
            end = replace(item, message="")
            end_text = state.end_text
        if state is not None and not state.has_delta and item.message:
            delta = replace(item, phase="delta")
            projected.append(ProjectedOutputEvent(delta, self._projector.render(delta)))
        projected.append(ProjectedOutputEvent(end, end_text))
        return tuple(projected)

    def finish(self) -> tuple[ProjectedOutputEvent, ...]:
        projected: list[ProjectedOutputEvent] = []
        for key in tuple(self._content):
            state = self._content.pop(key)
            self._closed_content.add(key)
            end = replace(state.event, phase="end", message="")
            projected.append(ProjectedOutputEvent(end, state.end_text))
        return tuple(projected)

    def discard(self) -> None:
        self._content.clear()
        self._closed_content.clear()

    def _close_turn(self, run_key: str) -> list[ProjectedOutputEvent]:
        projected: list[ProjectedOutputEvent] = []
        for key, state in tuple(self._content.items()):
            if self._turn_id(state.event) != run_key:
                continue
            self._content.pop(key, None)
            self._closed_content.add(key)
            end = replace(state.event, phase="end", message="")
            projected.append(ProjectedOutputEvent(end, state.end_text))
        return projected

    @staticmethod
    def _content_key(event: OutputEvent) -> str:
        identity = event.stream_id or f"event:{event.sequence}"
        return f"{event.source_key}|{event.cycle_key}|{identity}"

    @staticmethod
    def _turn_id(event: OutputEvent) -> str:
        return event.stream_id.rsplit(":", 1)[0] if ":" in event.stream_id else ""

    @staticmethod
    def _is_media(event: OutputEvent) -> bool:
        return (
            isinstance(event.data, dict)
            and event.data.get("type") in {"image", "audio", "video", "file"}
        )


__all__ = [
    "EventOutputError",
    "EventOutputProjectionStream",
    "OutputProjector",
    "ProjectedOutputEvent",
    "WorkflowOutputProjector",
]
