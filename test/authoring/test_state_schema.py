from __future__ import annotations

import pytest

from agent_shell.workflow.state_schema import (
    WorkflowStateSchemaError,
    compile_workflow_state_schema,
    validate_workflow_state,
    validate_workflow_state_schema,
)


STATE_SOURCE = """
from pydantic import BaseModel, ConfigDict


class State(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    topic: str
"""


def test_open_state_accepts_any_json_object() -> None:
    validate_workflow_state({"topic": "x", "count": 3}, None)
    validate_workflow_state({}, None)


def test_declared_state_schema_requires_a_pydantic_state() -> None:
    with pytest.raises(WorkflowStateSchemaError, match="Pydantic 'State'"):
        validate_workflow_state_schema("value = 1")

    with pytest.raises(WorkflowStateSchemaError, match="Pydantic BaseModel"):
        validate_workflow_state_schema(
            "from pydantic import BaseModel\nState = object\n"
        )


def test_declared_state_schema_must_be_valid_python() -> None:
    with pytest.raises(WorkflowStateSchemaError, match="could not be loaded"):
        validate_workflow_state_schema("class State(")


def test_declared_state_schema_accepts_a_pydantic_state() -> None:
    validate_workflow_state_schema(STATE_SOURCE)


def test_declared_state_schema_validates_types_and_unknown_keys() -> None:
    schema = compile_workflow_state_schema(STATE_SOURCE)
    validate_workflow_state({"count": 1, "topic": "x"}, schema)

    with pytest.raises(WorkflowStateSchemaError, match="count"):
        validate_workflow_state({"count": "many", "topic": "x"}, schema)
    with pytest.raises(WorkflowStateSchemaError, match="unknown"):
        validate_workflow_state(
            {"count": 1, "topic": "x", "unknown": True},
            schema,
        )


def test_declared_state_schema_reports_missing_required_keys() -> None:
    schema = compile_workflow_state_schema(STATE_SOURCE)
    with pytest.raises(WorkflowStateSchemaError, match="count"):
        validate_workflow_state({}, schema)
