from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from agent_shell.graph_schema import (
    GraphSchema,
    GraphSchemaError,
    compile_graph_schema,
)
from agent_shell.runtime.state import (
    validate_workflow_state_update,
    wrap_workflow_state_update,
)


WorkflowStateSchemaError = GraphSchemaError


def compile_workflow_state_schema(source: str | None) -> GraphSchema | None:
    """Compile the optional Pydantic State model for one Workflow."""

    return compile_graph_schema(source)


def validate_workflow_state_schema(source: str | None) -> None:
    """Validate one Workflow Python schema declaration."""

    compile_graph_schema(source)


def validate_workflow_state(
    state: Mapping[str, Any],
    schema: GraphSchema | None,
) -> None:
    """Validate one flat State value against the optional Pydantic model."""

    try:
        validate_workflow_state_update(wrap_workflow_state_update(state))
    except ValidationError as exc:
        raise WorkflowStateSchemaError(str(exc)) from exc
    if schema is not None:
        schema.validate_state(state)


__all__ = [
    "WorkflowStateSchemaError",
    "compile_workflow_state_schema",
    "validate_workflow_state",
    "validate_workflow_state_schema",
]
