from __future__ import annotations

import threading

from agent_shell.configuration.dependencies import (
    ConfigurationEntity,
    ConfigurationReference,
    iter_configuration_entities,
    iter_configuration_references,
)
from agent_shell.python_packages.authoring import PACKAGE_COMPONENT_SPECS
from agent_shell.contracts import MANAGED_COMPONENT_MODELS
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.model_connections import ModelResourceStore
from agent_shell.validation.models import ValidationIssue, ValidationReport
from agent_shell.validation.service import ConfigurationValidationService
from agent_shell.validation.workflows import validate_stored_workflow


_REFERENCE_NOT_FOUND_CODES = frozenset(
    {
        "assembly.main_agent_not_found",
        "assembly.reference_not_found",
        "assembly.subagent_not_found",
        "workflow.command_not_found",
        "workflow.task_dispatcher_not_found",
        "workflow_event_output_not_found",
    }
)


def _target_label(reference: ConfigurationReference) -> str:
    return reference.target_component_type or reference.target_kind


def _matches_target(
    target: ConfigurationEntity,
    reference: ConfigurationReference,
) -> bool:
    return target.kind == reference.target_kind and (
        reference.target_kind != "component"
        or target.component_type == reference.target_component_type
    )


def _dependency_issues(config: dict) -> list[ValidationIssue]:
    entities = tuple(iter_configuration_entities(config))
    by_id = {entity.id: entity for entity in entities}
    issues: list[ValidationIssue] = []
    for owner in entities:
        for reference in iter_configuration_references(owner):
            target = by_id.get(reference.target_id)
            common = {
                "scope": "block" if owner.kind == "component" else owner.kind,
                "owner_id": owner.id,
                "owner_name": owner.name,
                "owner_type": owner.component_type,
                "path": reference.path,
            }
            expected = _target_label(reference)
            if target is None:
                issues.append(
                    ValidationIssue(
                        code="storage.reference_not_found",
                        message=(
                            f"The referenced {expected} configuration does not exist."
                        ),
                        message_key="validation.issue.assembly.referenceNotFound",
                        message_args={"capability_type": expected},
                        **common,
                    )
                )
            elif not _matches_target(target, reference):
                actual = target.component_type or target.kind
                issues.append(
                    ValidationIssue(
                        code="storage.reference_type_mismatch",
                        message=(
                            f"The referenced UUID belongs to {actual}, not {expected}."
                        ),
                        message_key=(
                            "validation.issue.assembly.referencedBlockInvalid"
                        ),
                        message_args={
                            "capability_type": expected,
                            "block_name": target.name,
                            "detail": f"The UUID belongs to {actual}.",
                        },
                        **common,
                    )
                )
    return issues


class RepositoryValidationService:
    def __init__(
        self,
        repository: FileConfigRepository,
        blocks: BlockStore,
        configuration_validation: ConfigurationValidationService,
        *,
        model_resources: ModelResourceStore | None = None,
    ) -> None:
        self._repository = repository
        self._blocks = blocks
        self._configuration_validation = configuration_validation
        self._model_resources = model_resources
        self._cache_lock = threading.Lock()
        self._cached_context: tuple[str, int, int] | None = None
        self._cached_report: ValidationReport | None = None

    @staticmethod
    def _semantic_issues(report: ValidationReport) -> list[ValidationIssue]:
        return [
            issue
            for issue in report.issues
            if issue.code not in _REFERENCE_NOT_FOUND_CODES
        ]

    def validate_repository(self) -> ValidationReport:
        repository_id, repository_revision = self._repository.repository_context()
        model_revision = (
            self._model_resources.revision()
            if self._model_resources is not None
            else 0
        )
        context = (repository_id, repository_revision, model_revision)
        with self._cache_lock:
            if context == self._cached_context and self._cached_report is not None:
                return self._cached_report

        stage = "repository_load"
        config = self._repository.config()
        issues: list[ValidationIssue] = []
        components = config.get("components", {})
        for block_type, records in components.items():
            if block_type not in MANAGED_COMPONENT_MODELS:
                for block in records:
                    issues.append(
                        ValidationIssue(
                            code="storage.unknown_block_type",
                            scope="block",
                            owner_id=str(block.get("id", "")),
                            owner_name=str(block.get("name", "")),
                            owner_type=str(block_type),
                            path="block_type",
                            message=(
                                f"Stored configuration type {block_type!r} is not "
                                "supported."
                            ),
                            message_key="errors.unknownConfigurationType",
                            message_args={"type": str(block_type)},
                        )
                    )
                continue
            for block in records:
                if block_type == "skill" and block.get("skill_package") != {
                    "folder": block.get("id")
                }:
                    issues.append(
                        ValidationIssue(
                            code="storage.skill_package_owner_mismatch",
                            scope="block",
                            owner_id=str(block.get("id", "")),
                            owner_name=str(block.get("name", "")),
                            owner_type="skill",
                            path="skill_package.folder",
                            message="The Skill private package folder does not match its owner configuration.",
                            message_key="validation.issue.storage.skillPackageOwnerMismatch",
                            message_args={},
                        )
                    )
                issues.extend(
                    self._semantic_issues(
                        self._configuration_validation.validate_stored_block(
                            block_type,
                            block,
                            stage=stage,
                        )
                    )
                )

        for profile in config.get("subagents", []):
            report, _ = self._configuration_validation.validate_subagent(
                profile,
                stage=stage,
                owner_id=str(profile.get("id", "")),
                stored=True,
            )
            issues.extend(self._semantic_issues(report))
        for main_agent in config.get("main_agents", []):
            report, _, _ = self._configuration_validation.validate_main_agent(
                main_agent,
                stage=stage,
                owner_id=str(main_agent.get("id", "")),
                stored=True,
            )
            issues.extend(self._semantic_issues(report))
        for workflow in config.get("workflows", []):
            issues.extend(
                self._semantic_issues(
                    validate_stored_workflow(
                        workflow,
                        blocks=self._blocks,
                        configuration_validation=self._configuration_validation,
                        stage=stage,
                    )
                )
            )
        issues.extend(_dependency_issues(config))
        if self._model_resources is not None:
            available = {item["id"] for item in self._model_resources.list_connections()}
            for requirement in components.get("model-requirement", []):
                requirement_id = str(requirement.get("id", ""))
                connection_id = self._model_resources.get_binding(
                    self._repository.repository_id,
                    requirement_id,
                )
                if not connection_id or connection_id not in available:
                    issues.append(
                        ValidationIssue(
                            code="model_requirement_unbound",
                            scope="block",
                            owner_id=requirement_id,
                            owner_name=str(requirement.get("name", "")),
                            owner_type="model-requirement",
                            path="binding",
                            message="The model requirement is not bound to a local model connection.",
                            message_key="validation.issue.modelRequirementUnbound",
                            message_args={},
                            severity="warning",
                        )
                    )
        report = ValidationReport(stage=stage, issues=tuple(issues))
        has_external_package_assets = any(
            components.get(component_type)
            for component_type in PACKAGE_COMPONENT_SPECS
        )
        with self._cache_lock:
            if has_external_package_assets:
                self._cached_context = None
                self._cached_report = None
            else:
                self._cached_context = context
                self._cached_report = report
        return report


__all__ = ["RepositoryValidationService"]
