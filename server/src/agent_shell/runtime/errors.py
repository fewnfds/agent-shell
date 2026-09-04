from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_shell.validation.models import ValidationReport


class AgentRuntimeError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 500,
        validation_report: ValidationReport | None = None,
    ) -> None:
        self.code = code
        self.safe_message = message
        self.status_code = status_code
        self.validation_report = validation_report
        super().__init__(code)


_SERVER_RUN_ERROR_PREFIX = "agent-shell.runtime-error.v1:"


def encode_server_run_error(error: AgentRuntimeError) -> str:
    """Serialize one safe product error through Server's string error field."""

    return _SERVER_RUN_ERROR_PREFIX + json.dumps(
        {
            "code": error.code,
            "message": error.safe_message,
            "status_code": error.status_code,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def decode_server_run_error(value: object) -> AgentRuntimeError | None:
    """Recover a product error from an official Run lifecycle error string."""

    if not isinstance(value, str) or not value.startswith(_SERVER_RUN_ERROR_PREFIX):
        return None
    try:
        payload = json.loads(value.removeprefix(_SERVER_RUN_ERROR_PREFIX))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    code = payload.get("code")
    message = payload.get("message")
    status_code = payload.get("status_code")
    if (
        not isinstance(code, str)
        or not code
        or not isinstance(message, str)
        or not message
        or not isinstance(status_code, int)
        or isinstance(status_code, bool)
        or not 400 <= status_code <= 599
    ):
        return None
    return AgentRuntimeError(code, message, status_code=status_code)


__all__ = [
    "AgentRuntimeError",
    "decode_server_run_error",
    "encode_server_run_error",
]
