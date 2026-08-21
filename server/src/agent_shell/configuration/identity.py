from __future__ import annotations

import re
from typing import Annotated
from uuid import uuid4

from pydantic import Field


CONFIGURATION_ID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_CONFIGURATION_ID = re.compile(CONFIGURATION_ID_PATTERN)

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


def name_collision_key(value: str) -> str:
    return value.strip().casefold()


__all__ = [
    "CONFIGURATION_ID_PATTERN",
    "ConfigurationId",
    "is_configuration_id",
    "name_collision_key",
    "new_configuration_id",
    "require_configuration_id",
]
