from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from agent_shell.configuration.identity import (
    CONFIGURATION_ID_PATTERN,
    ConfigurationId,
    normalize_configuration_name,
)

PACKAGE_ID_PATTERN = CONFIGURATION_ID_PATTERN
PackageId = ConfigurationId


def validate_package_folder(value: str) -> str:
    normalized = normalize_configuration_name(
        value,
        label="Python package folder",
    )
    if value != normalized:
        raise ValueError("Python package folder must be normalized")
    return normalized


PackageFolder = Annotated[
    str,
    Field(min_length=1),
    AfterValidator(validate_package_folder),
]


class PythonPackageReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    folder: PackageFolder


def validate_package_relative_path(value: str) -> str:
    if (
        not value
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
    try:
        return validate_package_folder(folder)
    except ValueError:
        return None


__all__ = [
    "PACKAGE_ID_PATTERN",
    "PackageFolder",
    "PackageId",
    "PythonPackageReference",
    "parse_package_folder",
    "validate_package_folder",
    "validate_package_relative_path",
]
