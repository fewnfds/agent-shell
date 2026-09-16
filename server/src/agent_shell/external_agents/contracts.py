"""Run-level contracts shared by the runner, the monitor, and Command Nodes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


ExternalAgentRunStatus = Literal["success", "timeout", "denied", "failed"]
NEW_CONVERSATION = "new"
CONTINUE_LATEST_CONVERSATION = "continue-latest"


@dataclass(frozen=True)
class ExternalAgentRunEvent:
    """One normalized event, also persisted to ``events.ndjson``."""

    kind: str
    payload: Mapping[str, object]
    at: str

    def as_record(self) -> dict[str, object]:
        return {"kind": self.kind, "at": self.at, "payload": dict(self.payload)}


@dataclass(frozen=True)
class ExternalAgentRunResult:
    """Final state of one CLI process plus the evidence it left behind."""

    status: ExternalAgentRunStatus
    response: str
    conversation_id: str
    conversation_requested: str
    conversation_reused: bool | None
    exit_code: int | None
    duration_ms: int
    usage: Mapping[str, int]
    denied_actions: tuple[str, ...]
    error_code: str | None
    error_message: str | None
    session_directory: str
    event_log: str
    stderr_log: str
    result_file: str


__all__ = [
    "CONTINUE_LATEST_CONVERSATION",
    "NEW_CONVERSATION",
    "ExternalAgentRunEvent",
    "ExternalAgentRunResult",
    "ExternalAgentRunStatus",
]
