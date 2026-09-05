from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import threading
from typing import Any, Callable
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import yaml

from agent_shell.configuration.identity import require_configuration_id
from agent_shell.configuration.identity import new_configuration_id as generate_configuration_id
from agent_shell.configuration.bundles.archive import (
    canonical_json_bytes,
    materialize_files,
    snapshot_directory,
)
from agent_shell.configuration.dependencies import (
    ConfigurationEntity,
    iter_configuration_entities,
    rewrite_configuration_references,
)
from agent_shell.configuration.repositories import (
    ConfigurationRepositoryDescriptor,
    REPOSITORY_SCHEMA_VERSION,
    configuration_repositories_root,
    create_configuration_repository,
    ensure_active_configuration_repository,
    find_configuration_repository,
    list_configuration_repositories,
    normalize_repository_name,
    PYTHON_PACKAGES_DIRECTORY,
    SKILL_PACKAGES_DIRECTORY,
    write_active_configuration_repository,
)
from agent_shell.configuration.storage import validate_configuration_snapshot
from agent_shell.python_packages.authoring import PACKAGE_COMPONENT_SPECS
from agent_shell.storage.atomic_files import write_text_atomic
from agent_shell.storage.configuration_mutations import ConfigurationMutationCoordinator
from agent_shell.storage.environment import (
    InstanceEnvironmentStore,
    environment_owner_for_name,
)
from agent_shell.settings import (
    DEFAULT_GRAPH_MAX_CONCURRENCY,
    DEFAULT_GRAPH_RECURSION_LIMIT,
    DEFAULT_N_JOBS_PER_WORKER,
)


CONFIG_VERSION = 2


class ActiveRepositoryChangedError(RuntimeError):
    """Raised when a request tries to commit against a different Repository."""


class ActiveRepositoryDeleteError(ValueError):
    """Raised when deletion targets the active Configuration Repository."""


def _default_config() -> dict[str, Any]:
    return {
        "config_version": CONFIG_VERSION,
        "components": {},
        "main_agents": [],
        "subagents": [],
        "workflows": [],
    }


def _default_system() -> dict[str, Any]:
    return {
        "config_version": CONFIG_VERSION,
        "settings": {
            "host": "127.0.0.1",
            "port": 19100,
            "n_jobs_per_worker": DEFAULT_N_JOBS_PER_WORKER,
            "recursion_limit": DEFAULT_GRAPH_RECURSION_LIMIT,
            "max_concurrency": DEFAULT_GRAPH_MAX_CONCURRENCY,
            "debug_port": None,
            "allow_remote": False,
            "langsmith_tracing_enabled": False,
            "langsmith_endpoint": "https://api.smith.langchain.com",
            "langsmith_project": "agent-shell",
            "langsmith_workspace_id": None,
            "cors_origins": [],
            "trusted_proxy_cidrs": [],
        },
        "api_server": {
            "enabled": True,
            "message_interception_enabled": False,
        },
        "history_retention": {
            "runtime_diagnostics": 20,
        },
        "workflow_lifecycles": {
            "retained_lifecycles": 20,
        },
        "configuration_validation": {"debounce_ms": 1000},
        "system_log": {"max_size_mib": 5},
    }


def _read_yaml(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(default)
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream) or {}
    if not isinstance(value, dict):
        raise ValueError(f"configuration file must contain a mapping: {path}")
    return value


