from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_shell.contracts import RequiredReference

WorkflowRole = Literal["parent", "child"]


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Annotated[str, Field(min_length=1, max_length=120)]
    workflow_role: WorkflowRole
    description: Annotated[str, Field(max_length=2_000)] = ""
    checkpointer_id: RequiredReference | None = None
    workflow_event_output_id: RequiredReference | None = None
    cancel_on_upstream_termination: bool = True
    recursion_limit: Annotated[int, Field(ge=1)] = 1_000_000
    execution_timeout_seconds: Annotated[int, Field(ge=1)] = 1_200
    max_concurrency: Annotated[int, Field(ge=1)] = 100
