from __future__ import annotations

from collections.abc import Mapping

from agent_shell.event_output_packages import (
    EventOutputCallable,
    EventOutputOrigin,
    EventRunOutputCallable,
    EventSegmentEndCallable,
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
        segment_end: EventSegmentEndCallable | None = None,
        run_output: EventRunOutputCallable | None = None,
    ) -> None:
        self._output = output
        self._segment_end = segment_end
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

    def render_segment_end(
        self,
        event: Mapping[str, object],
        origin: EventOutputOrigin,
    ) -> str:
        if self._segment_end is None:
            return ""
        try:
            value = self._segment_end(event, origin)
            if not isinstance(value, str):
                raise TypeError("segment_end(event, origin) must return a string")
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


__all__ = [
    "EventOutputError",
    "OutputProjector",
]