def _dump_yaml(value: dict[str, Any]) -> str:
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _configuration_document(
    path: Path,
    document: dict[str, Any],
    *,
    kind: str,
    component_type: str = "",
    identity_field: str = "",
) -> tuple[str, dict[str, Any]]:
    expected_keys = {"kind", "schema_version", "id", "payload"}
    if component_type:
        expected_keys.update({"type", "name"})
    elif identity_field:
        expected_keys.add(identity_field)
    if set(document) != expected_keys:
        raise ValueError(f"configuration document envelope is invalid: {path}")
    if document.get("kind") != kind:
        raise ValueError(f"configuration document kind is invalid: {path}")
    if type(document.get("schema_version")) is not int or document.get(
        "schema_version"
    ) != CONFIG_VERSION:
        raise ValueError(f"configuration document schema_version is invalid: {path}")
    if component_type and document.get("type") != component_type:
        raise ValueError(f"configuration document type is invalid: {path}")
    item_id = require_configuration_id(
        document.get("id"),
        label=f"configuration document id in {path}",
    )
    if path.stem != item_id:
        raise ValueError(
            f"configuration filename must match its document id: {path}"
        )
    payload = document.get("payload")
    if not isinstance(payload, dict):
        raise ValueError(f"configuration payload must be a mapping: {path}")
    reserved_payload_fields = {"id"}
    if component_type:
        reserved_payload_fields.add("name")
    elif identity_field:
        reserved_payload_fields.add(identity_field)
    if reserved_payload_fields.intersection(payload):
        raise ValueError(
            f"configuration payload duplicates envelope identity: {path}"
        )
    return item_id, payload


