from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from agent_shell.runtime.run_calls import RunCheckStatus, RunStatus


class AgentRunHandle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    main_agent_id: str
    assistant_id: str
    thread_id: str
    run_id: str
    status: RunStatus


class AgentRunSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = ""
    caller_run_id: str = ""
    main_agent_id: str = ""
    main_agent_name: str = ""
    assistant_id: str = ""
    thread_id: str = ""
    run_id: str
    status: RunCheckStatus
    output: dict[str, Any] | None = None


__all__ = ["AgentRunHandle", "AgentRunSnapshot"]
