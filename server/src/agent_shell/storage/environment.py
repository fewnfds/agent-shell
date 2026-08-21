from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import threading
from types import MappingProxyType
from typing import Mapping

from agent_shell.storage.atomic_files import write_text_atomic
from agent_shell.storage.configuration_mutations import ConfigurationMutationCoordinator


SYSTEM_SETTINGS_ENVIRONMENT_OWNER = "system-settings"
API_SERVER_ENVIRONMENT_OWNER = "api-server"
MODEL_CONNECTION_ENVIRONMENT_OWNER = "model-connections"

_EXACT_OWNER_BY_NAME = {
    "AGENT_SHELL_MANAGEMENT_TOKEN": SYSTEM_SETTINGS_ENVIRONMENT_OWNER,
    "LANGSMITH_API_KEY": SYSTEM_SETTINGS_ENVIRONMENT_OWNER,
    "AGENT_SHELL_API_KEY": API_SERVER_ENVIRONMENT_OWNER,
}
_MODEL_SECRET_ENVIRONMENT = re.compile(
    r"^AGENT_SHELL_MODEL_[0-9A-F]{32}_API_KEY$"
)
_ENVIRONMENT_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_ENVIRONMENT_OWNERS = frozenset(
    {
        SYSTEM_SETTINGS_ENVIRONMENT_OWNER,
        API_SERVER_ENVIRONMENT_OWNER,
        MODEL_CONNECTION_ENVIRONMENT_OWNER,
    }
)


class EnvironmentFormatError(ValueError):
    pass


class EnvironmentOwnershipError(ValueError):
    def __init__(self, names: tuple[str, ...]) -> None:
        self.names = tuple(sorted(set(names)))
        super().__init__("environment keys do not have a registered owner")


def is_model_secret_environment_name(value: str) -> bool:
    return _MODEL_SECRET_ENVIRONMENT.fullmatch(value) is not None


def environment_owner_for_name(name: str) -> str | None:
    owner = _EXACT_OWNER_BY_NAME.get(name)
    if owner is not None:
        return owner
    if is_model_secret_environment_name(name):
        return MODEL_CONNECTION_ENVIRONMENT_OWNER
    return None


def unknown_environment_names(values: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name in values
            if name.startswith("AGENT_SHELL_")
            and environment_owner_for_name(name) is None
        )
    )


def parse_environment_text(text: str) -> dict[str, str]:
    if text.startswith("\ufeff"):
        raise EnvironmentFormatError("environment file must be UTF-8 without BOM")
    values: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise EnvironmentFormatError(
                f"environment line {line_number} must not be empty"
            )
        name, separator, encoded = line.partition("=")
        if (
            not separator
            or _ENVIRONMENT_NAME.fullmatch(name) is None
            or name in values
        ):
            raise EnvironmentFormatError(
                f"environment line {line_number} is invalid"
            )
        try:
            value = json.loads(encoded)
        except (json.JSONDecodeError, TypeError) as exc:
            raise EnvironmentFormatError(
                f"environment line {line_number} has an invalid value"
            ) from exc
        if not isinstance(value, str) or "\x00" in value:
            raise EnvironmentFormatError(
                f"environment line {line_number} must contain a JSON string"
            )
        values[name] = value
    return values


def serialize_environment(values: Mapping[str, str]) -> str:
    lines: list[str] = []
    for name, value in sorted(values.items()):
        if _ENVIRONMENT_NAME.fullmatch(name) is None:
            raise EnvironmentFormatError(f"environment key is invalid: {name}")
        if not isinstance(value, str) or "\x00" in value:
            raise EnvironmentFormatError(
                f"environment value is invalid for key: {name}"
            )
        lines.append(f"{name}={json.dumps(value, ensure_ascii=False)}")
    return "\n".join(lines) + ("\n" if lines else "")


def read_environment_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return parse_environment_text(path.read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    _values: Mapping[str, str]

    @classmethod
    def capture(cls, values: Mapping[str, str]) -> "EnvironmentSnapshot":
        return cls(MappingProxyType(dict(values)))

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def owned_values(self, owner: str) -> dict[str, str]:
        return {
            name: value
            for name, value in self._values.items()
            if environment_owner_for_name(name) == owner
        }

    def as_dict(self) -> dict[str, str]:
        return dict(self._values)


class InstanceEnvironmentStore:
    """The only writer for the instance-owned secret environment file."""

    def __init__(
        self,
        path: Path,
        *,
        mutations: ConfigurationMutationCoordinator | None = None,
    ) -> None:
        self.path = Path(path).resolve()
        self._mutations = mutations or ConfigurationMutationCoordinator()
        self._lock = threading.RLock()

    @staticmethod
    def _validate_owner(owner: str) -> None:
        if owner not in _ENVIRONMENT_OWNERS:
            raise EnvironmentOwnershipError((owner,))

    @staticmethod
    def _validate_owned_names(owner: str, names: set[str]) -> None:
        invalid = tuple(
            name for name in names if environment_owner_for_name(name) != owner
        )
        if invalid:
            raise EnvironmentOwnershipError(invalid)

    def _load(self) -> dict[str, str]:
        values = read_environment_file(self.path)
        unknown = unknown_environment_names(values)
        if unknown:
            raise EnvironmentOwnershipError(unknown)
        return values

    def snapshot(self) -> EnvironmentSnapshot:
        with self._lock:
            return EnvironmentSnapshot.capture(self._load())

    def get(self, name: str) -> str | None:
        return self.snapshot().get(name)

    def owned_values(self, owner: str) -> dict[str, str]:
        self._validate_owner(owner)
        return self.snapshot().owned_values(owner)

    def patch(
        self,
        owner: str,
        *,
        set_values: Mapping[str, str] | None = None,
        remove_keys: set[str] | frozenset[str] = frozenset(),
    ) -> EnvironmentSnapshot:
        self._validate_owner(owner)
        replacements = dict(set_values or {})
        replacement_names = set(replacements)
        removals = set(remove_keys)
        if replacement_names.intersection(removals):
            raise ValueError("environment patch cannot set and remove the same key")
        self._validate_owned_names(owner, replacement_names | removals)
        serialize_environment(replacements)

        with self._mutations.mutation(), self._lock:
            candidate = self._load()
            candidate.update(replacements)
            for name in removals:
                candidate.pop(name, None)
            write_text_atomic(self.path, serialize_environment(candidate))
            return EnvironmentSnapshot.capture(candidate)

    def replace_owned(
        self,
        owner: str,
        values: Mapping[str, str],
    ) -> EnvironmentSnapshot:
        self._validate_owner(owner)
        replacements = dict(values)
        self._validate_owned_names(owner, set(replacements))
        with self._mutations.mutation(), self._lock:
            current = self._load()
            removals = {
                name
                for name in current
                if environment_owner_for_name(name) == owner
                and name not in replacements
            }
            candidate = {
                name: value
                for name, value in current.items()
                if name not in removals
            }
            candidate.update(replacements)
            write_text_atomic(self.path, serialize_environment(candidate))
            return EnvironmentSnapshot.capture(candidate)


__all__ = [
    "API_SERVER_ENVIRONMENT_OWNER",
    "EnvironmentFormatError",
    "EnvironmentOwnershipError",
    "EnvironmentSnapshot",
    "InstanceEnvironmentStore",
    "MODEL_CONNECTION_ENVIRONMENT_OWNER",
    "SYSTEM_SETTINGS_ENVIRONMENT_OWNER",
    "environment_owner_for_name",
    "is_model_secret_environment_name",
    "parse_environment_text",
    "read_environment_file",
    "serialize_environment",
    "unknown_environment_names",
]
