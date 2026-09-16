"""Node-scoped entry point a Command Node uses to call one External Agent.

The Workflow Node owns the binding: one node names one External Agent preset,
and that preset runs inside the Lifecycle of the current Run. The facade stays
a plain class so injecting it into a graph does not drag dataclass field types
through Pydantic schema building.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_shell.contracts import ExternalAgentProfile
    from agent_shell.external_agents.contracts import (
        ExternalAgentRunEvent,
        ExternalAgentRunResult,
    )
    from agent_shell.external_agents.runtime import AntigravityRunner


class ExternalAgentCommands:
    """One External Agent preset bound to one Workflow Node invocation."""

    def __init__(
        self,
        runner: "AntigravityRunner",
        profile: "ExternalAgentProfile",
        *,
        preset_id: str,
        lifecycle_id: str,
    ) -> None:
        self.__runner = runner
        self.__profile = profile
        self.__preset_id = preset_id
        self.__lifecycle_id = lifecycle_id

    @property
    def name(self) -> str:
        return self.__profile.name

    @property
    def agent_name(self) -> str:
        return self.__profile.agent_name

    async def run(
        self,
        prompt: str,
        *,
        conversation: str | None = None,
        on_event: "Callable[[ExternalAgentRunEvent], None] | None" = None,
    ) -> "ExternalAgentRunResult":
        """Start one CLI process and return its terminal result."""

        return await self.__runner.run(
            self.__profile,
            external_agent_id=self.__preset_id,
            lifecycle_id=self.__lifecycle_id,
            prompt=prompt,
            conversation=conversation,
            on_event=on_event,
        )


__all__ = ["ExternalAgentCommands"]
