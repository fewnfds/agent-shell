from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from agent_shell.runtime.run_calls import RunCheckStatus, RunStatus


CheckpointMode = Literal["enabled", "disabled"]


class AgentRunHandle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    main_agent_id: str
    assistant_id: str
    thread_id: str
    run_id: str
    status: RunStatus
    checkpoint_mode: CheckpointMode


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
    checkpoint_mode: CheckpointMode = "enabled"
    output: dict[str, Any] | None = None


__all__ = ["AgentRunHandle", "AgentRunSnapshot", "CheckpointMode"]
