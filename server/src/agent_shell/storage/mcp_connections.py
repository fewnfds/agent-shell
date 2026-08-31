from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
import threading
from typing import Annotated, Any, Literal
from urllib.parse import urlparse
from uuid import UUID, uuid5

from packaging.version import InvalidVersion, Version
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)
import yaml

from agent_shell.configuration.identity import (
    ConfigurationName,
    name_collision_key,
    new_configuration_id,
    require_configuration_id,
)
from agent_shell.mcp.installation import McpInstallationManager
from agent_shell.storage.atomic_files import write_text_atomic
from agent_shell.storage.configuration_mutations import ConfigurationMutationCoordinator
from agent_shell.storage.environment import (
    EnvironmentSnapshot,
    InstanceEnvironmentStore,
    MCP_CONNECTION_ENVIRONMENT_OWNER,
)
from agent_shell.storage.file_config import _dump_yaml


_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_NPM_PACKAGE = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")
_NPM_VERSION = re.compile(
    r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?(?:\+[0-9A-Za-z][0-9A-Za-z.-]*)?$"
)
_PYPI_PACKAGE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_ENTRYPOINT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

McpStringValue = Annotated[str, StringConstraints(strip_whitespace=False)]


class McpConfiguredValue(BaseModel):
    """One user-owned connection value, either visible or secret-backed."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["literal", "secret"] = "secret"
    value: McpStringValue | None = None
    status: Literal["masked", "missing"] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "McpConfiguredValue":
        if self.source == "literal":
            if self.value is None:
                raise ValueError("literal MCP connection values require value")
            if self.status is not None:
                raise ValueError("literal MCP connection values do not have status")
        elif self.value is not None and self.status is not None:
            raise ValueError("secret MCP connection values cannot set value and status")
        return self


class _McpConnectionBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: ConfigurationName


class McpStdioConnection(_McpConnectionBase):
    transport: Literal["stdio"]
    package_source: Literal["npm", "pypi"]
    package: Annotated[str, Field(min_length=1)]
    version: Annotated[str, Field(min_length=1)]
    entrypoint: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, McpConfiguredValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def package_declaration(self) -> "McpStdioConnection":
        if self.package_source == "npm":
            if _NPM_PACKAGE.fullmatch(self.package) is None:
                raise ValueError("MCP npm package name is invalid")
            if _NPM_VERSION.fullmatch(self.version) is None:
                raise ValueError("MCP npm package version must be exact")
        else:
            if _PYPI_PACKAGE.fullmatch(self.package) is None:
                raise ValueError("MCP PyPI package name is invalid")
            try:
                Version(self.version)
            except InvalidVersion as exc:
                raise ValueError("MCP PyPI package version must be exact") from exc
        if self.entrypoint is not None and _ENTRYPOINT.fullmatch(self.entrypoint) is None:
            raise ValueError("MCP package entrypoint is invalid")
        return self

    @field_validator("cwd")
    @classmethod
    def absolute_cwd(cls, value: str | None) -> str | None:
        if value is not None and not Path(value).is_absolute():
            raise ValueError("MCP stdio cwd must be an absolute path")
        return value

    @field_validator("env")
    @classmethod
    def environment_names(
        cls,
        values: dict[str, McpConfiguredValue],
    ) -> dict[str, McpConfiguredValue]:
        invalid = sorted(name for name in values if _ENVIRONMENT_NAME.fullmatch(name) is None)
        if invalid:
            raise ValueError("MCP stdio environment names are invalid: " + ", ".join(invalid))
        return values


class McpHttpConnection(_McpConnectionBase):
    transport: Literal["http"]
    url: Annotated[str, Field(min_length=1)]
    headers: dict[str, McpConfiguredValue] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("MCP URL must be an HTTP(S) URL without credentials or fragment")
        return value

    @field_validator("headers")
    @classmethod
    def header_names(
        cls,
        values: dict[str, McpConfiguredValue],
    ) -> dict[str, McpConfiguredValue]:
        invalid = sorted(name for name in values if _HEADER_NAME.fullmatch(name) is None)
        if invalid:
            raise ValueError("MCP HTTP header names are invalid: " + ", ".join(invalid))
        return values


McpConnection = Annotated[
    McpStdioConnection | McpHttpConnection,
    Field(discriminator="transport"),
]
MCP_CONNECTION_ADAPTER = TypeAdapter(McpConnection)


class McpConnectionNameConflictError(ValueError):
    """The requested MCP Connection name is already in use."""


class McpSecretReferenceMissingError(ValueError):
    """A configured MCP secret slot has no value in the environment store."""


def _value_map_field(record: dict[str, Any]) -> str:
    return "env" if record.get("transport") == "stdio" else "headers"


def _secret_reference(connection_id: str, channel: str, target_name: str) -> str:
    slot = uuid5(UUID(connection_id), f"{channel}:{target_name}")
    return (
        f"AGENT_SHELL_MCP_{connection_id.replace('-', '').upper()}_"
        f"{slot.hex.upper()}"
    )


def _public_record(
    record: dict[str, Any],
    environment: EnvironmentSnapshot,
    installations: McpInstallationManager,
) -> dict[str, Any]:
    result = deepcopy(record)
    field = _value_map_field(record)
    projected: dict[str, dict[str, str]] = {}
    for name, configured in dict(record.get(field, {})).items():
        if configured.get("source") == "literal":
            projected[name] = {
                "source": "literal",
                "value": str(configured.get("value", "")),
            }
            continue
        reference = configured.get("reference")
        projected[name] = {
            "source": "secret",
            "status": (
                "masked"
                if isinstance(reference, str) and environment.get(reference) is not None
                else "missing"
            ),
        }
    result[field] = projected
    installation = installations.status(str(record["id"]), record)
    if installation is not None:
        result["installation"] = installation
    return result


def _resolved_value_map(
    record: dict[str, Any],
    environment: EnvironmentSnapshot,
) -> dict[str, str]:
    field = _value_map_field(record)
    resolved: dict[str, str] = {}
    for name, configured in dict(record.get(field, {})).items():
        if configured.get("source") == "literal":
            resolved[name] = str(configured.get("value", ""))
            continue
        reference = configured.get("reference")
        value = environment.get(reference) if isinstance(reference, str) else None
        if value is None:
            raise McpSecretReferenceMissingError(str(reference or name))
        resolved[name] = value
    return resolved


def _copy_input_record(
    record: dict[str, Any],
    environment: EnvironmentSnapshot,
) -> dict[str, Any]:
    value = deepcopy(record)
    field = _value_map_field(record)
    configured_values: dict[str, dict[str, Any]] = {}
    for name, configured in dict(record.get(field, {})).items():
        if configured.get("source") == "literal":
            configured_values[name] = {
                "source": "literal",
                "value": str(configured.get("value", "")),
            }
        else:
            reference = configured.get("reference")
            configured_values[name] = {
                "source": "secret",
                "value": (
                    environment.get(reference)
                    if isinstance(reference, str)
                    else None
                ),
            }
    value[field] = configured_values
    return value


@dataclass(frozen=True, slots=True)
class McpResourceSnapshot:
    """Read-only MCP connections, bindings and secret view for one request."""

    _records: tuple[dict[str, Any], ...]
    _environment: EnvironmentSnapshot
    _bindings: dict[str, dict[str, str]]
    _installations: McpInstallationManager

    @classmethod
    def capture(
        cls,
        records: list[dict[str, Any]],
        environment: EnvironmentSnapshot,
        bindings: dict[str, dict[str, str]],
        installations: McpInstallationManager,
    ) -> "McpResourceSnapshot":
        return cls(
            tuple(deepcopy(records)),
            environment,
            deepcopy(bindings),
            installations,
        )

    def list_connections(self) -> list[dict[str, Any]]:
        return sorted(
            (
                _public_record(item, self._environment, self._installations)
                for item in self._records
            ),
            key=lambda item: (str(item.get("name", "")).casefold(), str(item["id"])),
        )

    def get_connection(self, connection_id: str) -> dict[str, Any] | None:
        return next(
            (
                _public_record(item, self._environment, self._installations)
                for item in self._records
                if item["id"] == connection_id
            ),
            None,
        )

    def resolve_connection(self, connection_id: str) -> dict[str, Any]:
        for item in self._records:
            if item["id"] != connection_id:
                continue
            field = _value_map_field(item)
            resolved = {
                key: deepcopy(value)
                for key, value in item.items()
                if key not in {"id", "name", field}
            }
            values = _resolved_value_map(item, self._environment)
            if values:
                resolved[field] = values
            return self._installations.resolve_connection(str(item["id"]), resolved)
        raise KeyError(connection_id)

    def copy_input(self, connection_id: str) -> dict[str, Any]:
        for item in self._records:
            if item["id"] == connection_id:
                value = _copy_input_record(item, self._environment)
                value.pop("id", None)
                return value
        raise KeyError(connection_id)

    def get_binding(self, repository_id: str, requirement_id: str) -> str | None:
        return self._bindings.get(repository_id, {}).get(requirement_id)

    def bindings_for_repository(self, repository_id: str) -> dict[str, str]:
        return dict(self._bindings.get(repository_id, {}))


class McpResourceStore:
    """Instance MCP Connection, secret slot and Repository binding aggregate."""

    def __init__(
        self,
        data_root: Path,
        *,
        runtime_root: Path | None = None,
        environment: InstanceEnvironmentStore | None = None,
        mutations: ConfigurationMutationCoordinator | None = None,
    ) -> None:
        if environment is not None and mutations is None:
            raise ValueError("an injected environment store requires its coordinator")
        self.data_root = data_root.resolve()
        self.root = self.data_root / "config" / "mcp-connections"
        self.bindings_path = self.data_root / "config" / "mcp-bindings.yaml"
        self._installations = McpInstallationManager(
            self.data_root,
            runtime_root or self.data_root.parent / "runtime",
        )
        self._mutations = mutations or ConfigurationMutationCoordinator()
        self._environment = environment or InstanceEnvironmentStore(
            self.data_root / "config" / "agent-shell.env",
            mutations=self._mutations,
        )
        self._lock = threading.RLock()
        self._revision = 1

    def _documents(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not self.root.exists():
            return records
        for path in sorted(self.root.glob("*.yaml")):
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(document, dict) or set(document) != {
                "kind", "schema_version", "id", "name", "payload"
            }:
                raise ValueError(f"MCP connection document is invalid: {path}")
            if document["kind"] != "mcp-connection" or document["schema_version"] != 1:
                raise ValueError(f"MCP connection document version is invalid: {path}")
            item_id = require_configuration_id(document["id"], label=f"MCP connection id in {path}")
            if path.stem != item_id or not isinstance(document["payload"], dict):
                raise ValueError(f"MCP connection document identity is invalid: {path}")
            record = {"id": item_id, "name": document["name"], **document["payload"]}
            self._validate_stored_record(record)
            records.append(record)
        return records

    @staticmethod
    def _validate_stored_record(record: dict[str, Any]) -> None:
        field = _value_map_field(record)
        public = deepcopy(record)
        converted: dict[str, dict[str, Any]] = {}
        for name, configured in dict(record.get(field, {})).items():
            if not isinstance(configured, dict):
                raise ValueError("MCP connection value slot is invalid")
            if configured.get("source") == "literal" and set(configured) == {"source", "value"}:
                converted[name] = dict(configured)
            elif configured.get("source") == "secret" and set(configured) == {"source", "reference"}:
                converted[name] = {"source": "secret", "status": "missing"}
            else:
                raise ValueError("MCP connection value slot is invalid")
        public[field] = converted
        public.pop("id", None)
        MCP_CONNECTION_ADAPTER.validate_python(public)

    def _load_bindings(self) -> dict[str, dict[str, str]]:
        if not self.bindings_path.exists():
            return {}
        value = yaml.safe_load(self.bindings_path.read_text(encoding="utf-8")) or {}
        if not isinstance(value, dict):
            raise ValueError("MCP bindings must contain a mapping")
        bindings: dict[str, dict[str, str]] = {}
        for repository_id, scope in value.items():
            if not isinstance(repository_id, str) or not isinstance(scope, dict):
                raise ValueError("MCP binding scope is invalid")
            if repository_id:
                require_configuration_id(repository_id, label="MCP binding repository id")
            bindings[repository_id] = {
                require_configuration_id(requirement_id, label="MCP binding requirement id"):
                require_configuration_id(connection_id, label="MCP binding connection id")
                for requirement_id, connection_id in scope.items()
            }
        return bindings

    def _write_bindings(self, value: dict[str, dict[str, str]]) -> None:
        write_text_atomic(self.bindings_path, _dump_yaml(value))

    def _snapshot_unlocked(self) -> McpResourceSnapshot:
        return McpResourceSnapshot.capture(
            self._documents(),
            self._environment.snapshot(),
            self._load_bindings(),
            self._installations,
        )

    def snapshot(self) -> McpResourceSnapshot:
        with self._mutations.mutation(), self._lock:
            return self._snapshot_unlocked()

    def revision(self) -> int:
        with self._lock:
            return self._revision

    def list_connections(self) -> list[dict[str, Any]]:
        return self.snapshot().list_connections()

    def get_connection(self, connection_id: str) -> dict[str, Any] | None:
        return self.snapshot().get_connection(connection_id)

    def resolve_connection(self, connection_id: str) -> dict[str, Any]:
        return self.snapshot().resolve_connection(connection_id)

    def get_binding(self, repository_id: str, requirement_id: str) -> str | None:
        return self.snapshot().get_binding(repository_id, requirement_id)

    def bindings_for_repository(self, repository_id: str) -> dict[str, str]:
        return self.snapshot().bindings_for_repository(repository_id)

    def save_connection(self, connection_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        connection_id = require_configuration_id(connection_id, label="MCP connection id")
        with self._mutations.mutation(), self._lock:
            records = self._documents()
            existing = next((item for item in records if item["id"] == connection_id), None)
            model = MCP_CONNECTION_ADAPTER.validate_python(
                {key: value for key, value in payload.items() if key != "id"}
            )
            candidate = model.model_dump(mode="json", exclude_none=True)
            name = str(candidate["name"])
            for item in records:
                if item["id"] != connection_id and name_collision_key(str(item["name"])) == name_collision_key(name):
                    raise McpConnectionNameConflictError("MCP connection name already exists")

            field = _value_map_field(candidate)
            configured_values = dict(candidate.get(field, {}))
            stored_values: dict[str, dict[str, str]] = {}
            secret_updates: dict[str, str] = {}
            for target_name, configured in configured_values.items():
                source = configured.get("source")
                if source == "literal":
                    stored_values[target_name] = {
                        "source": "literal",
                        "value": str(configured.get("value", "")),
                    }
                    continue
                reference = _secret_reference(connection_id, field, target_name)
                stored_values[target_name] = {"source": "secret", "reference": reference}
                secret_value = configured.get("value")
                if secret_value is not None:
                    secret_updates[reference] = str(secret_value)
            candidate[field] = stored_values
            stored = {"id": connection_id, **candidate}
            final_records = [item for item in records if item["id"] != connection_id] + [stored]
            active_references = {
                str(configured["reference"])
                for item in final_records
                for configured in dict(item.get(_value_map_field(item), {})).values()
                if configured.get("source") == "secret" and isinstance(configured.get("reference"), str)
            }
            original_environment = self._environment.owned_values(MCP_CONNECTION_ENVIRONMENT_OWNER)
            document = {
                "kind": "mcp-connection",
                "schema_version": 1,
                "id": connection_id,
                "name": name,
                "payload": {key: value for key, value in stored.items() if key not in {"id", "name"}},
            }
            document_path = self.root / f"{connection_id}.yaml"
            previous_document = document_path.read_text(encoding="utf-8") if document_path.exists() else None
            try:
                if secret_updates:
                    self._environment.patch(MCP_CONNECTION_ENVIRONMENT_OWNER, set_values=secret_updates)
                write_text_atomic(document_path, _dump_yaml(document))
                stale = set(self._environment.owned_values(MCP_CONNECTION_ENVIRONMENT_OWNER)).difference(active_references)
                if stale:
                    self._environment.patch(MCP_CONNECTION_ENVIRONMENT_OWNER, remove_keys=stale)
            except BaseException:
                try:
                    if previous_document is None:
                        document_path.unlink(missing_ok=True)
                    else:
                        write_text_atomic(document_path, previous_document)
                    self._environment.replace_owned(MCP_CONNECTION_ENVIRONMENT_OWNER, original_environment)
                except BaseException:
                    pass
                raise
            self._revision += 1
            return _public_record(
                stored,
                self._environment.snapshot(),
                self._installations,
            )

    def save_connections_atomic(
        self,
        items: list[tuple[str, dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        with self._mutations.mutation(), self._lock:
            previous_revision = self._revision
            previous_documents = {
                path: path.read_text(encoding="utf-8")
                for path in self.root.glob("*.yaml")
            } if self.root.exists() else {}
            previous_environment = self._environment.owned_values(MCP_CONNECTION_ENVIRONMENT_OWNER)
            try:
                return [self.save_connection(connection_id, payload) for connection_id, payload in items]
            except BaseException:
                try:
                    current_paths = set(self.root.glob("*.yaml")) if self.root.exists() else set()
                    for path in current_paths.difference(previous_documents):
                        path.unlink(missing_ok=True)
                    for path, text in previous_documents.items():
                        write_text_atomic(path, text)
                    self._environment.replace_owned(MCP_CONNECTION_ENVIRONMENT_OWNER, previous_environment)
                    self._revision = previous_revision
                except BaseException:
                    pass
                raise

    def copy_connection(self, source_id: str, name: str) -> dict[str, Any]:
        payload = self.snapshot().copy_input(source_id)
        payload["name"] = name
        return self.save_connection(new_configuration_id(), payload)

    def delete_connection(self, connection_id: str) -> bool:
        connection_id = require_configuration_id(connection_id, label="MCP connection id")
        with self._mutations.mutation(), self._lock:
            records = self._documents()
            target = next((item for item in records if item["id"] == connection_id), None)
            if target is None:
                return False
            original_bindings = self._load_bindings()
            candidate_bindings = deepcopy(original_bindings)
            for repository_id, scope in list(candidate_bindings.items()):
                retained = {requirement_id: bound_id for requirement_id, bound_id in scope.items() if bound_id != connection_id}
                if retained:
                    candidate_bindings[repository_id] = retained
                else:
                    candidate_bindings.pop(repository_id, None)
            original_environment = self._environment.owned_values(MCP_CONNECTION_ENVIRONMENT_OWNER)
            references = {
                str(configured["reference"])
                for configured in dict(target.get(_value_map_field(target), {})).values()
                if configured.get("source") == "secret" and isinstance(configured.get("reference"), str)
            }
            document_path = self.root / f"{connection_id}.yaml"
            previous_document = document_path.read_text(encoding="utf-8")
            bindings_existed = self.bindings_path.exists()
            try:
                if candidate_bindings != original_bindings:
                    self._write_bindings(candidate_bindings)
                document_path.unlink()
                if references:
                    self._environment.patch(MCP_CONNECTION_ENVIRONMENT_OWNER, remove_keys=references)
            except BaseException:
                try:
                    write_text_atomic(document_path, previous_document)
                    if bindings_existed:
                        self._write_bindings(original_bindings)
                    else:
                        self.bindings_path.unlink(missing_ok=True)
                    self._environment.replace_owned(MCP_CONNECTION_ENVIRONMENT_OWNER, original_environment)
                except BaseException:
                    pass
                raise
            self._revision += 1
            self._installations.remove(connection_id)
            return True

    def install_connection(self, connection_id: str) -> dict[str, Any]:
        connection_id = require_configuration_id(connection_id, label="MCP connection id")
        with self._lock:
            declared = self._snapshot_unlocked().copy_input(connection_id)
            return self._installations.install(connection_id, declared)

    def set_binding(self, repository_id: str, requirement_id: str, connection_id: str | None) -> None:
        if repository_id:
            repository_id = require_configuration_id(repository_id, label="MCP binding repository id")
        requirement_id = require_configuration_id(requirement_id, label="MCP binding requirement id")
        if connection_id is not None:
            connection_id = require_configuration_id(connection_id, label="MCP binding connection id")
        with self._mutations.mutation(), self._lock:
            if connection_id is not None and not any(item["id"] == connection_id for item in self._documents()):
                raise KeyError(connection_id)
            bindings = self._load_bindings()
            scope = bindings.setdefault(repository_id, {})
            if connection_id is None:
                scope.pop(requirement_id, None)
            else:
                scope[requirement_id] = connection_id
            if not scope:
                bindings.pop(repository_id, None)
            self._write_bindings(bindings)
            self._revision += 1

    def copy_repository_bindings(self, source_repository_id: str, target_repository_id: str, target_ids: dict[str, str]) -> None:
        source_repository_id = require_configuration_id(source_repository_id, label="source MCP binding repository id")
        target_repository_id = require_configuration_id(target_repository_id, label="target MCP binding repository id")
        with self._mutations.mutation(), self._lock:
            bindings = self._load_bindings()
            copied = {
                target_ids[requirement_id]: connection_id
                for requirement_id, connection_id in bindings.get(source_repository_id, {}).items()
                if requirement_id in target_ids
            }
            if copied:
                bindings[target_repository_id] = copied
            else:
                bindings.pop(target_repository_id, None)
            self._write_bindings(bindings)
            self._revision += 1

    def remove_repository_bindings(self, repository_id: str) -> dict[str, str]:
        repository_id = require_configuration_id(repository_id, label="MCP binding repository id")
        with self._mutations.mutation(), self._lock:
            bindings = self._load_bindings()
            removed = bindings.pop(repository_id, {})
            if removed:
                self._write_bindings(bindings)
                self._revision += 1
            return removed

    def restore_repository_bindings(self, repository_id: str, bindings: dict[str, str]) -> None:
        repository_id = require_configuration_id(repository_id, label="MCP binding repository id")
        with self._mutations.mutation(), self._lock:
            value = self._load_bindings()
            if bindings:
                value[repository_id] = dict(bindings)
            else:
                value.pop(repository_id, None)
            self._write_bindings(value)
            self._revision += 1


__all__ = [
    "MCP_CONNECTION_ADAPTER",
    "McpConfiguredValue",
    "McpConnection",
    "McpConnectionNameConflictError",
    "McpHttpConnection",
    "McpResourceSnapshot",
    "McpResourceStore",
    "McpSecretReferenceMissingError",
    "McpStdioConnection",
]
