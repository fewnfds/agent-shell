from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any

from pydantic import TypeAdapter
import yaml

from agent_shell.configuration.identity import name_collision_key
from agent_shell.configuration.identity import new_configuration_id
from agent_shell.configuration.identity import require_configuration_id
from agent_shell.contracts import BlockName, ModelConnectionBlock
from agent_shell.storage.atomic_files import write_text_atomic
from agent_shell.storage.configuration_mutations import ConfigurationMutationCoordinator
from agent_shell.storage.environment import (
    EnvironmentSnapshot,
    InstanceEnvironmentStore,
    MODEL_CONNECTION_ENVIRONMENT_OWNER,
)
from agent_shell.storage.file_config import _dump_yaml


class ModelConnectionNameConflictError(ValueError):
    """The requested instance model connection name is already in use."""


class ModelCredentialReferenceMissingError(ValueError):
    """A stored credential reference has no corresponding environment value."""


def _credential_reference(record: dict[str, Any]) -> str | None:
    credential = record.get("credential")
    if not isinstance(credential, dict) or set(credential) != {"reference"}:
        return None
    reference = credential.get("reference")
    return reference if isinstance(reference, str) else None


def _public_record(
    record: dict[str, Any],
    environment: EnvironmentSnapshot,
) -> dict[str, Any]:
    value = deepcopy(record)
    reference = _credential_reference(record)
    value["credential"] = {
        "status": (
            "masked"
            if reference and environment.get(reference) is not None
            else "missing"
        )
    }
    return value


@dataclass(frozen=True, slots=True)
class ModelResourceSnapshot:
    """Read-only connection and binding values captured for one request."""

    _records: tuple[dict[str, Any], ...]
    _environment: EnvironmentSnapshot
    _bindings: dict[str, dict[str, str]]

    @classmethod
    def capture(
        cls,
        records: list[dict[str, Any]],
        environment: EnvironmentSnapshot,
        bindings: dict[str, dict[str, str]],
    ) -> "ModelResourceSnapshot":
        return cls(
            tuple(deepcopy(records)),
            environment,
            deepcopy(bindings),
        )

    def list_connections(self) -> list[dict[str, Any]]:
        return sorted(
            (_public_record(item, self._environment) for item in self._records),
            key=lambda item: (
                str(item.get("name", "")).casefold(),
                str(item["id"]),
            ),
        )

    def get_connection(self, connection_id: str) -> dict[str, Any] | None:
        return next(
            (
                _public_record(item, self._environment)
                for item in self._records
                if item["id"] == connection_id
            ),
            None,
        )

    def resolve_connection(self, connection_id: str) -> dict[str, Any]:
        for item in self._records:
            if item["id"] != connection_id:
                continue
            resolved = deepcopy(item)
            reference = _credential_reference(item)
            if reference is not None and self._environment.get(reference) is None:
                raise ModelCredentialReferenceMissingError(reference)
            resolved["credential"] = (
                self._environment.get(reference) if reference is not None else None
            )
            resolved.pop("id", None)
            return ModelConnectionBlock.model_validate(resolved).model_dump(
                mode="json"
            )
        raise KeyError(connection_id)

    def get_binding(self, repository_id: str, requirement_id: str) -> str | None:
        scope = self._bindings.get(repository_id, {})
        return scope.get(requirement_id)

    def bindings_for_repository(self, repository_id: str) -> dict[str, str]:
        return dict(self._bindings.get(repository_id, {}))


