from __future__ import annotations

import json
import traceback
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
        remote_traceback: str = "",
        decoded_from_server: bool = False,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.validation_report = validation_report
        self.source_exception_type = source_exception_type
        self.remote_traceback = remote_traceback
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
            explicit_message = getattr(current, "safe_message", None)
            message = (
                explicit_message.strip()
                if isinstance(explicit_message, str) and explicit_message.strip()
                else str(current).strip()
            )
            part = (
                f"{type(current).__name__}: {message}"
                if message
                else type(current).__name__
            )
        if not parts or part != parts[-1]:
            parts.append(part)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return " <- ".join(parts)


_SERVER_RUN_ERROR_PREFIX = "agent-shell.runtime-error.v1:"


def encode_server_run_error(
    error: AgentRuntimeError,
    *,
    detail_exception: BaseException | None = None,
) -> str:
    """Serialize a classified error and its source through Server's error field."""

    source = detail_exception or error.__cause__ or (
        None if error.__suppress_context__ else error.__context__
    )
    message = describe_exception(source) if source is not None else error.message
    source_exception_type = error.source_exception_type
    if source is not None:
        source_exception_type = (
            source.source_exception_type
            if isinstance(source, AgentRuntimeError) and source.source_exception_type
            else type(source).__name__
        )
    remote_traceback = error.remote_traceback
    if source is not None:
        remote_traceback = (
            source.remote_traceback
            if isinstance(source, AgentRuntimeError) and source.remote_traceback
            else "".join(
                traceback.TracebackException.from_exception(source).format(chain=True)
            )
        )

    return _SERVER_RUN_ERROR_PREFIX + json.dumps(
        {
            "code": error.code,
            "message": message,
            "status_code": error.status_code,
            "source_exception_type": source_exception_type,
            "traceback": remote_traceback,
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
    remote_traceback = payload.get("traceback", "")
    if (
        not isinstance(code, str)
        or not code
        or not isinstance(message, str)
        or not message
        or not isinstance(status_code, int)
        or isinstance(status_code, bool)
        or not 400 <= status_code <= 599
        or not isinstance(source_exception_type, str)
        or not isinstance(remote_traceback, str)
    ):
        return None
    return AgentRuntimeError(
        code,
        message,
        status_code=status_code,
        source_exception_type=source_exception_type,
        remote_traceback=remote_traceback,
        decoded_from_server=True,
    )


__all__ = [
    "AgentRuntimeError",
    "decode_server_run_error",
    "describe_exception",
    "encode_server_run_error",
]
