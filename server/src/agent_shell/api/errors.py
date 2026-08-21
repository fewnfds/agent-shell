from __future__ import annotations

from fastapi import HTTPException

from agent_shell.localization import MessageArg, localized_message


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
