from __future__ import annotations

import os
import shutil
from pathlib import Path
import tempfile
from typing import Any

from agent_shell.configuration.identity import require_configuration_id
from agent_shell.registries.errors import ResourceScanError
from agent_shell.registries.skills import (
    scan_private_skill_package,
    scan_skill_folder,
    scan_skill_templates,
)
from agent_shell.storage.owned_paths import (
    OwnedPathError,
    is_plain_tree,
    is_reparse_point,
    require_single_path_segment,
    resolve_owned_relative_path,
)
from agent_shell.storage.staged_changes import StagedPathChange


class SkillPackageAuthoringError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillPackageAuthoringError(
            "skill_template_path_invalid", "A Skill Template path is required."
        )
    path = value.strip().replace("\\", "/")
    parts = path.split("/")
    if (
        path.startswith("/")
        or any(not part or part in {".", ".."} for part in parts)
        or any("\x00" in part for part in parts)
    ):
        raise SkillPackageAuthoringError(
            "skill_template_path_invalid", "The Skill Template path is invalid."
        )
    return "/".join(parts)


class SkillPackageAuthoringService:
    def __init__(
        self,
        *,
        templates_root: Path,
        instances_root: Path | Any,
    ) -> None:
        self._templates_root = templates_root.resolve()
        self._instances_root_source = instances_root

    @property
    def instances_root(self) -> Path:
        value = self._instances_root_source() if callable(self._instances_root_source) else self._instances_root_source
        return Path(value).resolve()

    def template_catalog(self) -> dict[str, Any]:
        return scan_skill_templates(self._templates_root)

    def _template_folder(self, template_path: object) -> Path:
        relative = _safe_relative_path(template_path)
        try:
            folder, _ = resolve_owned_relative_path(
                self._templates_root,
                relative,
                label="Skill Template path",
            )
        except OwnedPathError as exc:
            raise SkillPackageAuthoringError(
                "skill_template_path_invalid", "The Skill Template path escapes its repository."
            ) from exc
        if not folder.is_dir() or not is_plain_tree(folder):
            raise SkillPackageAuthoringError(
                "skill_template_not_found", "The selected Skill Template is not available."
            , status_code=404)
        try:
            scan_skill_folder(folder)
        except ResourceScanError as exc:
            raise SkillPackageAuthoringError(
                "skill_template_invalid", "The selected Skill Template is invalid."
            ) from exc
        return folder

    def _owner_root(self, owner_id: str) -> Path:
        try:
            owner_id = require_configuration_id(owner_id, label="Skill package owner")
        except ValueError as exc:
            raise SkillPackageAuthoringError(
                "skill_package_owner_invalid", "The Skill package owner is invalid."
            ) from exc
        return self.instances_root / owner_id

    def inspect(self, owner_id: str) -> dict[str, Any]:
        root = self._owner_root(owner_id)
        report = scan_private_skill_package(root)
        return {
            "folder": owner_id,
            "path": str(root),
            "catalog": report["catalog"],
            "warnings": report["errors"],
        }

    def _existing_names(self, root: Path) -> set[str]:
        names: set[str] = set()
        if not root.exists():
            return names
        for child in root.iterdir():
            if not child.is_dir() or is_reparse_point(child):
                continue
            try:
                item = scan_skill_folder(child)
            except ResourceScanError:
                continue
            names.add(str(item["name"]))
        return names

    def _copy_template(self, source: Path, destination: Path) -> None:
        if destination.exists():
            raise SkillPackageAuthoringError(
                "skill_name_conflict",
                "A Skill with this name already exists in the private package.",
                status_code=409,
            )
        shutil.copytree(source, destination, symlinks=False)

    def create(
        self,
        owner_id: str,
        template_paths: list[str],
    ) -> tuple[dict[str, str], StagedPathChange]:
        if not template_paths:
            raise SkillPackageAuthoringError(
                "skill_templates_required", "Select at least one Skill Template."
            )
        root = self._owner_root(owner_id)
        if os.path.lexists(root):
            raise SkillPackageAuthoringError(
                "skill_package_exists", "The Skill private package already exists.", status_code=409
            )
        sources = [self._template_folder(path) for path in template_paths]
        names = [str(scan_skill_folder(source)["name"]) for source in sources]
        if len(names) != len(set(names)):
            raise SkillPackageAuthoringError(
                "skill_name_conflict", "Selected Skill Templates contain a duplicate name.", status_code=409
            )
        root.mkdir(parents=True, exist_ok=False)
        try:
            for source, name in zip(sources, names, strict=True):
                self._copy_template(source, root / name)
        except BaseException:
            shutil.rmtree(root, ignore_errors=True)
            raise
        return (
            {"folder": owner_id},
            StagedPathChange(lambda: shutil.rmtree(root, ignore_errors=True)),
        )

    def copy(self, source_owner_id: str, target_owner_id: str) -> StagedPathChange:
        source = self._owner_root(source_owner_id)
        target = self._owner_root(target_owner_id)
        if not source.is_dir() or not is_plain_tree(source):
            raise SkillPackageAuthoringError(
                "skill_package_not_found", "The source Skill private package is unavailable.", status_code=404
            )
        if os.path.lexists(target):
            raise SkillPackageAuthoringError(
                "skill_package_exists", "The target Skill private package already exists.", status_code=409
            )
        shutil.copytree(source, target, symlinks=False)
        return StagedPathChange(lambda: shutil.rmtree(target, ignore_errors=True))

    def stage_delete(self, owner_id: str) -> StagedPathChange:
        root = self._owner_root(owner_id)
        if not os.path.lexists(root):
            return StagedPathChange(lambda: None)
        if not is_plain_tree(root):
            raise SkillPackageAuthoringError(
                "skill_package_owner_invalid", "The Skill private package path is unsafe."
            )
        staging = Path(tempfile.mkdtemp(prefix=f".{owner_id}.", dir=root.parent))
        staged = staging / root.name
        shutil.move(str(root), str(staged))

        def rollback() -> None:
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)
            if staged.exists():
                shutil.move(str(staged), str(root))
            staging.rmdir()

        def finalize() -> None:
            shutil.rmtree(staging, ignore_errors=True)

        return StagedPathChange(rollback, finalize)

    def add(self, owner_id: str, template_path: str) -> StagedPathChange:
        root = self._owner_root(owner_id)
        source = self._template_folder(template_path)
        name = str(scan_skill_folder(source)["name"])
        if os.path.lexists(root) and not is_plain_tree(root):
            raise SkillPackageAuthoringError(
                "skill_package_owner_invalid", "The Skill private package path is unsafe."
            )
        root.mkdir(parents=True, exist_ok=True)
        if name in self._existing_names(root) or (root / name).exists():
            raise SkillPackageAuthoringError(
                "skill_name_conflict",
                "A Skill with this name already exists. Delete it and refresh before adding it again.",
                status_code=409,
            )
        destination = root / name
        self._copy_template(source, destination)
        return StagedPathChange(lambda: shutil.rmtree(destination, ignore_errors=True))

    def remove(self, owner_id: str, folder_name: str) -> StagedPathChange:
        try:
            folder_name = require_single_path_segment(
                folder_name, label="private Skill folder"
            )
        except OwnedPathError as exc:
            raise SkillPackageAuthoringError(
                "skill_folder_invalid", "The private Skill folder is invalid."
            ) from exc
        root = self._owner_root(owner_id)
        target = root / folder_name
        if not target.is_dir() or is_reparse_point(target):
            raise SkillPackageAuthoringError(
                "skill_not_found", "The selected private Skill does not exist.", status_code=404
            )
        staging = Path(tempfile.mkdtemp(prefix=f".{owner_id}.", dir=root.parent))
        staged = staging / target.name
        shutil.move(str(target), str(staged))

        def rollback() -> None:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            if staged.exists():
                shutil.move(str(staged), str(target))
            staging.rmdir()

        def finalize() -> None:
            shutil.rmtree(staging, ignore_errors=True)

        return StagedPathChange(rollback, finalize)


__all__ = ["SkillPackageAuthoringError", "SkillPackageAuthoringService"]
