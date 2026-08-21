from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from uuid import uuid4

from agent_shell.configuration.identity import require_configuration_id
from agent_shell.storage.atomic_files import write_text_atomic


REPOSITORY_SCHEMA_VERSION = 1
DEFAULT_REPOSITORY_NAME = "Default"


@dataclass(frozen=True, slots=True)
class ConfigurationRepositoryDescriptor:
    id: str
    name: str
    root: Path

    @property
    def python_packages_root(self) -> Path:
        return self.root / "python_package_instances"

    @property
    def skill_packages_root(self) -> Path:
        return self.root / "skill_package_instances"

    @property
    def imports_root(self) -> Path:
        return self.root / "configuration-imports"

    def as_dict(self, *, active: bool = False) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "schema_version": REPOSITORY_SCHEMA_VERSION,
            "active": active,
        }


def configuration_repositories_root(data_root: Path) -> Path:
    return data_root.resolve() / "configuration-repositories"


def active_repository_pointer(data_root: Path) -> Path:
    return data_root.resolve() / "config" / "active-configuration-repository.json"


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_text_atomic(path, text)


def _repository_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("configuration repository name is required")
    name = value.strip()
    if len(name) > 120:
        raise ValueError("configuration repository name must not exceed 120 characters")
    return name


def load_configuration_repository(root: Path) -> ConfigurationRepositoryDescriptor:
    root = root.resolve()
    manifest_path = root / "repository.json"
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"configuration repository manifest is invalid: {manifest_path}") from exc
    if not isinstance(value, dict) or set(value) != {"id", "name", "schema_version"}:
        raise ValueError(f"configuration repository manifest is invalid: {manifest_path}")
    repository_id = require_configuration_id(
        value.get("id"), label="configuration repository id"
    )
    if root.name != repository_id:
        raise ValueError("configuration repository folder must match its manifest id")
    if value.get("schema_version") != REPOSITORY_SCHEMA_VERSION:
        raise ValueError("configuration repository schema version is unsupported")
    return ConfigurationRepositoryDescriptor(
        id=repository_id,
        name=_repository_name(value.get("name")),
        root=root,
    )


def list_configuration_repositories(
    data_root: Path,
) -> tuple[ConfigurationRepositoryDescriptor, ...]:
    root = configuration_repositories_root(data_root)
    if not root.exists():
        return ()
    repositories: list[ConfigurationRepositoryDescriptor] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if path.is_dir():
            repositories.append(load_configuration_repository(path))
    return tuple(sorted(repositories, key=lambda item: (item.name.casefold(), item.id)))


def create_configuration_repository(
    data_root: Path,
    name: str,
    *,
    repository_id: str | None = None,
) -> ConfigurationRepositoryDescriptor:
    normalized_name = _repository_name(name)
    repository_id = require_configuration_id(
        repository_id or str(uuid4()), label="configuration repository id"
    )
    root = configuration_repositories_root(data_root) / repository_id
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError("configuration repository id already exists") from exc
    descriptor = ConfigurationRepositoryDescriptor(
        id=repository_id,
        name=normalized_name,
        root=root.resolve(),
    )
    try:
        _write_json_atomic(
            root / "repository.json",
            {
                "id": descriptor.id,
                "name": descriptor.name,
                "schema_version": REPOSITORY_SCHEMA_VERSION,
            },
        )
        for directory in (
            root / "components",
            root / "agents" / "main",
            root / "agents" / "subagent",
            root / "workflows",
            descriptor.python_packages_root,
            descriptor.skill_packages_root,
            descriptor.imports_root,
        ):
            directory.mkdir(parents=True, exist_ok=True)
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return descriptor


def write_active_configuration_repository(
    data_root: Path,
    repository_id: str,
) -> None:
    repository_id = require_configuration_id(
        repository_id, label="active configuration repository id"
    )
    _write_json_atomic(
        active_repository_pointer(data_root),
        {"repository_id": repository_id},
    )


def active_configuration_repository(
    data_root: Path,
) -> ConfigurationRepositoryDescriptor:
    pointer = active_repository_pointer(data_root)
    try:
        value = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("active configuration repository pointer is invalid") from exc
    if not isinstance(value, dict) or set(value) != {"repository_id"}:
        raise ValueError("active configuration repository pointer is invalid")
    repository_id = require_configuration_id(
        value.get("repository_id"), label="active configuration repository id"
    )
    return load_configuration_repository(
        configuration_repositories_root(data_root) / repository_id
    )


def ensure_active_configuration_repository(
    data_root: Path,
) -> ConfigurationRepositoryDescriptor:
    pointer = active_repository_pointer(data_root)
    if pointer.exists():
        return active_configuration_repository(data_root)
    existing = list_configuration_repositories(data_root)
    descriptor = (
        existing[0]
        if existing
        else create_configuration_repository(data_root, DEFAULT_REPOSITORY_NAME)
    )
    write_active_configuration_repository(data_root, descriptor.id)
    return descriptor


__all__ = [
    "ConfigurationRepositoryDescriptor",
    "REPOSITORY_SCHEMA_VERSION",
    "active_configuration_repository",
    "active_repository_pointer",
    "configuration_repositories_root",
    "create_configuration_repository",
    "ensure_active_configuration_repository",
    "list_configuration_repositories",
    "load_configuration_repository",
    "write_active_configuration_repository",
]
