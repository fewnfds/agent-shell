from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agent_shell.configuration.dependencies import ConfigurationEntityKind
from agent_shell.configuration.identity import ConfigurationId
from agent_shell.configuration.repositories import list_configuration_repositories
from agent_shell.configuration.repositories import (
    CONFIGURATION_IMPORTS_DIRECTORY,
    PYTHON_PACKAGES_DIRECTORY,
    SKILL_PACKAGES_DIRECTORY,
)
from agent_shell.python_packages.authoring import PackageAdapterDirectory
from agent_shell.python_packages.contracts import PackageFolder


_TRANSACTION_DIR = CONFIGURATION_IMPORTS_DIRECTORY
_RECOVERY_LOCK = threading.RLock()
_ASSET_CLAIM_PREFIX = ".agent-shell-import-owner-"


class JournalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: ConfigurationEntityKind
    target_id: ConfigurationId
    component_type: str | None = Field(default=None, alias="type")

    @model_validator(mode="after")
    def validate_type(self) -> "JournalRecord":
        if (self.kind == "component") != (self.component_type is not None):
            raise ValueError("journal type is required only for Component records")
        if self.component_type is not None and (
            not self.component_type
            or not self.component_type.replace("-", "a").isalnum()
            or not self.component_type[0].isalpha()
            or self.component_type != self.component_type.lower()
        ):
            raise ValueError("journal Component type is invalid")
        return self


class JournalPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: PackageAdapterDirectory
    target_id: ConfigurationId
    folder: PackageFolder


class JournalSkillPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: ConfigurationId
    folder: PackageFolder


class ImportJournal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: Literal[4] = 4
    transaction_id: ConfigurationId
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["prepared", "committed"]
    records: list[JournalRecord]
    packages: list[JournalPackage]
    skill_packages: list[JournalSkillPackage]


def transaction_root(repository_root: Path) -> Path:
    return repository_root / _TRANSACTION_DIR


def write_import_journal(path: Path, journal: ImportJournal) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                journal.model_dump(mode="json", by_alias=True),
                stream,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _configuration_path(config_root: Path, record: JournalRecord) -> Path:
    if record.kind == "component":
        return (
            config_root
            / "components"
            / str(record.component_type)
            / f"{record.target_id}.yaml"
        )
    if record.kind == "main_agent":
        return config_root / "agents" / "main" / f"{record.target_id}.yaml"
    if record.kind == "subagent":
        return config_root / "agents" / "subagent" / f"{record.target_id}.yaml"
    return config_root / "workflows" / f"{record.target_id}.yaml"


def _assert_owned_path(path: Path, owner: Path) -> Path:
    resolved_owner = owner.resolve()
    resolved_path = path.resolve()
    if resolved_path.parent != resolved_owner:
        raise RuntimeError("configuration import recovery path escaped its owner")
    return resolved_path


def _asset_claim(folder: Path, transaction_id: str) -> Path:
    return folder / f"{_ASSET_CLAIM_PREFIX}{transaction_id}"


def claim_import_asset(folder: Path, transaction_id: str) -> None:
    marker = _asset_claim(folder, transaction_id)
    if marker.exists():
        raise RuntimeError("configuration import asset claim already exists")
    marker.write_text(transaction_id, encoding="ascii")


def _cleanup_claimed_asset(
    path: Path,
    owner: Path,
    transaction_id: str,
    *,
    remove_asset: bool,
) -> None:
    resolved_path = _assert_owned_path(path, owner)
    if not resolved_path.is_dir():
        return
    marker = _asset_claim(resolved_path, transaction_id)
    try:
        claimed = marker.read_text(encoding="ascii") == transaction_id
    except (OSError, UnicodeError):
        claimed = False
    if not claimed:
        return
    if remove_asset:
        shutil.rmtree(resolved_path)
    else:
        marker.unlink(missing_ok=True)


def _remove_owned_tree(path: Path, owner: Path) -> None:
    resolved_path = _assert_owned_path(path, owner)
    if resolved_path.exists():
        shutil.rmtree(resolved_path)


def cleanup_import_journal(repository_root: Path, journal: ImportJournal) -> None:
    root = transaction_root(repository_root)
    remove_assets = journal.state == "prepared"
    if remove_assets:
        for record in journal.records:
            _configuration_path(repository_root, record).unlink(missing_ok=True)
    packages_root = repository_root / PYTHON_PACKAGES_DIRECTORY
    for package in journal.packages:
        adapter_root = packages_root / package.directory
        _cleanup_claimed_asset(
            adapter_root / package.folder,
            adapter_root,
            journal.transaction_id,
            remove_asset=remove_assets,
        )
    skills_root = repository_root / SKILL_PACKAGES_DIRECTORY
    for skill in journal.skill_packages:
        _cleanup_claimed_asset(
            skills_root / skill.folder,
            skills_root,
            journal.transaction_id,
            remove_asset=remove_assets,
        )
    staging_root = root / "staging"
    _remove_owned_tree(staging_root / journal.transaction_id, staging_root)
    (root / "journals" / f"{journal.transaction_id}.json").unlink(missing_ok=True)


def recover_configuration_imports(data_root: Path) -> None:
    with _RECOVERY_LOCK:
        for repository in list_configuration_repositories(data_root):
            journals = transaction_root(repository.root) / "journals"
            if not journals.exists():
                continue
            for path in sorted(journals.glob("*.json")):
                try:
                    UUID(path.stem, version=4)
                    journal = ImportJournal.model_validate_json(
                        path.read_text(encoding="utf-8")
                    )
                except (ValueError, OSError, UnicodeError, ValidationError) as exc:
                    raise RuntimeError(
                        f"configuration import journal is invalid: {path.name}"
                    ) from exc
                if journal.transaction_id != path.stem:
                    raise RuntimeError(
                        f"configuration import journal identity mismatch: {path.name}"
                    )
                cleanup_import_journal(repository.root, journal)


__all__ = [
    "ImportJournal",
    "JournalPackage",
    "JournalRecord",
    "JournalSkillPackage",
    "cleanup_import_journal",
    "claim_import_asset",
    "recover_configuration_imports",
    "transaction_root",
    "write_import_journal",
]
