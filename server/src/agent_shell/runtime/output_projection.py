from __future__ import annotations

from collections.abc import Mapping

from agent_shell.event_output_packages import (
    EventOutputCallable,
    EventOutputOrigin,
    EventRunOutputCallable,
)
from agent_shell.runtime.errors import AgentRuntimeError


class EventOutputError(AgentRuntimeError):
    """Safe wrapper for user-authored public output failures."""

    def __init__(self) -> None:
        super().__init__(
            "event_output.execution_failed",
            "The event output extension failed.",
            status_code=502,
        )


class OutputProjector:
    """Invoke one package with a raw protocol event and explicit Shell origin."""

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
    """Select the configured Agent or Workflow package from Shell origin."""

    def __init__(
        self,
        outputs_by_node: Mapping[str, EventOutputCallable],
        *,
        workflow_output: EventOutputCallable | None = None,
        workflow_run_output: EventRunOutputCallable | None = None,
    ) -> None:
        self._projectors = {
            node_id: OutputProjector(output)
            for node_id, output in outputs_by_node.items()
        }
        self._workflow_projector = OutputProjector(workflow_output)
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
        projector = self._workflow_run_projector
        return projector.render_run(event, origin) if projector is not None else ""


__all__ = [
    "EventOutputError",
    "OutputProjector",
    "WorkflowOutputProjector",
]