class FileConfigRepository:
    """Persistent configuration repository backed by layered YAML files."""

    _COMPONENT_DIR = "components"
    _RECORD_SECTIONS = frozenset({"main_agents", "subagents", "workflows"})

    def __init__(
        self,
        data_root: Path,
        *,
        _config: dict[str, Any] | None = None,
        _system: dict[str, Any] | None = None,
        _persist: bool = True,
        _repository: ConfigurationRepositoryDescriptor | None = None,
        mutations: ConfigurationMutationCoordinator | None = None,
        environment: InstanceEnvironmentStore | None = None,
    ) -> None:
        self.data_root = data_root.resolve()
        self._instance_config_root = self.data_root / "config"
        self.system_path = self._instance_config_root / "system.yaml"
        self._lock = threading.RLock()
        self._mutations = mutations or ConfigurationMutationCoordinator()
        self._environment = environment or InstanceEnvironmentStore(
            self._instance_config_root / "agent-shell.env",
            mutations=self._mutations,
        )
        self._persist = _persist
        self._active_repository = (
            _repository
            if _repository is not None
            else (
                ensure_active_configuration_repository(self.data_root)
                if _persist
                else ConfigurationRepositoryDescriptor(
                    id="",
                    name="",
                    root=self._instance_config_root,
                )
            )
        )
        self._config = deepcopy(_config) if _config is not None else self._load_config()
        self._system = deepcopy(_system) if _system is not None else _read_yaml(self.system_path, _default_system())
        self._revision = 1
        self._normalize()
        validate_configuration_snapshot(
            self._config,
            config_version=CONFIG_VERSION,
        )
        if self._persist and not self.system_path.exists():
            write_text_atomic(self.system_path, _dump_yaml(self._system))

    @property
    def config_root(self) -> Path:
        return self._active_repository.root

    @property
    def components_root(self) -> Path:
        return self.config_root / self._COMPONENT_DIR

    @property
    def agents_root(self) -> Path:
        return self.config_root / "agents"

    @property
    def workflows_root(self) -> Path:
        return self.config_root / "workflows"

    @property
    def python_packages_root(self) -> Path:
        return self._active_repository.python_packages_root

    @property
    def skill_packages_root(self) -> Path:
        return self._active_repository.skill_packages_root

    @property
    def configuration_imports_root(self) -> Path:
        return self._active_repository.imports_root

    @property
    def repository_id(self) -> str:
        return self._active_repository.id

    @property
    def repository_name(self) -> str:
        return self._active_repository.name

    def _load_config_from(self, root: Path) -> dict[str, Any]:
        previous = self._active_repository
        self._active_repository = ConfigurationRepositoryDescriptor(
            id=previous.id,
            name=previous.name,
            root=root.resolve(),
        )
        try:
            return self._load_config()
        finally:
            self._active_repository = previous

    def _load_config(self) -> dict[str, Any]:
        config = _default_config()
        for directory in self.components_root.glob("*") if self.components_root.exists() else ():
            if not directory.is_dir():
                continue
            if directory.name == "model":
                raise ValueError(
                    "legacy model components are not accepted; use model-requirement "
                    "and instance model connections"
                )
            records: list[dict[str, Any]] = []
            for path in sorted(directory.glob("*.yaml")):
                document = _read_yaml(path, {})
                item_id, payload = _configuration_document(
                    path,
                    document,
                    kind="component",
                    component_type=directory.name,
                )
                record = {
                    **deepcopy(payload),
                    "id": item_id,
                    "name": document.get("name"),
                }
                records.append(record)
            config["components"][directory.name] = records

        for category, key, identity in (("main", "main_agents", "name"), ("subagent", "subagents", "component_name")):
            directory = self.agents_root / category
            records: list[dict[str, Any]] = []
            if directory.exists():
                for path in sorted(directory.glob("*.yaml")):
                    document = _read_yaml(path, {})
                    item_id, payload = _configuration_document(
                        path,
                        document,
                        kind="main_agent" if category == "main" else "subagent",
                        identity_field=identity,
                    )
                    records.append(
                        {
                            **deepcopy(payload),
                            "id": item_id,
                            identity: document.get(identity),
                        }
                    )
            config[key] = records

        if self.workflows_root.exists():
            for path in sorted(self.workflows_root.glob("*.yaml")):
                document = _read_yaml(path, {})
                item_id, payload = _configuration_document(
                    path,
                    document,
                    kind="workflow",
                )
                config["workflows"].append(
                    {**deepcopy(payload), "id": item_id}
                )
        return config

    @staticmethod
    def _normalize_config(config: dict[str, Any]) -> None:
        config.setdefault("config_version", CONFIG_VERSION)
        config.setdefault("components", {})
        config.setdefault("main_agents", [])
        config.setdefault("subagents", [])
        config.setdefault("workflows", [])
        components = config["components"]
        if not isinstance(components, dict):
            raise ValueError("config components must be a mapping")

    @staticmethod
    def _normalize_system(system: dict[str, Any]) -> None:
        system.setdefault("config_version", CONFIG_VERSION)
        defaults = _default_system()
        for section, value in defaults.items():
            if section == "config_version":
                continue
            current = system.setdefault(section, {})
            if isinstance(current, dict) and isinstance(value, dict):
                for key, default in value.items():
                    current.setdefault(key, deepcopy(default))
        system.pop("runtime_control", None)
        system.pop("runtime_diagnostics", None)
        history_retention = system.get("history_retention")
        if isinstance(history_retention, dict):
            history_retention.pop("runtime_log", None)
            history_retention.pop("workflow_debug_history", None)

    def _normalize(self) -> None:
        self._normalize_config(self._config)
        self._normalize_system(self._system)

    @classmethod
    def empty(cls, data_root: Path) -> "FileConfigRepository":
        return cls(
            data_root,
            _config=_default_config(),
            _system=_default_system(),
            _persist=False,
        )

    @classmethod
    def from_snapshot(
        cls,
        data_root: Path,
        config: dict[str, Any],
    ) -> "FileConfigRepository":
        """Build an isolated repository view for validation without persistence."""

        return cls(
            data_root,
            _config=config,
            _system=_default_system(),
            _persist=False,
        )

    def clone(self) -> "FileConfigRepository":
        with self._lock:
            return FileConfigRepository(
                self.data_root,
                _config=self._config,
                _system=self._system,
                _persist=False,
                _repository=self._active_repository,
                mutations=self._mutations,
                environment=self._environment,
            )

    def list_repositories(self) -> list[dict[str, object]]:
        with self._lock:
            active_id = self.repository_id
            return [
                item.as_dict(active=item.id == active_id)
                for item in list_configuration_repositories(self.data_root)
            ]

    def create_repository(self, name: str) -> dict[str, object]:
        with self._mutations.mutation(), self._lock:
            if any(
                item.name.casefold() == name.strip().casefold()
                for item in list_configuration_repositories(self.data_root)
            ):
                raise ValueError("configuration repository name already exists")
            descriptor = create_configuration_repository(self.data_root, name)
            return descriptor.as_dict(active=False)

    @staticmethod
    def _snapshot_from_entities(
        entities: list[ConfigurationEntity],
    ) -> dict[str, Any]:
        config = _default_config()
        for entity in entities:
            record = deepcopy(entity.payload)
            if entity.kind == "component":
                config["components"].setdefault(entity.component_type, []).append(
                    record
                )
            elif entity.kind == "main_agent":
                config["main_agents"].append(record)
            elif entity.kind == "subagent":
                config["subagents"].append(record)
            else:
                config["workflows"].append(record)
        return config

    def _repository_descriptor(
        self, repository_id: str
    ) -> ConfigurationRepositoryDescriptor:
        return find_configuration_repository(self.data_root, repository_id)

    def _copy_repository_assets(
        self,
        source: ConfigurationRepositoryDescriptor,
        target: ConfigurationRepositoryDescriptor,
        entities: list[ConfigurationEntity],
        target_ids: dict[str, str],
    ) -> None:
        for entity in entities:
            if entity.kind != "component":
                continue
            target_id = target_ids[entity.id]
            spec = PACKAGE_COMPONENT_SPECS.get(entity.component_type)
            if spec is not None:
                reference = entity.payload.get("python_package")
                if (
                    not isinstance(reference, dict)
                    or reference.get("folder") != entity.name
                ):
                    raise ValueError(
                        "Python package folder does not match its Component name"
                    )
                folder_name = str(reference["folder"])
                source_folder = (
                    source.python_packages_root / spec.directory / folder_name
                )
                files = snapshot_directory(
                    source_folder,
                    exclude_python_runtime=True,
                )
                target_folder = (
                    target.python_packages_root / spec.directory / folder_name
                )
                materialize_files(target_folder, files)
                manifest_path = target_folder / "package.json"
                try:
                    manifest = json.loads(
                        manifest_path.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        "Python package manifest is invalid"
                    ) from exc
                if not isinstance(manifest, dict):
                    raise ValueError("Python package manifest must be an object")
                manifest["id"] = target_id
                write_text_atomic(
                    manifest_path,
                    json.dumps(
                        manifest,
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                )
            if entity.component_type == "skill":
                reference = entity.payload.get("skill_package")
                if (
                    not isinstance(reference, dict)
                    or reference.get("folder") != entity.name
                ):
                    raise ValueError(
                        "Skill package folder does not match its Component name"
                    )
                folder_name = str(reference["folder"])
                materialize_files(
                    target.skill_packages_root / folder_name,
                    snapshot_directory(source.skill_packages_root / folder_name),
                )

    def copy_repository(
        self,
        source_id: str,
        name: str,
    ) -> tuple[dict[str, object], dict[str, str]]:
        normalized_name = normalize_repository_name(name)
        with self._mutations.mutation(), self._lock:
            repositories = list_configuration_repositories(self.data_root)
            if any(
                item.name.casefold() == normalized_name.casefold()
                for item in repositories
            ):
                raise ValueError("configuration repository name already exists")
            source = self._repository_descriptor(source_id)
            source_config = self._load_config_from(source.root)
            source_entities = list(iter_configuration_entities(source_config))
            existing_ids = self.all_configuration_ids()
            target_ids: dict[str, str] = {}
            for entity in source_entities:
                target_id = generate_configuration_id()
                while target_id in existing_ids:
                    target_id = generate_configuration_id()
                existing_ids.add(target_id)
                target_ids[entity.id] = target_id

            target_entities: list[ConfigurationEntity] = []
            for entity in source_entities:
                payload = rewrite_configuration_references(
                    entity,
                    target_ids,
                    preserve_unmapped=True,
                )
                target_id = target_ids[entity.id]
                payload["id"] = target_id
                if entity.kind == "workflow":
                    payload["enabled"] = False
                if entity.kind == "component":
                    if entity.component_type in PACKAGE_COMPONENT_SPECS:
                        payload["python_package"]["folder"] = entity.name
                    if entity.component_type == "skill":
                        payload["skill_package"]["folder"] = entity.name
                target_entities.append(
                    ConfigurationEntity(
                        id=target_id,
                        kind=entity.kind,
                        name=entity.name,
                        payload=payload,
                        component_type=entity.component_type,
                    )
                )
            target_config = self._snapshot_from_entities(target_entities)
            validate_configuration_snapshot(
                target_config,
                config_version=CONFIG_VERSION,
            )

            target_id = generate_configuration_id()
            repository_ids = {item.id for item in repositories}
            while target_id in repository_ids:
                target_id = generate_configuration_id()
            repositories_root = configuration_repositories_root(self.data_root)
            final_root = repositories_root / normalized_name
            staging_root = repositories_root / f".repository_copy_{target_id}"
            staging = ConfigurationRepositoryDescriptor(
                id=target_id,
                name=normalized_name,
                root=staging_root,
            )
            try:
                staging_root.mkdir(parents=True, exist_ok=False)
                write_text_atomic(
                    staging_root / "repository.json",
                    json.dumps(
                        {
                            "id": target_id,
                            "name": normalized_name,
                            "schema_version": REPOSITORY_SCHEMA_VERSION,
                        },
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                )
                staged_repository = FileConfigRepository(
                    self.data_root,
                    _config=_default_config(),
                    _system=self._system,
                    _persist=True,
                    _repository=staging,
                    mutations=self._mutations,
                    environment=self._environment,
                )
                staged_repository.update_config(
                    lambda candidate: (
                        candidate.clear(),
                        candidate.update(deepcopy(target_config)),
                    ),
                    expected_repository_id=target_id,
                )
                staging.imports_root.mkdir(parents=True, exist_ok=True)
                self._copy_repository_assets(
                    source,
                    staging,
                    source_entities,
                    target_ids,
                )
                os.replace(staging_root, final_root)
            except BaseException:
                shutil.rmtree(staging_root, ignore_errors=True)
                shutil.rmtree(final_root, ignore_errors=True)
                raise
            descriptor = ConfigurationRepositoryDescriptor(
                id=target_id,
                name=normalized_name,
                root=final_root,
            )
            return descriptor.as_dict(active=False), target_ids

    def delete_repository(self, repository_id: str) -> dict[str, object]:
        with self._mutations.mutation(), self._lock:
            if repository_id == self.repository_id:
                raise ActiveRepositoryDeleteError(
                    "the active configuration repository cannot be deleted"
                )
            descriptor = self._repository_descriptor(repository_id)
            tombstone = descriptor.root.parent / f".repository_delete_{descriptor.id}"
            if tombstone.exists():
                raise ValueError(
                    "configuration repository deletion staging already exists"
                )
            os.replace(descriptor.root, tombstone)
            shutil.rmtree(tombstone, ignore_errors=True)
            return descriptor.as_dict(active=False)

    def export_repository(
        self, repository_id: str
    ) -> tuple[bytes, str]:
        with self._mutations.mutation(), self._lock:
            descriptor = self._repository_descriptor(repository_id)
            files: dict[str, bytes] = {
                "repository/repository.json": (
                    descriptor.root / "repository.json"
                ).read_bytes(),
            }
            for directory_name in (
                "components",
                "agents",
                "workflows",
                PYTHON_PACKAGES_DIRECTORY,
                SKILL_PACKAGES_DIRECTORY,
            ):
                directory = descriptor.root / directory_name
                if not directory.exists():
                    continue
                files.update(
                    {
                        f"repository/{directory_name}/{path}": body
                        for path, body in snapshot_directory(directory).items()
                    }
                )
            manifest = {
                "format": "agent-shell.configuration-repository",
                "format_version": 1,
                "repository": {
                    "id": descriptor.id,
                    "name": descriptor.name,
                    "schema_version": REPOSITORY_SCHEMA_VERSION,
                },
            }
            files["manifest.json"] = canonical_json_bytes(manifest)
            output = BytesIO()
            with ZipFile(
                output,
                "w",
                compression=ZIP_DEFLATED,
                allowZip64=True,
            ) as archive:
                for path, body in sorted(files.items()):
                    info = ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = ZIP_DEFLATED
                    archive.writestr(info, body)
            safe_name = "".join(
                character
                if character.isascii()
                and (character.isalnum() or character in {"-", "_", "."})
                else "-"
                for character in descriptor.name.strip()
            ).strip("-.") or "configuration-repository"
            return (
                output.getvalue(),
                f"{safe_name}.agent-shell-repository.zip",
            )

    @staticmethod
    def _configuration_ids(config: dict[str, Any]) -> set[str]:
        ids = {
            str(item.get("id"))
            for records in config.get("components", {}).values()
            if isinstance(records, list)
            for item in records
            if isinstance(item, dict) and item.get("id")
        }
        for key in ("main_agents", "subagents", "workflows"):
            ids.update(
                str(item.get("id"))
                for item in config.get(key, [])
                if isinstance(item, dict) and item.get("id")
            )
        return ids

    def all_configuration_ids(self) -> set[str]:
        with self._lock:
            result: set[str] = set()
            for descriptor in list_configuration_repositories(self.data_root):
                snapshot = self._load_config_from(descriptor.root)
                current = self._configuration_ids(snapshot)
                if result.intersection(current):
                    raise ValueError(
                        "configuration ids must be globally unique across repositories"
                    )
                result.update(current)
            return result

    def new_configuration_id(self) -> str:
        with self._lock:
            existing = self.all_configuration_ids()
            value = generate_configuration_id()
            while value in existing:
                value = generate_configuration_id()
            return value

    def switch_repository(self, repository_id: str) -> dict[str, object]:
        with self._mutations.mutation(), self._lock:
            descriptor = find_configuration_repository(
                self.data_root,
                repository_id,
            )
            candidate = self._load_config_from(descriptor.root)
            self._normalize_config(candidate)
            validate_configuration_snapshot(candidate, config_version=CONFIG_VERSION)
            target_ids = self._configuration_ids(candidate)
            for other in list_configuration_repositories(self.data_root):
                if other.id == descriptor.id:
                    continue
                if target_ids.intersection(
                    self._configuration_ids(self._load_config_from(other.root))
                ):
                    raise ValueError(
                        "configuration ids must be globally unique across repositories"
                    )
            write_active_configuration_repository(self.data_root, descriptor.id)
            self._active_repository = descriptor
            self._config = candidate
            self._revision += 1
            return descriptor.as_dict(active=True)

    def config(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._config)

    @staticmethod
    def _project_record(
        record: dict[str, Any],
        fields: tuple[str, ...] | None,
    ) -> dict[str, Any]:
        if fields is None:
            return deepcopy(record)
        return {
            field: deepcopy(record[field])
            for field in fields
            if field in record
        }

    def _record_section(self, section: str) -> list[dict[str, Any]]:
        if section not in self._RECORD_SECTIONS:
            raise ValueError(f"unsupported configuration section: {section}")
        records = self._config.get(section, [])
        if not isinstance(records, list):
            raise ValueError(f"configuration section must be a list: {section}")
        return records

    def list_records(
        self,
        section: str,
        *,
        fields: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Copy one record section, optionally projecting top-level fields."""

        with self._lock:
            return [
                self._project_record(record, fields)
                for record in self._record_section(section)
                if isinstance(record, dict)
            ]

    def get_record(
        self,
        section: str,
        record_id: str,
        *,
        fields: tuple[str, ...] | None = None,
    ) -> dict[str, Any] | None:
        """Copy one record without materializing unrelated configuration."""

        with self._lock:
            for record in self._record_section(section):
                if isinstance(record, dict) and record.get("id") == record_id:
                    return self._project_record(record, fields)
        return None

    def find_record(
        self,
        section: str,
        field: str,
        value: object,
        *,
        fields: tuple[str, ...] | None = None,
    ) -> dict[str, Any] | None:
        """Copy the first record matching one top-level field."""

        with self._lock:
            for record in self._record_section(section):
                if isinstance(record, dict) and record.get(field) == value:
                    return self._project_record(record, fields)
        return None

    def _component_records(self, component_type: str) -> list[dict[str, Any]]:
        components = self._config.get("components", {})
        if not isinstance(components, dict):
            raise ValueError("configuration components must be a mapping")
        records = components.get(component_type, [])
        if not isinstance(records, list):
            raise ValueError(
                f"component configuration section must be a list: {component_type}"
            )
        return records

    def list_component_records(
        self,
        component_type: str,
        *,
        fields: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Copy one Component type, optionally projecting top-level fields."""

        with self._lock:
            return [
                self._project_record(record, fields)
                for record in self._component_records(component_type)
                if isinstance(record, dict)
            ]

    def get_component_record(
        self,
        component_type: str,
        record_id: str,
        *,
        fields: tuple[str, ...] | None = None,
    ) -> dict[str, Any] | None:
        """Copy one Component record without materializing its collection."""

        with self._lock:
            for record in self._component_records(component_type):
                if isinstance(record, dict) and record.get("id") == record_id:
                    return self._project_record(record, fields)
        return None

    def list_component_headers(self) -> list[dict[str, str]]:
        with self._lock:
            components = self._config.get("components", {})
            if not isinstance(components, dict):
                raise ValueError("configuration components must be a mapping")
            return [
                {
                    "id": str(record.get("id", "")),
                    "block_type": str(component_type),
                    "name": str(record.get("name", "")),
                }
                for component_type, records in components.items()
                if isinstance(records, list)
                for record in records
                if isinstance(record, dict)
            ]

    def get_component_header(self, record_id: str) -> dict[str, str] | None:
        with self._lock:
            components = self._config.get("components", {})
            if not isinstance(components, dict):
                raise ValueError("configuration components must be a mapping")
            for component_type, records in components.items():
                if not isinstance(records, list):
                    continue
                for record in records:
                    if isinstance(record, dict) and record.get("id") == record_id:
                        return {
                            "id": str(record.get("id", "")),
                            "block_type": str(component_type),
                            "name": str(record.get("name", "")),
                        }
        return None

    def configuration_entity_type(self, record_id: str) -> str | None:
        """Return the concrete Repository entity type for one UUID."""

        with self._lock:
            for entity in iter_configuration_entities(self._config):
                if entity.id == record_id:
                    return entity.component_type or entity.kind
        return None

    def repository_context(self) -> tuple[str, int]:
        with self._lock:
            return self.repository_id, self._revision

    def system(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._system)

    @contextmanager
    def exclusive_config_mutation(
        self,
        *,
        expected_repository_id: str | None = None,
    ) -> Iterator[None]:
        """Serialize one configuration mutation that also owns external assets."""

        with self._mutations.mutation(), self._lock:
            if (
                expected_repository_id is not None
                and self.repository_id != expected_repository_id
            ):
                raise ActiveRepositoryChangedError(
                    "active configuration repository changed during mutation"
                )
            yield

    @contextmanager
    def request_snapshot_context(
        self,
    ) -> Iterator[tuple["FileConfigRepository", Path, Path, str]]:
        """Capture config and both private asset roots from one active repository."""

        with self._lock:
            yield (
                self.clone(),
                self.python_packages_root,
                self.skill_packages_root,
                self.repository_id,
            )

    def update_config(
        self,
        mutator: Callable[[dict[str, Any]], Any],
        *,
        expected_repository_id: str | None = None,
    ) -> Any:
        with self._mutations.mutation(), self._lock:
            if (
                expected_repository_id is not None
                and self.repository_id != expected_repository_id
            ):
                raise ActiveRepositoryChangedError(
                    "active configuration repository changed during mutation"
                )
            candidate = deepcopy(self._config)
            result = mutator(candidate)
            self._normalize_config(candidate)
            validate_configuration_snapshot(
                candidate,
                config_version=CONFIG_VERSION,
            )
            try:
                self._flush_config(candidate)
            except BaseException:
                try:
                    self._flush_config(self._config)
                except BaseException:
                    pass
                raise
            self._config = candidate
            self._revision += 1
            return result

    def update_system(self, mutator: Callable[[dict[str, Any]], Any]) -> Any:
        with self._mutations.mutation(), self._lock:
            candidate = deepcopy(self._system)
            result = mutator(candidate)
            self._normalize_system(candidate)
            if self._persist:
                write_text_atomic(self.system_path, _dump_yaml(candidate))
            self._system = candidate
            return result

    def secret(self, name: str) -> str | None:
        return self._environment.get(name)

    def set_secret(self, name: str, value: str | None) -> None:
        owner = environment_owner_for_name(name)
        if owner is None:
            raise ValueError("environment key does not have a registered owner")
        if value is None:
            self._environment.patch(owner, remove_keys={name})
        else:
            self._environment.patch(owner, set_values={name: value})

    def _flush_config(self, config: dict[str, Any]) -> None:
        if not self._persist:
            return
        self.components_root.mkdir(parents=True, exist_ok=True)
        expected: set[Path] = set()
        for block_type, records in config.get("components", {}).items():
            directory = self.components_root / str(block_type)
            directory.mkdir(parents=True, exist_ok=True)
            for record in records:
                if not isinstance(record, dict) or not record.get("id"):
                    continue
                document = {"kind": "component", "type": block_type, "schema_version": CONFIG_VERSION, "id": record["id"], "name": record.get("name", ""), "payload": self._serialize_record(record, block_type)}
                path = directory / f"{record['id']}.yaml"
                expected.add(path)
                write_text_atomic(path, _dump_yaml(document))
        self._write_agents(config, expected)
        self._write_workflows(config, expected)
        for directory in (
            self.components_root,
            self.agents_root,
            self.workflows_root,
        ):
            if not directory.exists():
                continue
            for path in directory.rglob("*.yaml"):
                if path not in expected:
                    path.unlink(missing_ok=True)

    def _write_agents(self, config: dict[str, Any], expected: set[Path]) -> None:
        for category, key, identity, kind in (("main", "main_agents", "name", "main_agent"), ("subagent", "subagents", "component_name", "subagent")):
            directory = self.agents_root / category
            directory.mkdir(parents=True, exist_ok=True)
            for record in config.get(key, []):
                if not isinstance(record, dict) or not record.get("id"):
                    continue
                path = directory / f"{record['id']}.yaml"
                expected.add(path)
                payload = {k: deepcopy(v) for k, v in record.items() if k not in {"id", identity}}
                write_text_atomic(path, _dump_yaml({"kind": kind, "schema_version": CONFIG_VERSION, "id": record["id"], identity: record.get(identity, ""), "payload": payload}))

    def _write_workflows(
        self, config: dict[str, Any], expected: set[Path]
    ) -> None:
        self.workflows_root.mkdir(parents=True, exist_ok=True)
        for record in config.get("workflows", []):
            if not isinstance(record, dict) or not record.get("id"):
                continue
            path = self.workflows_root / f"{record['id']}.yaml"
            expected.add(path)
            payload = {k: deepcopy(v) for k, v in record.items() if k != "id"}
            write_text_atomic(path, _dump_yaml({"kind": "workflow", "schema_version": CONFIG_VERSION, "id": record["id"], "payload": payload}))

    @staticmethod
    def _serialize_record(record: dict, block_type: str) -> dict:
        payload = {k: deepcopy(v) for k, v in record.items() if k not in {"id", "name"}}
        return payload
