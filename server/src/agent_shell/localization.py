from __future__ import annotations

import math
import re
from collections.abc import Mapping

from agent_shell.redaction import redact_for_boundary


MessageArg = str | int | float | bool | None

_MESSAGE_KEY_PATTERN = re.compile(
    r"^[a-z][A-Za-z0-9]*(?:\.[a-z][A-Za-z0-9]*)+$"
)


def normalize_message_key(value: str) -> str:
    if _MESSAGE_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError(f"Invalid localized message key: {value!r}")
    return value


def normalize_message_args(
    values: Mapping[str, MessageArg] | None = None,
) -> dict[str, MessageArg]:
    normalized: dict[str, MessageArg] = {}
    for key, value in (values or {}).items():
        if not isinstance(key, str) or not key:
            raise TypeError("Localized message argument names must be non-empty strings")
        if isinstance(value, str):
            safe = redact_for_boundary("preflight-diagnostic", value)
            normalized[key] = safe if isinstance(safe, str) else "[UNAVAILABLE]"
            continue
        if value is None or isinstance(value, (bool, int)):
            normalized[key] = value
            continue
        if isinstance(value, float) and math.isfinite(value):
            normalized[key] = value
            continue
        raise TypeError(
            "Localized message arguments must be finite JSON primitive values"
        )
    return normalized


def localized_message(
    message_key: str,
    message_args: Mapping[str, MessageArg] | None = None,
) -> dict[str, object]:
    return {
        "message_key": normalize_message_key(message_key),
        "message_args": normalize_message_args(message_args),
    }
