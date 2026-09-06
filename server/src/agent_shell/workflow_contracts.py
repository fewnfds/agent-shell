from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from agent_shell.configuration.identity import ConfigurationName
from agent_shell.contracts import RequiredReference

class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: ConfigurationName
    description: str = ""
    is_model_entry: bool = False
    workflow_event_output_id: RequiredReference | None = None
    durability: Literal["sync", "async", "exit"] = "async"
    on_disconnect: Literal["cancel", "continue"] = "cancel"
