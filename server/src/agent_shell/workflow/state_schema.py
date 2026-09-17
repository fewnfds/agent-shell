from __future__ import annotations

from collections.abc import Mapping
from functools import cache
import json
from typing import Any

from jsonschema.exceptions import SchemaError, best_match
from jsonschema.protocols import Validator
from jsonschema.validators import validator_for


class WorkflowStateSchemaError(ValueError):
    """One declared Workflow State schema or State value is unusable."""


def _canonical_json(schema: Mapping[str, Any]) -> str:
    return json.dumps(
        schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@cache
def _value_validator(schema_json: str) -> Validator:
    schema = json.loads(schema_json)
    validator = validator_for(schema)
    validator.check_schema(schema)
    return validator(schema)


def validate_workflow_state_schema(schema: Mapping[str, Any]) -> None:
    """Reject a ``state_schema`` that cannot describe a flat State object."""

    if schema.get("type") != "object":
        raise WorkflowStateSchemaError(
            "The Workflow state_schema must declare \"type\": \"object\"."
        )
    try:
        validator_class = validator_for(schema)
        validator_class.check_schema(dict(schema))
    except SchemaError as exc:
        location = "/".join(str(part) for part in exc.absolute_path)
        detail = f"{location}: {exc.message}" if location else exc.message
        raise WorkflowStateSchemaError(
            f"The Workflow state_schema is not a valid JSON Schema: {detail}"
        ) from exc


def validate_workflow_state(
    state: Mapping[str, Any],
    schema: Mapping[str, Any] | None,
) -> None:
    """Validate one flat State value against the optional declared schema."""

    if schema is None:
        return
    try:
        validator = _value_validator(_canonical_json(schema))
    except SchemaError as exc:
        raise WorkflowStateSchemaError(
            f"The Workflow state_schema is not a valid JSON Schema: {exc.message}"
        ) from exc
    error = best_match(validator.iter_errors(dict(state)))
    if error is None:
        return
    location = "/".join(str(part) for part in error.absolute_path)
    detail = f"{location}: {error.message}" if location else error.message
    raise WorkflowStateSchemaError(
        f"The Workflow State does not satisfy the declared state_schema: {detail}"
    )


__all__ = [
    "WorkflowStateSchemaError",
    "validate_workflow_state",
    "validate_workflow_state_schema",
]
