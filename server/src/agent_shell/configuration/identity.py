from __future__ import annotations

import re
from typing import Annotated
from uuid import uuid4

from pydantic import AfterValidator, Field


CONFIGURATION_ID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_CONFIGURATION_ID = re.compile(CONFIGURATION_ID_PATTERN)
_WINDOWS_INVALID_NAME_CHARACTERS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)

ConfigurationId = Annotated[
    str,
    Field(
        strict=True,
        min_length=36,
        max_length=36,
        pattern=CONFIGURATION_ID_PATTERN,
    ),
]


def is_configuration_id(value: object) -> bool:
    return isinstance(value, str) and _CONFIGURATION_ID.fullmatch(value) is not None


def require_configuration_id(value: object, *, label: str) -> str:
    if not is_configuration_id(value):
        raise ValueError(
            f"{label} must be a canonical lowercase UUID4 configuration id"
        )
    return value


def new_configuration_id() -> str:
    return str(uuid4())


def normalize_configuration_name(
    value: object,
    *,
    label: str = "configuration name",
) -> str:
    """Return one Windows-safe display name used as a physical directory name."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    name = value.strip()
    if name in {".", ".."}:
        raise ValueError(f"{label} must be a valid Windows file name")
    if name.endswith((" ", ".")):
        raise ValueError(f"{label} must not end with a space or period")
    if any(
        character in _WINDOWS_INVALID_NAME_CHARACTERS or ord(character) < 32
        for character in name
    ):
        raise ValueError(
            f'{label} must not contain Windows-reserved characters \\/:*?"<>| '
            "or control characters"
        )
    reserved_candidate = name.split(".", 1)[0].upper()
    if reserved_candidate in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{label} must not use a Windows-reserved device name")
    return name


ConfigurationName = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=120),
    AfterValidator(normalize_configuration_name),
]


def name_collision_key(value: str) -> str:
    return normalize_configuration_name(value).casefold()


__all__ = [
    "CONFIGURATION_ID_PATTERN",
    "ConfigurationId",
    "ConfigurationName",
    "is_configuration_id",
    "name_collision_key",
    "new_configuration_id",
    "normalize_configuration_name",
    "require_configuration_id",
]