class ModelResourceStore:
    """Instance Model Connection, credential, and mapping aggregate."""

    def __init__(
        self,
        data_root: Path,
        *,
        environment: InstanceEnvironmentStore | None = None,
        mutations: ConfigurationMutationCoordinator | None = None,
    ) -> None:
        if environment is not None and mutations is None:
            raise ValueError("an injected environment store requires its coordinator")
        self.data_root = data_root.resolve()
        self.root = self.data_root / "config" / "model-connections"
        self.bindings_path = self.data_root / "config" / "model-bindings.yaml"
        self._mutations = mutations or ConfigurationMutationCoordinator()
        self._environment = environment or InstanceEnvironmentStore(
            self.data_root / "config" / "agent-shell.env",
            mutations=self._mutations,
        )
        self._lock = threading.RLock()
        self._revision = 1

    @staticmethod
    def _secret_name(connection_id: str) -> str:
        return (
            "AGENT_SHELL_MODEL_"
            f"{connection_id.replace('-', '').upper()}_API_KEY"
        )

    def _documents(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not self.root.exists():
            return records
        for path in sorted(self.root.glob("*.yaml")):
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(document, dict) or set(document) != {
                "kind",
                "schema_version",
                "id",
                "name",
                "payload",
            }:
                raise ValueError(f"model connection document is invalid: {path}")
            if (
                document["kind"] != "model-connection"
                or document["schema_version"] != 1
            ):
                raise ValueError(
                    f"model connection document version is invalid: {path}"
                )
            item_id = require_configuration_id(
                document["id"],
                label=f"model connection id in {path}",
            )
            if path.stem != item_id or not isinstance(document["payload"], dict):
                raise ValueError(
                    f"model connection document identity is invalid: {path}"
                )
            records.append(
                {
                    "id": item_id,
                    "name": document["name"],
                    **document["payload"],
                }
            )
        return records

    def _load_bindings(self) -> dict[str, dict[str, str]]:
        if not self.bindings_path.exists():
            return {}
        value = yaml.safe_load(
            self.bindings_path.read_text(encoding="utf-8")
        ) or {}
        if not isinstance(value, dict):
            raise ValueError("model bindings must contain a mapping")
        bindings: dict[str, dict[str, str]] = {}
        for repository_id, scope in value.items():
            if not isinstance(repository_id, str) or not isinstance(scope, dict):
                raise ValueError("model binding scope is invalid")
            if repository_id:
                require_configuration_id(
                    repository_id,
                    label="model binding repository id",
                )
            normalized: dict[str, str] = {}
            for requirement_id, connection_id in scope.items():
                normalized[
                    require_configuration_id(
                        requirement_id,
                        label="model binding requirement id",
                    )
                ] = require_configuration_id(
                    connection_id,
                    label="model binding connection id",
                )
            bindings[repository_id] = normalized
        return bindings

    def _write_bindings(self, value: dict[str, dict[str, str]]) -> None:
        write_text_atomic(self.bindings_path, _dump_yaml(value))

    def _snapshot_unlocked(self) -> ModelResourceSnapshot:
        return ModelResourceSnapshot.capture(
            self._documents(),
            self._environment.snapshot(),
            self._load_bindings(),
        )

    def snapshot(self) -> ModelResourceSnapshot:
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

    def save_connection(
        self,
        connection_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        connection_id = require_configuration_id(
            connection_id,
            label="model connection id",
        )
        with self._mutations.mutation(), self._lock:
            records = self._documents()
            existing = next(
                (item for item in records if item["id"] == connection_id),
                None,
            )
            raw_name = payload.get("name")
            if not isinstance(raw_name, str):
                raise ValueError("model connection name must be a string")
            name = TypeAdapter(BlockName).validate_python(raw_name.strip())
            for item in records:
                if (
                    item["id"] != connection_id
                    and name_collision_key(str(item["name"]))
                    == name_collision_key(name)
                ):
                    raise ModelConnectionNameConflictError(
                        "model connection name already exists"
                    )

            candidate = ModelConnectionBlock.model_validate(
                {key: value for key, value in payload.items() if key != "id"}
            ).model_dump(mode="json")
            credential_input = candidate.pop("credential", None)
            old_reference = _credential_reference(existing or {})
            reuse = bool(
                existing
                and existing.get("provider") == candidate.get("provider")
                and existing.get("base_url") == candidate.get("base_url")
            )
            reference = self._secret_name(connection_id)
            if credential_input is not None:
                stored_credential: dict[str, str] | None = {
                    "reference": reference
                }
            elif reuse and old_reference:
                stored_credential = {"reference": old_reference}
            else:
                stored_credential = None
            candidate["credential"] = stored_credential
            stored = {"id": connection_id, "name": name, **candidate}

            final_records = [
                item for item in records if item["id"] != connection_id
            ] + [stored]
            active_references = {
                item_reference
                for item in final_records
                if (item_reference := _credential_reference(item)) is not None
            }
            original_environment = self._environment.owned_values(
                MODEL_CONNECTION_ENVIRONMENT_OWNER
            )
            document = {
                "kind": "model-connection",
                "schema_version": 1,
                "id": connection_id,
                "name": name,
                "payload": {
                    key: value
                    for key, value in stored.items()
                    if key not in {"id", "name"}
                },
            }
            document_path = self.root / f"{connection_id}.yaml"
            previous_document = (
                document_path.read_text(encoding="utf-8")
                if document_path.exists()
                else None
            )
            try:
                if credential_input is not None:
                    self._environment.patch(
                        MODEL_CONNECTION_ENVIRONMENT_OWNER,
                        set_values={reference: str(credential_input)},
                    )
                write_text_atomic(document_path, _dump_yaml(document))
                stale_references = set(
                    self._environment.owned_values(
                        MODEL_CONNECTION_ENVIRONMENT_OWNER
                    )
                ).difference(active_references)
                if stale_references:
                    self._environment.patch(
                        MODEL_CONNECTION_ENVIRONMENT_OWNER,
                        remove_keys=stale_references,
                    )
            except BaseException:
                try:
                    if previous_document is None:
                        document_path.unlink(missing_ok=True)
                    else:
                        write_text_atomic(document_path, previous_document)
                    self._environment.replace_owned(
                        MODEL_CONNECTION_ENVIRONMENT_OWNER,
                        original_environment,
                    )
                except BaseException:
                    pass
                raise
            self._revision += 1
            return _public_record(stored, self._environment.snapshot())

    def copy_connection(self, source_id: str, name: str) -> dict[str, Any]:
        source = self.resolve_connection(source_id)
        source["name"] = name
        return self.save_connection(new_configuration_id(), source)

    def delete_connection(self, connection_id: str) -> bool:
        connection_id = require_configuration_id(
            connection_id,
            label="model connection id",
        )
        with self._mutations.mutation(), self._lock:
            records = self._documents()
            target = next(
                (item for item in records if item["id"] == connection_id),
                None,
            )
            if target is None:
                return False
            original_bindings = self._load_bindings()
            candidate_bindings = deepcopy(original_bindings)
            for repository_id, scope in list(candidate_bindings.items()):
                retained = {
                    requirement_id: bound_id
                    for requirement_id, bound_id in scope.items()
                    if bound_id != connection_id
                }
                if retained:
                    candidate_bindings[repository_id] = retained
                else:
                    candidate_bindings.pop(repository_id, None)

            original_environment = self._environment.owned_values(
                MODEL_CONNECTION_ENVIRONMENT_OWNER
            )
            reference = _credential_reference(target)
            document_path = self.root / f"{connection_id}.yaml"
            previous_document = document_path.read_text(encoding="utf-8")
            bindings_existed = self.bindings_path.exists()
            try:
                if candidate_bindings != original_bindings:
                    self._write_bindings(candidate_bindings)
                document_path.unlink()
                if reference is not None:
                    self._environment.patch(
                        MODEL_CONNECTION_ENVIRONMENT_OWNER,
                        remove_keys={reference},
                    )
            except BaseException:
                try:
                    write_text_atomic(document_path, previous_document)
                    if bindings_existed:
                        self._write_bindings(original_bindings)
                    else:
                        self.bindings_path.unlink(missing_ok=True)
                    self._environment.replace_owned(
                        MODEL_CONNECTION_ENVIRONMENT_OWNER,
                        original_environment,
                    )
                except BaseException:
                    pass
                raise
            self._revision += 1
            return True

    def set_binding(
        self,
        repository_id: str,
        requirement_id: str,
        connection_id: str | None,
    ) -> None:
        if repository_id:
            repository_id = require_configuration_id(
                repository_id,
                label="model binding repository id",
            )
        requirement_id = require_configuration_id(
            requirement_id,
            label="model binding requirement id",
        )
        if connection_id is not None:
            connection_id = require_configuration_id(
                connection_id,
                label="model binding connection id",
            )
        with self._mutations.mutation(), self._lock:
            if connection_id is not None and not any(
                item["id"] == connection_id for item in self._documents()
            ):
                raise KeyError(connection_id)
            value = self._load_bindings()
            scope = value.setdefault(repository_id, {})
            if connection_id is None:
                scope.pop(requirement_id, None)
            else:
                scope[requirement_id] = connection_id
            if not scope:
                value.pop(repository_id, None)
            self._write_bindings(value)
            self._revision += 1

    def copy_repository_bindings(
        self,
        source_repository_id: str,
        target_repository_id: str,
        target_ids: dict[str, str],
    ) -> None:
        source_repository_id = require_configuration_id(
            source_repository_id,
            label="source model binding repository id",
        )
        target_repository_id = require_configuration_id(
            target_repository_id,
            label="target model binding repository id",
        )
        with self._mutations.mutation(), self._lock:
            value = self._load_bindings()
            source = value.get(source_repository_id, {})
            copied = {
                target_ids[requirement_id]: connection_id
                for requirement_id, connection_id in source.items()
                if requirement_id in target_ids
            }
            if copied:
                value[target_repository_id] = copied
            else:
                value.pop(target_repository_id, None)
            self._write_bindings(value)
            self._revision += 1

    def remove_repository_bindings(
        self,
        repository_id: str,
    ) -> dict[str, str]:
        repository_id = require_configuration_id(
            repository_id,
            label="model binding repository id",
        )
        with self._mutations.mutation(), self._lock:
            value = self._load_bindings()
            removed = value.pop(repository_id, {})
            if removed:
                self._write_bindings(value)
                self._revision += 1
            return removed

    def restore_repository_bindings(
        self,
        repository_id: str,
        bindings: dict[str, str],
    ) -> None:
        repository_id = require_configuration_id(
            repository_id,
            label="model binding repository id",
        )
        with self._mutations.mutation(), self._lock:
            value = self._load_bindings()
            if bindings:
                value[repository_id] = dict(bindings)
            else:
                value.pop(repository_id, None)
            self._write_bindings(value)
            self._revision += 1


__all__ = [
    "ModelConnectionNameConflictError",
    "ModelCredentialReferenceMissingError",
    "ModelResourceSnapshot",
    "ModelResourceStore",
]
