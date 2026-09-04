from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_shell.configuration.identity import ConfigurationName
from agent_shell.contracts import RequiredReference

class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: ConfigurationName
    description: Annotated[str, Field(max_length=2_000)] = ""
    workflow_event_output_id: RequiredReference | None = None
    response_stream_scheduling_id: RequiredReference | None = None
    durability: Literal["sync", "async", "exit"] = "async"
    on_disconnect: Literal["cancel", "continue"] = "cancel"
    recursion_limit: Annotated[int, Field(ge=1)] = 1_000_000
    max_concurrency: Annotated[int, Field(ge=1)] = 100
