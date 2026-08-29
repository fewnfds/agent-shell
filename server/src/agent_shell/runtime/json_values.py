from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, message_to_dict
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool


_SECRET_FIELD_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bearer_token",
        "client_secret",
        "credential",
        "credentials",
        "management_token",
        "password",
        "proxy_authorization",
        "refresh_token",
        "secret",
        "secret_value",
        "token",
        "api_token",
        "x_api_key",
    }
)


def _type_name(value: object) -> str:
    value_type = value if isinstance(value, type) else type(value)
    module = getattr(value_type, "__module__", "")
    name = getattr(value_type, "__qualname__", value_type.__name__)
    return f"{module}.{name}" if module else name


def json_safe(
    value: Any,
    *,
    active: set[int] | None = None,
    redact_secret_fields: bool = True,
) -> Any:
    """Preserve runtime content while excluding configured secret fields."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return json_safe(
            value.value,
            active=active,
            redact_secret_fields=redact_secret_fields,
        )
    if callable(getattr(value, "get_secret_value", None)):
        return "[REDACTED]"
    if isinstance(value, bytes):
        return {
            "type": "bytes",
            "base64": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, Path):
        return str(value)

    active = active if active is not None else set()
    identity = id(value)
    if identity in active:
        return {"type": _type_name(value), "cycle": True}
    active.add(identity)
    try:
        if isinstance(value, BaseMessage):
            return json_safe(
                message_to_dict(value),
                active=active,
                redact_secret_fields=redact_secret_fields,
            )
        if isinstance(value, BaseTool):
            try:
                return json_safe(
                    convert_to_openai_tool(value),
                    active=active,
                    redact_secret_fields=False,
                )
            except (TypeError, ValueError):
                return {"type": _type_name(value), "name": value.name}
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for raw_key, item in value.items():
                key = str(raw_key)
                normalized_key = key.lower().replace("-", "_")
                result[key] = (
                    "[REDACTED]"
                    if redact_secret_fields
                    and normalized_key in _SECRET_FIELD_NAMES
                    else json_safe(
                        item,
                        active=active,
                        redact_secret_fields=redact_secret_fields,
                    )
                )
            return result
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            return [
                json_safe(
                    item,
                    active=active,
                    redact_secret_fields=redact_secret_fields,
                )
                for item in value
            ]
        if isinstance(value, (set, frozenset)):
            return [
                json_safe(
                    item,
                    active=active,
                    redact_secret_fields=redact_secret_fields,
                )
                for item in value
            ]
        if is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: json_safe(
                    getattr(value, field.name),
                    active=active,
                    redact_secret_fields=redact_secret_fields,
                )
                for field in fields(value)
            }
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                return json_safe(
                    model_dump(mode="json"),
                    active=active,
                    redact_secret_fields=redact_secret_fields,
                )
            except (TypeError, ValueError):
                try:
                    return json_safe(
                        model_dump(),
                        active=active,
                        redact_secret_fields=redact_secret_fields,
                    )
                except (TypeError, ValueError):
                    pass
        model_json_schema = getattr(value, "model_json_schema", None)
        if callable(model_json_schema):
            try:
                return {
                    "type": _type_name(value),
                    "schema": json_safe(
                        model_json_schema(),
                        active=active,
                        redact_secret_fields=redact_secret_fields,
                    ),
                }
            except (TypeError, ValueError):
                pass
        return {"type": _type_name(value)}
    finally:
        active.discard(identity)


__all__ = ["json_safe"]
