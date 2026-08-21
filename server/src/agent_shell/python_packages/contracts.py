from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from agent_shell.configuration.identity import (
    CONFIGURATION_ID_PATTERN,
    ConfigurationId,
)

PACKAGE_ID_PATTERN = CONFIGURATION_ID_PATTERN
_UUID_FRAGMENT = PACKAGE_ID_PATTERN.removeprefix("^").removesuffix("$")
PACKAGE_FOLDER_PATTERN = rf"^{_UUID_FRAGMENT}$"
_PACKAGE_FOLDER = re.compile(PACKAGE_FOLDER_PATTERN)


PackageId = ConfigurationId


PackageFolder = Annotated[
    str,
    Field(min_length=36, max_length=36, pattern=PACKAGE_FOLDER_PATTERN),
]


class PythonPackageReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    folder: PackageFolder


def validate_package_relative_path(value: str) -> str:
    if (
        not value
        or len(value) > 240
        or value.startswith(("/", "\\"))
        or "\\" in value
        or ":" in value
        or "\x00" in value
    ):
        raise ValueError("Python package file paths must be relative POSIX paths")
    path = PurePosixPath(value)
    if path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Python package file paths must be normalized relative paths")
    return value


def parse_package_folder(folder: str) -> str | None:
    return folder if _PACKAGE_FOLDER.fullmatch(folder) is not None else None


__all__ = [
    "PACKAGE_FOLDER_PATTERN",
    "PACKAGE_ID_PATTERN",
    "PackageFolder",
    "PackageId",
    "PythonPackageReference",
    "parse_package_folder",
    "validate_package_relative_path",
]
