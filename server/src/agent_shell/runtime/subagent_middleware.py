from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent_shell.runtime.errors import AgentRuntimeError


def make_subagent_middleware_override(
    *,
    backend: Any,
    subagents: Sequence[dict[str, Any]],
    task_description: str | None,
    middleware: Sequence[Any],
) -> Any | None:
    """Build the official same-name replacement for a custom task description."""

    if task_description is None:
        return None

    try:
        from deepagents.middleware import SubAgentMiddleware
        from deepagents.middleware._state import private_state_field_names
        from deepagents.middleware.summarization import SummarizationState

        state_schemas = [
            SummarizationState,
            *(
                state_schema
                for item in middleware
                if (state_schema := getattr(item, "state_schema", None)) is not None
            ),
        ]
        return SubAgentMiddleware(
            backend=backend,
            subagents=subagents,
            task_description=task_description,
            private_state_keys=private_state_field_names(*state_schemas),
        )
    except Exception as exc:
        raise AgentRuntimeError(
            "subagent_configuration_failed",
            "The selected synchronous Subagent configuration is invalid.",
            status_code=422,
        ) from exc

