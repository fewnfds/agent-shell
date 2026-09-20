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
        source_exception_type: str = "",
        diagnostic_id: str = "",
        decoded_from_server: bool = False,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.validation_report = validation_report
        self.source_exception_type = source_exception_type
        self.diagnostic_id = diagnostic_id
        self.decoded_from_server = decoded_from_server
        super().__init__(message)

    def __str__(self) -> str:
        if self.decoded_from_server:
            return self.message
        return encode_server_run_error(self)


def describe_exception(exc: BaseException) -> str:
    """Preserve the concrete failure and its explicit exception chain."""

    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, AgentRuntimeError):
            part = current.message.strip() or current.code
        else:
            message = str(current).strip()
            part = (
                f"{type(current).__name__}: {message}"
                if message
                else type(current).__name__
            )
        if not parts or part != parts[-1]:
            parts.append(part)
        current = current.__cause__ or current.__context__
    return " <- ".join(parts)


_SERVER_RUN_ERROR_PREFIX = "agent-shell.runtime-error.v1:"


def encode_server_run_error(
    error: AgentRuntimeError,
    *,
    detail_exception: BaseException | None = None,
) -> str:
    """Serialize a classified error and its local diagnostic reference.

    Server transports this envelope as a plain string. The real failure is a
    local diagnostic fact created where the exception was still alive, so the
    envelope only carries classification plus the ``diagnostic_id`` reference.
    """

    source = detail_exception or error.__cause__ or (
        None if error.__suppress_context__ else error.__context__
    )
    message = describe_exception(source) if source is not None else error.message
    source_exception_type = error.source_exception_type
    diagnostic_id = error.diagnostic_id
    if source is not None:
        if isinstance(source, AgentRuntimeError):
            source_exception_type = source.source_exception_type or source_exception_type
            diagnostic_id = source.diagnostic_id or diagnostic_id
        else:
            source_exception_type = type(source).__name__

    return _SERVER_RUN_ERROR_PREFIX + json.dumps(
        {
            "code": error.code,
            "message": message,
            "status_code": error.status_code,
            "source_exception_type": source_exception_type,
            "diagnostic_id": diagnostic_id,
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
    source_exception_type = payload.get("source_exception_type", "")
    diagnostic_id = payload.get("diagnostic_id", "")
    if (
        not isinstance(code, str)
        or not code
        or not isinstance(message, str)
        or not message
        or not isinstance(status_code, int)
        or isinstance(status_code, bool)
        or not 400 <= status_code <= 599
        or not isinstance(source_exception_type, str)
        or not isinstance(diagnostic_id, str)
    ):
        return None
    return AgentRuntimeError(
        code,
        message,
        status_code=status_code,
        source_exception_type=source_exception_type,
        diagnostic_id=diagnostic_id,
        decoded_from_server=True,
    )


__all__ = [
    "AgentRuntimeError",
    "decode_server_run_error",
    "describe_exception",
    "encode_server_run_error",
]
