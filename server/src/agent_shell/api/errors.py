from __future__ import annotations

from fastapi import HTTPException

from agent_shell.localization import MessageArg, localized_message

_COMPAT_FAILURE_MESSAGES = {
    "completion_cancelled": "The Lifecycle was cancelled.",
    "completion_failed": "The completion failed.",
    "configuration_snapshot_failed": "The request configuration could not be prepared.",
    "internal_error": "The request failed due to an internal server error.",
    "provider_request_failed": "The provider request failed.",
    "run_start_failed": "The Run could not be started.",
    "tool_execution_failed": "The tool execution failed.",
}


def compat_failure_message(code: str, status_code: int) -> str:
    """Stable classification disclosed on the OpenAI-compatible wire."""

    message = _COMPAT_FAILURE_MESSAGES.get(code)
    if message is not None:
        return message
    if status_code >= 500:
        return "The request failed due to an internal server error."
    if status_code == 422:
        return "The request could not be executed with the current configuration."
    return "The request was rejected."


def localized_error_detail(
    *,
    code: str,
    message_key: str,
    message: str,
    message_args: dict[str, MessageArg] | None = None,
) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        **localized_message(message_key, message_args),
    }


def management_error(
    status_code: int,
    *,
    code: str,
    message_key: str,
    message: str,
    message_args: dict[str, MessageArg] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=localized_error_detail(
            code=code,
            message_key=message_key,
            message=message,
            message_args=message_args,
        ),
    )
