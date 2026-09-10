from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from langchain.agents.middleware.types import PrivateStateAttr

from agent_shell.runtime.errors import AgentRuntimeError


logger = logging.getLogger(__name__)


def _has_private_state_marker(annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin is Annotated:
        return any(
            metadata is PrivateStateAttr
            for metadata in get_args(annotation)[1:]
        )
    if origin is not None:
        return any(_has_private_state_marker(item) for item in get_args(annotation))
    return False


def _private_state_field_names(*state_schemas: type[object]) -> frozenset[str]:
    names: set[str] = set()
    for state_schema in state_schemas:
        try:
            hints = get_type_hints(state_schema, include_extras=True)
        except (NameError, TypeError, AttributeError):
            logger.warning(
                "Could not resolve annotations for state schema %s; its "
                "PrivateStateAttr fields will not be kept private.",
                getattr(state_schema, "__qualname__", state_schema),
            )
            continue
        names.update(
            name
            for name, annotation in hints.items()
            if _has_private_state_marker(annotation)
        )
    return frozenset(names)


def materialize_subagent_middleware(
    *,
    backend: Any,
    subagents: Sequence[dict[str, Any]],
    task_description: str | None,
    middleware: Sequence[Any],
    state_schema: type | None = None,
) -> Any:
    """Build the explicit synchronous delegation middleware."""

    try:
        from deepagents.middleware import SubAgentMiddleware
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
        return SubAgentMiddleware(
            backend=backend,
            subagents=subagents,
            task_description=task_description,
            private_state_keys=_private_state_field_names(*state_schemas),
            state_schema=state_schema,
        )
    except Exception as exc:
        raise AgentRuntimeError(
            "subagent_configuration_failed",
            "The selected synchronous Subagent configuration is invalid.",
            status_code=422,
        ) from exc
