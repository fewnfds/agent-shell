from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from agent_shell.configuration.identity import ConfigurationId


McpRawToolName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class McpToolSelection(BaseModel):
    """Portable selection of raw Tool names published by one MCP server."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["all", "include"] = "all"
    tools: list[McpRawToolName] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tools(self) -> "McpToolSelection":
        if len(self.tools) != len(set(self.tools)):
            raise ValueError("MCP Tool selection must not contain duplicates")
        if self.mode == "all" and self.tools:
            raise ValueError("all MCP Tool selection must not list Tool names")
        if self.mode == "include" and not self.tools:
            raise ValueError("include MCP Tool selection requires at least one Tool name")
        return self


class McpReference(BaseModel):
    """Attach one portable MCP requirement to one capability consumer."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    requirement_id: ConfigurationId
    tool_selection: McpToolSelection = Field(default_factory=McpToolSelection)


__all__ = ["McpRawToolName", "McpReference", "McpToolSelection"]
