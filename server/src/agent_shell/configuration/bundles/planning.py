from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any

from agent_shell.configuration.bundles.archive import ParsedBundle, parse_bundle
from agent_shell.configuration.bundles.assets import (
    PackageAssetPlan,
    SkillPackageAssetPlan,
    materialize_skill_package_assets,
    materialize_package_assets,
    validate_asset_ownership,
)
from agent_shell.configuration.bundles.contracts import (
    ImportResolutions,
)
from agent_shell.configuration.bundles.errors import BundleImportError
from agent_shell.configuration.bundles.exporting import snapshot_config
from agent_shell.configuration.bundles.filesystem import (
    FilesystemBinding,
    apply_filesystem_bindings,
    apply_validation_placeholders,
    collect_filesystem_bindings,
)
from agent_shell.configuration.bundles.validation import validate_bundle_snapshot
from agent_shell.configuration.bundles.records import (
    load_bundle_record_set,
    plan_identities,
    transform_bundle_records,
)
from agent_shell.configuration.dependencies import (
    ConfigurationEntity,
    iter_configuration_entities,
)
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.owned_paths import (
    OwnedPathError,
    resolve_data_root_relative_path,
)


@dataclass(frozen=True, slots=True)
class PreparedImport:
    parsed: ParsedBundle
    target_ids: dict[str, str]
    target_entities: tuple[ConfigurationEntity, ...]
    candidate_config: dict[str, Any]
    package_plans: tuple[PackageAssetPlan, ...]
    skill_plans: tuple[SkillPackageAssetPlan, ...]
    filesystem_bindings: tuple[FilesystemBinding, ...]
    public_plan: dict[str, object]


def _issue(code: str, message: str, **fields: object) -> dict[str, object]:
    return {"code": code, "message": message, **fields}


