from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TypedDict

from agent_shell.event_output_packages import (
    EventOutputCallable,
    EventOutputOrigin,
    EventRunOutputCallable,
)
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.output_stream import ModelCallBoundary, OutputEvent


class EventOutputOriginDict(TypedDict):
    lifecycle_id: str
    workflow_run_id: str
    parent_workflow_run_id: str
    workflow_id: str
    workflow_role: str
    background_task_id: str
    run_depth: int
    workflow_node_id: str
    node_invocation_id: str
    agent_profile_id: str
    subagent_profile_id: str


def _origin_values(
    context: WorkflowRuntimeContext | None,
    *,
    workflow_node_id: str = "",
    node_invocation_id: str = "",
    agent_profile_id: str = "",
    subagent_profile_id: str = "",
) -> EventOutputOriginDict:
    workflow = context.workflow if context is not None else {}
    return {
        "lifecycle_id": context.lifecycle_id if context is not None else "",
        "workflow_run_id": context.run_id if context is not None else "",
        "parent_workflow_run_id": context.parent_run_id if context is not None else "",
        "workflow_id": str(workflow.get("id", "")),
        "workflow_role": str(workflow.get("workflow_role", "")),
        "background_task_id": context.background_task_id if context is not None else "",
        "run_depth": context.run_depth if context is not None else 0,
        "workflow_node_id": workflow_node_id or (context.workflow_node_id if context is not None else ""),
        "node_invocation_id": node_invocation_id or (context.invocation_id if context is not None else ""),
        "agent_profile_id": agent_profile_id or (context.agent_id if context is not None else ""),
        "subagent_profile_id": subagent_profile_id,
    }


def _namespace_parts(event: object) -> tuple[str, ...]:
    if not isinstance(event, Mapping):
        return ()
    params = event.get("params")
    namespace = params.get("namespace") if isinstance(params, Mapping) else None
    data = params.get("data") if isinstance(params, Mapping) else None
    if (namespace is None or namespace == []) and isinstance(data, Mapping):
        namespace = data.get("namespace")
    if not isinstance(namespace, (list, tuple)):
        return ()
    return tuple(str(part) for part in namespace if str(part))


def _message_metadata(event: object) -> Mapping[str, object]:
    if not isinstance(event, Mapping):
        return {}
    params = event.get("params")
    data = params.get("data") if isinstance(params, Mapping) else None
    if not isinstance(data, (list, tuple)) or len(data) != 2:
        return {}
    return data[1] if isinstance(data[1], Mapping) else {}


class EventOutputOriginResolver:
    """Resolve Shell identity once for a raw v3 ProtocolEvent."""

    def __init__(
        self,
        context: WorkflowRuntimeContext | None,
        *,
        workflow_sources: Mapping[str, object] | None = None,
        main_agent_names: Sequence[str] = (),
        workflow_subagent_profile_ids: Mapping[str, Mapping[str, str]] | None = None,
        subagent_profile_ids: Mapping[str, str] | None = None,
    ) -> None:
        self._context = context
        self._sources = dict(workflow_sources or {})
        self._main_agent_names = frozenset(str(name) for name in main_agent_names)
        self._workflow_subagent_profile_ids = {
            str(node): {str(name): str(profile) for name, profile in profiles.items()}
            for node, profiles in (workflow_subagent_profile_ids or {}).items()
        }
        self._subagent_profile_ids = {
            str(name): str(profile) for name, profile in (subagent_profile_ids or {}).items()
        }

    def resolve(
        self,
        event: Mapping[str, object],
        normalized: Sequence[OutputEvent | ModelCallBoundary] = (),
    ) -> EventOutputOriginDict:
        workflow_node_id = ""
        node_invocation_id = ""
        agent_profile_id = ""
        subagent_profile_id = ""
        normalized_event = next(
            (item for item in normalized if isinstance(item, OutputEvent)), None
        )
        if normalized_event is not None:
            workflow_node_id = normalized_event.workflow_node_id
            agent_profile_id = normalized_event.agent_profile_id
            subagent_profile_id = normalized_event.subagent_profile_id

        parts = _namespace_parts(event)
        if not workflow_node_id:
            for segment in reversed(parts):
                name, separator, invocation = segment.partition(":")
                if name in self._sources:
                    workflow_node_id = name
                    node_invocation_id = invocation if separator else ""
                    source = self._sources[name]
                    agent_profile_id = str(getattr(source, "agent_profile_id", "") or "")
                    break
        if workflow_node_id and not node_invocation_id:
            for segment in reversed(parts):
                name, separator, invocation = segment.partition(":")
                if name == workflow_node_id and separator:
                    node_invocation_id = invocation
                    break

        metadata = _message_metadata(event)
        agent_name = str(metadata.get("lc_agent_name") or "")
        if not agent_name:
            params = event.get("params")
            data = params.get("data") if isinstance(params, Mapping) else None
            if isinstance(data, Mapping):
                agent_name = str(data.get("graph_name") or "")
        profiles = self._workflow_subagent_profile_ids.get(
            workflow_node_id, self._subagent_profile_ids
        )
        if agent_name and agent_name not in self._main_agent_names:
            subagent_profile_id = subagent_profile_id or profiles.get(agent_name, "")

        return _origin_values(
            self._context,
            workflow_node_id=workflow_node_id,
            node_invocation_id=node_invocation_id,
            agent_profile_id=agent_profile_id,
            subagent_profile_id=subagent_profile_id,
        )


class EventOutputError(AgentRuntimeError):
    """Safe wrapper for user-authored public output failures."""

    def __init__(self) -> None:
        super().__init__(
            "event_output.execution_failed",
            "The event output extension failed.",
            status_code=502,
        )


