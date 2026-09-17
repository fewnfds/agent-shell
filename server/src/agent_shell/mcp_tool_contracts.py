from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from agent_shell.configuration.identity import ConfigurationId


MCP_TOOL_NAME_PATTERN = r"^[A-Za-z0-9._-]{1,128}$"
_MCP_TOOL_NAME = re.compile(MCP_TOOL_NAME_PATTERN)


def validate_mcp_tool_name(value: str) -> str:
    if _MCP_TOOL_NAME.fullmatch(value) is None:
        raise ValueError(
            "MCP Tool names may contain only ASCII letters, digits, '.', "
            "'_', and '-', and must be 1-128 characters."
        )
    return value


McpToolName = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=128),
    AfterValidator(validate_mcp_tool_name),
]


class McpToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: McpToolName
    description: str = ""
    python_schema_id: ConfigurationId | None = None


__all__ = [
    "MCP_TOOL_NAME_PATTERN",
    "McpToolDefinition",
    "McpToolName",
    "validate_mcp_tool_name",
]
