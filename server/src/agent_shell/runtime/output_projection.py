from __future__ import annotations

from collections.abc import Mapping

from agent_shell.event_output_packages import EventOutputCallable
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.output_stream import OutputEvent


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

__all__ = ["EventOutputError", "OutputProjector", "WorkflowOutputProjector"]