class OutputProjector:
    """Invoke a package with the raw protocol event and explicit Shell origin."""

    def __init__(
        self,
        output: EventOutputCallable | None,
        *,
        run_output: EventRunOutputCallable | None = None,
    ) -> None:
        self._output = output
        self._run_output = run_output

    def enabled(self, _event: object = None) -> bool:
        return self._output is not None

    def render(self, event: Mapping[str, object], origin: EventOutputOrigin) -> str:
        if self._output is None:
            return ""
        try:
            value = self._output(event, origin)
            if not isinstance(value, str):
                raise TypeError("output(event, origin) must return a string")
            return value
        except Exception as exc:
            raise EventOutputError() from exc

    def render_run(
        self,
        event: Mapping[str, object],
        origin: EventOutputOrigin,
    ) -> str:
        if self._run_output is None:
            return ""
        try:
            value = self._run_output(event, origin)
            if not isinstance(value, str):
                raise TypeError("run_output(event, origin) must return a string")
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
        run_outputs_by_node: Mapping[str, EventRunOutputCallable | None] | None = None,
        workflow_run_output: EventRunOutputCallable | None = None,
    ) -> None:
        self._projectors = {
            node_id: OutputProjector(output)
            for node_id, output in outputs_by_node.items()
        }
        self._workflow_projector = OutputProjector(workflow_output)
        self._run_projectors = {
            node_id: OutputProjector(None, run_output=output)
            if output is not None
            else None
            for node_id, output in (run_outputs_by_node or {}).items()
        }
        self._workflow_run_projector = (
            OutputProjector(None, run_output=workflow_run_output)
            if workflow_run_output is not None
            else None
        )

    def _for(self, origin: EventOutputOrigin) -> OutputProjector | None:
        if origin.get("agent_profile_id") or origin.get("subagent_profile_id"):
            workflow_node_id = str(origin.get("workflow_node_id") or "")
            if not workflow_node_id:
                return None
            return self._projectors.get(workflow_node_id)
        return self._workflow_projector

    def _run_for(self, origin: EventOutputOrigin) -> OutputProjector | None:
        if origin.get("agent_profile_id") or origin.get("subagent_profile_id"):
            return self._run_projectors.get(str(origin.get("workflow_node_id") or ""))
        return self._workflow_run_projector

    def enabled(self, origin: EventOutputOrigin) -> bool:
        projector = self._for(origin)
        return projector.enabled() if projector is not None else False

    def render(self, event: Mapping[str, object], origin: EventOutputOrigin) -> str:
        projector = self._for(origin)
        return projector.render(event, origin) if projector is not None else ""

    def render_run(
        self,
        event: Mapping[str, object],
        origin: EventOutputOrigin,
    ) -> str:
        projector = self._run_for(origin)
        return projector.render_run(event, origin) if projector is not None else ""


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
    """Expand already-projected text across content block boundaries."""

    def __init__(self) -> None:
        self._content: dict[str, _ContentProjectionState] = {}
        self._closed_content: set[str] = set()

    def project(
        self,
        item: OutputEvent | ModelCallBoundary,
        *,
        text: str = "",
        segment_end_text: str = "",
    ) -> tuple[ProjectedOutputEvent, ...]:
        if isinstance(item, ModelCallBoundary):
            projected: list[ProjectedOutputEvent] = []
            if item.phase == "end":
                projected.extend(self._close_turn(item.run_key))
            projected.append(ProjectedOutputEvent(item))
            return tuple(projected)
        if item.event_type not in {"assistant_text", "reasoning"} or self._is_media(item):
            return (ProjectedOutputEvent(item, text),)

        key = self._content_key(item)
        if item.phase == "start":
            self._closed_content.discard(key)
            self._content[key] = _ContentProjectionState(
                item, end_text=segment_end_text
            )
            return (
                ProjectedOutputEvent(
                    item,
                    text,
                    segment_end_text=segment_end_text,
                ),
            )
        if item.phase == "delta":
            state = self._content.get(key)
            if state is None:
                self._closed_content.discard(key)
                state = _ContentProjectionState(
                    item,
                    end_text=segment_end_text,
                )
                self._content[key] = state
            state.event = item
            state.has_delta = True
            return (ProjectedOutputEvent(item, text),)
        if item.phase not in {"end", "error"}:
            return (ProjectedOutputEvent(item, text),)

        state = self._content.pop(key, None)
        if state is None and item.phase == "end" and key in self._closed_content:
            return ()
        self._closed_content.add(key)
        if item.phase == "error":
            return (ProjectedOutputEvent(item, text),)
        projected = []
        if state is None:
            start = replace(item, phase="start", message="")
            delta = replace(item, phase="delta") if item.message else None
            delta_text = text if delta is not None else ""
            end = replace(item, message="")
            end_text = segment_end_text
            projected.append(ProjectedOutputEvent(
                start,
                "",
                segment_end_text=end_text,
            ))
            if delta is not None:
                projected.append(ProjectedOutputEvent(delta, delta_text))
        else:
            end = replace(item, message="")
            # A raw content-block-finish is the only event available for a
            # non-streaming whole message and may also carry the closing
            # decoration for a streamed block.  When real deltas already
            # arrived, treat its projection as the segment end; otherwise the
            # branch below emits it as the whole-message delta.
            end_text = state.end_text
            if state.has_delta and not end_text:
                end_text = text
        if state is not None and not state.has_delta and item.message:
            delta = replace(item, phase="delta")
            projected.append(ProjectedOutputEvent(delta, text))
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
    "EventOutputOriginDict",
    "EventOutputOriginResolver",
    "EventOutputError",
    "EventOutputProjectionStream",
    "OutputProjector",
    "ProjectedOutputEvent",
    "WorkflowOutputProjector",
]
