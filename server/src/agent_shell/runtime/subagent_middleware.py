from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent_shell.runtime.agent_compilation import enable_deepagents_trace_inputs
from agent_shell.runtime.errors import AgentRuntimeError


def make_subagent_middleware_override(
    *,
    backend: Any,
    subagents: Sequence[dict[str, Any]],
    task_description: str | None,
    middleware: Sequence[Any],
    state_schema: type | None = None,
    workflow_debug_capture_enabled: bool = False,
) -> Any | None:
    """Build the official same-name replacement with Run-local tracing."""

    try:
        from deepagents.middleware import SubAgentMiddleware
        from deepagents.middleware._state import private_state_field_names
        from deepagents.middleware.summarization import SummarizationState

        state_schemas = [SummarizationState]
        if state_schema is not None:
            state_schemas.insert(0, state_schema)
        state_schemas.extend(
            candidate_schema
            for item in middleware
            if (
                candidate_schema := getattr(item, "state_schema", None)
            ) is not None
        )
        replacement = SubAgentMiddleware(
            backend=backend,
            subagents=subagents,
            task_description=task_description,
            private_state_keys=private_state_field_names(*state_schemas),
            state_schema=state_schema,
        )
        enable_deepagents_trace_inputs(
            (replacement,),
            debug_capture=workflow_debug_capture_enabled,
        )
        return replacement
    except Exception as exc:
        raise AgentRuntimeError(
            "subagent_configuration_failed",
            "The selected synchronous Subagent configuration is invalid.",
            status_code=422,
        ) from exc
