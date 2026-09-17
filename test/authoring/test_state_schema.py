from __future__ import annotations

import pytest

from agent_shell.workflow.state_schema import (
    WorkflowStateSchemaError,
    validate_workflow_state,
    validate_workflow_state_schema,
)


def test_open_state_accepts_any_json_object() -> None:
    validate_workflow_state({"topic": "x", "count": 3}, None)
    validate_workflow_state({}, None)


def test_declared_state_schema_requires_an_object_document() -> None:
    with pytest.raises(WorkflowStateSchemaError, match="object"):
        validate_workflow_state_schema({"type": "string"})
    with pytest.raises(WorkflowStateSchemaError, match="object"):
        validate_workflow_state_schema({"properties": {"topic": {"type": "string"}}})


def test_declared_state_schema_must_be_a_valid_json_schema() -> None:
    with pytest.raises(WorkflowStateSchemaError, match="not a valid JSON Schema"):
        validate_workflow_state_schema(
            {"type": "object", "properties": {"topic": {"type": 7}}}
        )


def test_declared_state_schema_accepts_an_object_document() -> None:
    validate_workflow_state_schema(
        {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
            "additionalProperties": False,
        }
    )


def test_declared_state_schema_validates_types_and_unknown_keys() -> None:
    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "additionalProperties": False,
    }
    validate_workflow_state({"count": 1}, schema)
    with pytest.raises(WorkflowStateSchemaError, match="state_schema"):
        validate_workflow_state({"count": "many"}, schema)
    with pytest.raises(WorkflowStateSchemaError, match="state_schema"):
        validate_workflow_state({"unknown": 1}, schema)


def test_declared_state_schema_reports_missing_required_keys() -> None:
    schema = {
        "type": "object",
        "properties": {"topic": {"type": "string"}},
        "required": ["topic"],
    }
    with pytest.raises(WorkflowStateSchemaError, match="state_schema"):
        validate_workflow_state({}, schema)