class BundleImportPlanner:
    def __init__(
        self,
        repository: FileConfigRepository,
        *,
        packages_dir: Path,
        skills_dir: Path,
        runtime_root: Path,
    ) -> None:
        self._repository = repository
        self._packages_dir = packages_dir
        self._skills_dir = skills_dir
        self._runtime_root = runtime_root

    def preview(self, content: bytes) -> PreparedImport:
        return self.prepare(content, resolutions=None, require_resolved=False)

    def prepare(
        self,
        content: bytes,
        *,
        resolutions: ImportResolutions | None,
        require_resolved: bool,
    ) -> PreparedImport:
        parsed = parse_bundle(content)
        record_set = load_bundle_record_set(parsed.manifest)
        source_entities = record_set.entities
        component_types = record_set.component_types
        component_records = record_set.component_records
        package_assets, skill_assets = validate_asset_ownership(
            parsed,
            component_types,
            record_set.skill_package_owners,
        )

        existing = tuple(iter_configuration_entities(self._repository.config()))
        identities = plan_identities(
            record_set,
            existing,
            resolutions,
            require_resolved=require_resolved,
            forbidden_ids=self._repository.all_configuration_ids(),
        )
        target_ids = identities.target_ids
        name_plans = identities.records
        name_errors = identities.errors
        supplied_names = identities.supplied_names

        bindings = collect_filesystem_bindings(component_records)
        raw_payloads = {
            source_id: deepcopy(payload)
            for source_id, (_component_type, _name, payload) in component_records.items()
        }
        binding_resolutions = (
            dict(resolutions.filesystem_bindings) if resolutions is not None else {}
        )
        try:
            resolved_component_payloads, binding_errors = apply_filesystem_bindings(
                raw_payloads,
                bindings,
                binding_resolutions,
                data_root=self._repository.data_root,
                require_resolved=require_resolved,
            )
        except ValueError as exc:
            raise BundleImportError(str(exc)) from exc

        target_entities = transform_bundle_records(
            record_set,
            identities,
            resolved_component_payloads,
        )

        errors: list[dict[str, object]] = [*name_errors, *binding_errors]
        warnings: list[dict[str, object]] = [
            _issue(
                "review_user_authored_content_for_secrets",
                "Review prompts, Skill files, and Python source before sharing or importing.",
            )
        ]
        for binding in bindings:
            resolution = binding_resolutions.get(binding.binding_id)
            selected_origin = (
                resolution.path_origin
                if resolution is not None
                else binding.source_path_origin
            )
            selected_value = (
                resolution.value if resolution is not None else binding.source_value
            )
            if binding.required and not require_resolved:
                errors.append(
                    _issue(
                        "filesystem_binding_required",
                        "A target filesystem path must be selected.",
                        source_id=binding.source_id,
                        path=binding.path,
                    )
                )
            elif selected_origin == "data-root-relative":
                try:
                    relative_target = resolve_data_root_relative_path(
                        self._repository.data_root,
                        selected_value,
                        label="mapped directory binding",
                    )
                except OwnedPathError:
                    continue
                if not relative_target.is_dir():
                    warnings.append(
                        _issue(
                            "filesystem_relative_target_missing",
                            "The data-root-relative mapped directory does not exist on this instance.",
                            source_id=binding.source_id,
                            path=binding.path,
                        )
                    )

        temporary_root = self._runtime_root / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="configuration-bundle-preview-",
            dir=temporary_root,
        ) as temporary_name:
            temporary = Path(temporary_name)
            staged_packages = temporary / "packages"
            staged_skills = temporary / "skills"
            staged_packages.mkdir()
            staged_skills.mkdir()
            package_plans = materialize_package_assets(
                parsed,
                package_assets,
                component_types,
                target_ids,
                staged_packages,
                runtime_root=self._runtime_root,
            )
            skill_plans = materialize_skill_package_assets(
                parsed,
                skill_assets,
                target_ids,
                staged_skills,
            )

            validation_entities = target_entities
            if bindings and not require_resolved:
                placeholder_payloads = apply_validation_placeholders(
                    {
                        source_id: deepcopy(payload)
                        for source_id, payload in resolved_component_payloads.items()
                    },
                    bindings,
                    temporary / "filesystem-placeholders",
                )
                replacement: list[ConfigurationEntity] = []
                target_by_source = {
                    source.id: target
                    for source, target in zip(source_entities, target_entities, strict=True)
                }
                for source in source_entities:
                    target = target_by_source[source.id]
                    payload = deepcopy(target.payload)
                    if source.id in placeholder_payloads:
                        payload.update(placeholder_payloads[source.id])
                    replacement.append(
                        ConfigurationEntity(
                            id=target.id,
                            kind=target.kind,
                            component_type=target.component_type,
                            name=target.name,
                            payload=payload,
                        )
                    )
                validation_entities = tuple(replacement)
            report = validate_bundle_snapshot(
                snapshot_config(validation_entities),
                data_root=self._repository.data_root,
                packages_dir=staged_packages,
                runtime_root=self._runtime_root,
            )
            for issue in report.issues:
                target = warnings if issue.severity == "warning" else errors
                target.append(issue.as_dict())

        for entity in source_entities:
            if entity.kind == "component" and entity.component_type == "model-requirement":
                warnings.append(
                    _issue(
                        "model_requirement_unbound",
                        "The imported Model Requirement is not bound to a local model connection.",
                        source_id=entity.id,
                    )
                )
            if entity.kind == "workflow":
                warnings.append(
                    _issue(
                        "workflow_imported_disabled",
                        "Imported Workflows are disabled until explicitly validated and enabled.",
                        source_id=entity.id,
                    )
                )
        for plan in package_plans:
            warnings.append(
                _issue(
                    "trusted_python_package",
                    "The bundle contains Python code that will run with Agent Shell privileges.",
                    source_id=plan.source_id,
                )
            )
            warnings.append(
                _issue(
                    "opaque_python_runtime_target",
                    "Static validation cannot prove the behavior of the bundled Python factory.",
                    source_id=plan.source_id,
                )
            )
            if plan.requirements:
                warnings.append(
                    _issue(
                        "python_requirements_restart_required",
                        "Restart Agent Shell after import to prepare Python dependencies.",
                        source_id=plan.source_id,
                    )
                )

        unresolved_names = any(
            item["requires_confirmation"]
            and item["source_id"] not in supplied_names
            for item in name_plans
        )
        public_plan: dict[str, object] = {
            "bundle_sha256": parsed.bundle_sha256,
            "manifest_sha256": parsed.manifest_sha256,
            "root": {
                "kind": parsed.manifest.root.kind,
                "type": parsed.manifest.root.component_type,
                "source_id": parsed.manifest.root.source_id,
                "target_id": target_ids[parsed.manifest.root.source_id],
                "workflow_role": (
                    next(
                        entity.payload.get("workflow_role")
                        for entity in source_entities
                        if entity.id == parsed.manifest.root.source_id
                    )
                    if parsed.manifest.root.kind == "workflow"
                    else None
                ),
            },
            "target_ids": dict(sorted(target_ids.items())),
            "records": name_plans,
            "filesystem_bindings": [
                binding.as_dict(self._repository.data_root) for binding in bindings
            ],
            "skill_packages": [
                {
                    "source_id": plan.source_id,
                    "target_id": plan.target_id,
                    "sha256": plan.asset.sha256,
                }
                for plan in skill_plans
            ],
            "errors": errors,
            "warnings": warnings,
            "ready": not errors and not unresolved_names,
        }
        candidate_config = snapshot_config(target_entities)
        return PreparedImport(
            parsed=parsed,
            target_ids=target_ids,
            target_entities=target_entities,
            candidate_config=candidate_config,
            package_plans=package_plans,
            skill_plans=skill_plans,
            filesystem_bindings=bindings,
            public_plan=public_plan,
        )


__all__ = ["BundleImportError", "BundleImportPlanner", "PreparedImport"]
