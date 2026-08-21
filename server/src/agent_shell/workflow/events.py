from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from agent_shell.contracts import RequiredReference
from agent_shell.workflow.contracts import NodeId


WORKFLOW_CUSTOM_EVENT_SCHEMA = "agent-shell.workflow.custom-event.v1"


class WorkflowEventSourceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_type: Literal["agent", "subagent", "script"]
    workflow_node_id: NodeId
    agent_profile_id: RequiredReference | None = None
    subagent_profile_id: RequiredReference | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "WorkflowEventSourceV1":
        if self.source_type == "agent" and self.agent_profile_id is None:
            raise ValueError("agent events require agent_profile_id")
        if self.source_type == "subagent" and (
            self.agent_profile_id is None or self.subagent_profile_id is None
        ):
            raise ValueError(
                "subagent events require agent_profile_id and subagent_profile_id"
            )
        if self.source_type == "script" and (
            self.agent_profile_id is not None or self.subagent_profile_id is not None
        ):
            raise ValueError("script events must not claim an Agent profile identity")
        return self


class WorkflowCustomEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_name: Literal["agent-shell.workflow.custom-event.v1"] = (
        WORKFLOW_CUSTOM_EVENT_SCHEMA
    )
    source: WorkflowEventSourceV1
    channel: Annotated[
        str,
        Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9._-]*$"),
    ]
    data: JsonValue

def emit_workflow_custom_event(event: WorkflowCustomEventV1) -> None:
    """Write a server-owned custom event from inside a LangGraph node or tool."""

    from langgraph.config import get_stream_writer

    get_stream_writer()(event.model_dump(mode="json"))


__all__ = [
    "WORKFLOW_CUSTOM_EVENT_SCHEMA",
    "WorkflowCustomEventV1",
    "WorkflowEventSourceV1",
    "emit_workflow_custom_event",
]
