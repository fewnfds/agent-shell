from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Iterable

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


@dataclass(frozen=True, slots=True)
class PythonRequirements:
    values: tuple[str, ...]
    fingerprint: str


class PythonRequirementsError(ValueError):
    def __init__(self, code: str, message: str, *, line: int = 0, package: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.line = line
        self.package = package


def _fingerprint(values: tuple[str, ...]) -> str:
    encoded = json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def parse_python_requirements(lines: Iterable[str]) -> PythonRequirements:
    source = tuple(str(value) for value in lines)
    parsed: dict[str, str] = {}
    for line_number, raw_line in enumerate(source, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-") or "\\" in line or "://" in line:
            raise PythonRequirementsError(
                "invalid",
                f"requirement line {line_number} is not a package requirement",
                line=line_number,
            )
        try:
            requirement = Requirement(line)
        except InvalidRequirement as exc:
            raise PythonRequirementsError(
                "invalid",
                f"requirement line {line_number} is invalid",
                line=line_number,
            ) from exc
        if requirement.url is not None:
            raise PythonRequirementsError(
                "invalid",
                f"requirement line {line_number} may not use a direct URL",
                line=line_number,
            )
        name = canonicalize_name(requirement.name)
        if name in parsed:
            raise PythonRequirementsError(
                "duplicate",
                f"requirements declare {requirement.name!r} more than once",
                line=line_number,
                package=requirement.name,
            )
        parsed[name] = str(requirement)
    values = tuple(parsed[name] for name in sorted(parsed))
    return PythonRequirements(values, _fingerprint(values))


__all__ = [
    "PythonRequirements",
    "PythonRequirementsError",
    "parse_python_requirements",
]
