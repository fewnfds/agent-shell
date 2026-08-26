from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from agent_shell.configuration.identity import normalize_configuration_name
from agent_shell.python_packages.authoring import PythonPackageAuthoringService
from agent_shell.skills.authoring import SkillPackageAuthoringService
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.staged_changes import StagedPathChange
from agent_shell.validation.models import ValidationReport
from agent_shell.validation.service import ConfigurationValidationService


class ComponentMutationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        message_key: str,
        status_code: int = 422,
        message_args: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message_key = message_key
        self.status_code = status_code
        self.message_args = message_args or {}


class ComponentMutationValidationError(RuntimeError):
    def __init__(self, report: ValidationReport) -> None:
        super().__init__("The component configuration failed validation.")
        self.report = report


class ComponentMutationService:
    """Commit Component records and their configuration-owned packages together."""

    def __init__(
        self,
        repository: FileConfigRepository,
        blocks: BlockStore,
        validation: ConfigurationValidationService,
        python_packages: PythonPackageAuthoringService,
        skill_packages: SkillPackageAuthoringService,
    ) -> None:
        self._repository = repository
        self._blocks = blocks
        self._validation = validation
        self._python_packages = python_packages
        self._skill_packages = skill_packages

    @contextmanager
    def _mutation(self) -> Iterator[str]:
        expected_repository_id = self._repository.repository_id
        with self._repository.exclusive_config_mutation(
            expected_repository_id=expected_repository_id
        ):
            yield expected_repository_id

    @staticmethod
    @contextmanager
    def _staged_changes() -> Iterator[list[StagedPathChange]]:
        changes: list[StagedPathChange] = []
        try:
            yield changes
        except BaseException:
            for change in reversed(changes):
                change.rollback()
            raise
        else:
            for change in changes:
                change.finalize()

    @staticmethod
    def _package_reference(payload: dict[str, Any]) -> dict[str, Any]:
        value = payload.get("python_package")
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _not_found() -> ComponentMutationError:
        return ComponentMutationError(
            "block_not_found",
            "The component configuration does not exist.",
            message_key="errors.blockNotFound",
            status_code=404,
        )

    @staticmethod
    def _name_conflict() -> ComponentMutationError:
        return ComponentMutationError(
            "configuration_name_conflict",
            "A configuration with this name already exists.",
            message_key="errors.configurationNameConflict",
            status_code=409,
        )

    def _validate(
        self,
        block_type: str,
        payload: dict[str, Any],
        *,
        block_id: str,
    ) -> dict[str, Any]:
        if block_type == "skill" and payload.get("skill_package") != {
            "folder": payload.get("name")
        }:
            raise ComponentMutationError(
                "skill_package_owner_invalid",
                "The Skill package folder must match its configuration name.",
                message_key="errors.skillPackageOwnerInvalid",
            )
        report, validated = self._validation.validate_block(
            block_type,
            payload,
            stage="block_save",
            owner_id=block_id,
        )
        if not report.valid:
            raise ComponentMutationValidationError(report)
        assert validated is not None
        return validated

    @staticmethod
    def _normalize_name(payload: dict[str, Any]) -> dict[str, Any]:
        candidate = dict(payload)
        try:
            candidate["name"] = normalize_configuration_name(
                candidate.get("name"),
                label="configuration name",
            )
        except ValueError as exc:
            raise ComponentMutationError(
                "configuration_name_invalid",
                str(exc),
                message_key="errors.configurationNameInvalid",
            ) from exc
        return candidate

    def _stage_create(
        self,
        block_type: str,
        block_id: str,
        payload: dict[str, Any],
        changes: list[StagedPathChange],
    ) -> dict[str, Any]:
        candidate = self._normalize_name(payload)
        if self._python_packages.supports(block_type):
            template = candidate.pop("python_package_template", None)
            if (
                not isinstance(template, dict)
                or set(template) != {"key", "revision"}
                or not isinstance(template.get("key"), str)
                or not template["key"].strip()
                or not isinstance(template.get("revision"), str)
                or not template["revision"]
            ):
                raise ComponentMutationError(
                    "python_package_template_required",
                    "Select a valid Python package template before saving.",
                    message_key="errors.pythonPackageTemplateRequired",
                )
            if candidate.get("python_package") != {"folder": ""}:
                raise ComponentMutationError(
                    "python_package_reference_invalid",
                    "A new Python package reference must contain an empty folder.",
                    message_key="errors.pythonPackageReferenceInvalid",
                )
            reference, change = self._python_packages.create(
                block_type,
                block_id,
                str(candidate["name"]),
                template_key=template["key"],
                template_revision=template["revision"],
            )
            changes.append(change)
            candidate["python_package"] = reference
        elif block_type == "skill":
            template_paths = candidate.pop("skill_template_paths", None)
            if not isinstance(template_paths, list) or not all(
                isinstance(item, str) for item in template_paths
            ):
                raise ComponentMutationError(
                    "skill_templates_required",
                    "Select at least one Skill Template.",
                    message_key="errors.skillTemplatesRequired",
                )
            reference, change = self._skill_packages.create(
                block_id, str(candidate["name"]), template_paths
            )
            changes.append(change)
            candidate["skill_package"] = reference
        return candidate

    def create(self, block_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._mutation() as repository_id:
            block_id = self._blocks.new_id()
            with self._staged_changes() as changes:
                candidate = self._stage_create(
                    block_type, block_id, payload, changes
                )
                validated = self._validate(
                    block_type, candidate, block_id=block_id
                )
                try:
                    self._blocks.save_block(
                        block_type,
                        block_id,
                        validated,
                        expected_repository_id=repository_id,
                    )
                except ValueError as exc:
                    raise self._name_conflict() from exc
            created = self._blocks.get_block(block_type, block_id)
            if created is None:
                raise RuntimeError("the committed Component record is unavailable")
            return created

    def copy(
        self,
        block_type: str,
        block_id: str,
        *,
        name: str,
    ) -> dict[str, Any]:
        with self._mutation() as repository_id:
            source = self._blocks.get_block_internal(block_type, block_id)
            if source is None:
                raise self._not_found()
            normalized_name = str(self._normalize_name({"name": name})["name"])
            report = self._validation.validate_block_copy(
                block_type, source, name=normalized_name
            )
            if not report.valid:
                raise ComponentMutationValidationError(report)
            new_id = self._blocks.new_id()
            with self._staged_changes() as changes:
                if self._python_packages.supports(block_type):
                    reference, change = self._python_packages.copy(
                        block_type,
                        block_id,
                        new_id,
                        normalized_name,
                        self._package_reference(source),
                    )
                    changes.append(change)
                    source = {**source, "python_package": reference}
                elif block_type == "skill":
                    source_folder = str(source.get("skill_package", {}).get("folder", ""))
                    changes.append(
                        self._skill_packages.copy(
                            block_id,
                            source_folder,
                            new_id,
                            normalized_name,
                        )
                    )
                    source = {
                        **source,
                        "skill_package": {"folder": normalized_name},
                    }
                try:
                    copied = self._blocks.copy_block(
                        block_type,
                        block_id,
                        new_id,
                        normalized_name,
                        source=source,
                        expected_repository_id=repository_id,
                    )
                except ValueError as exc:
                    raise self._name_conflict() from exc
                if copied is None:
                    raise self._not_found()
            return copied

    def update(
        self,
        block_type: str,
        block_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self._mutation() as repository_id:
            existing = self._blocks.get_block_internal(block_type, block_id)
            if existing is None:
                raise self._not_found()
            candidate = self._normalize_name(payload)
            if self._python_packages.supports(block_type):
                if candidate.get("python_package") != self._package_reference(existing):
                    raise ComponentMutationError(
                        "python_package_folder_immutable",
                        "An existing component cannot change its extension code directory reference.",
                        message_key="errors.pythonPackageFolderImmutable",
                        status_code=409,
                    )
            elif block_type == "skill" and candidate.get(
                "skill_package"
            ) != existing.get("skill_package"):
                raise ComponentMutationError(
                    "skill_package_folder_immutable",
                    "An existing Skill component cannot change its Skill package reference.",
                    message_key="errors.skillPackageFolderImmutable",
                    status_code=409,
                )
            with self._staged_changes() as changes:
                if str(candidate["name"]) != str(existing.get("name", "")):
                    if self._python_packages.supports(block_type):
                        reference, change = self._python_packages.stage_rename(
                            block_type,
                            block_id,
                            self._package_reference(existing),
                            str(candidate["name"]),
                        )
                        changes.append(change)
                        candidate["python_package"] = reference
                    elif block_type == "skill":
                        reference, change = self._skill_packages.stage_rename(
                            block_id,
                            str(existing.get("skill_package", {}).get("folder", "")),
                            str(candidate["name"]),
                        )
                        changes.append(change)
                        candidate["skill_package"] = reference
                validated = self._validate(block_type, candidate, block_id=block_id)
                try:
                    self._blocks.save_block(
                        block_type,
                        block_id,
                        validated,
                        expected_repository_id=repository_id,
                    )
                except ValueError as exc:
                    raise self._name_conflict() from exc
            updated = self._blocks.get_block(block_type, block_id)
            if updated is None:
                raise RuntimeError("the committed Component record is unavailable")
            return updated

    def _stage_delete(
        self,
        block_type: str,
        block_id: str,
        source: dict[str, Any],
    ) -> StagedPathChange | None:
        if self._python_packages.supports(block_type):
            return self._python_packages.stage_delete(
                block_type,
                block_id,
                self._package_reference(source),
            )
        if block_type == "skill":
            return self._skill_packages.stage_delete(
                block_id,
                str(source.get("skill_package", {}).get("folder", "")),
            )
        return None

    def delete(self, block_type: str, block_id: str) -> None:
        with self._mutation() as repository_id:
            source = self._blocks.get_block_internal(block_type, block_id)
            if source is None:
                raise self._not_found()
            with self._staged_changes() as changes:
                change = self._stage_delete(block_type, block_id, source)
                if change is not None:
                    changes.append(change)
                if not self._blocks.delete_block(
                    block_type,
                    block_id,
                    expected_repository_id=repository_id,
                ):
                    raise self._not_found()

    def delete_many(self, block_type: str, block_ids: list[str]) -> int:
        unique_ids = list(dict.fromkeys(block_ids))
        with self._mutation() as repository_id:
            sources: list[tuple[str, dict[str, Any]]] = []
            for block_id in unique_ids:
                source = self._blocks.get_block_internal(block_type, block_id)
                if source is None:
                    raise self._not_found()
                sources.append((block_id, source))
            with self._staged_changes() as changes:
                for block_id, source in sources:
                    change = self._stage_delete(block_type, block_id, source)
                    if change is not None:
                        changes.append(change)
                return self._blocks.delete_blocks(
                    block_type,
                    unique_ids,
                    expected_repository_id=repository_id,
                )

    def add_skill(self, block_id: str, template_path: str) -> dict[str, Any]:
        with self._mutation():
            block = self._blocks.get_block_internal("skill", block_id)
            if block is None:
                raise self._not_found()
            with self._staged_changes() as changes:
                folder = str(block.get("skill_package", {}).get("folder", ""))
                changes.append(self._skill_packages.add(block_id, folder, template_path))
                return self._skill_packages.inspect(block_id, folder)

    def remove_skill(self, block_id: str, folder_name: str) -> dict[str, Any]:
        with self._mutation():
            block = self._blocks.get_block_internal("skill", block_id)
            if block is None:
                raise self._not_found()
            with self._staged_changes() as changes:
                package_folder = str(block.get("skill_package", {}).get("folder", ""))
                changes.append(
                    self._skill_packages.remove(block_id, package_folder, folder_name)
                )
                return self._skill_packages.inspect(block_id, package_folder)


__all__ = [
    "ComponentMutationError",
    "ComponentMutationService",
    "ComponentMutationValidationError",
]
