from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
from uuid import uuid4

from agent_shell.configuration.bundles.assets import (
    materialize_package_assets,
    materialize_skill_package_assets,
)
from agent_shell.configuration.bundles.errors import BundleImportError
from agent_shell.configuration.bundles.planning import PreparedImport
from agent_shell.configuration.bundles.journal import (
    ImportJournal,
    JournalPackage,
    JournalRecord,
    JournalSkillPackage,
    claim_import_asset,
    cleanup_import_journal,
    transaction_root,
    write_import_journal,
)
from agent_shell.configuration.dependencies import iter_configuration_entities
from agent_shell.python_packages.authoring import PACKAGE_COMPONENT_SPECS
from agent_shell.storage.file_config import FileConfigRepository


def _append_imported_records(config: dict, prepared: PreparedImport) -> None:
    for entity in prepared.target_entities:
        record = deepcopy(entity.payload)
        if entity.kind == "component":
            config.setdefault("components", {}).setdefault(
                entity.component_type, []
            ).append(record)
        elif entity.kind == "main_agent":
            config.setdefault("main_agents", []).append(record)
        elif entity.kind == "subagent":
            config.setdefault("subagents", []).append(record)
        else:
            record["enabled"] = False
            config.setdefault("workflows", []).append(record)


def _remove_imported_records(config: dict, target_ids: set[str]) -> None:
    components = config.get("components", {})
    if isinstance(components, dict):
        for component_type, records in components.items():
            if isinstance(records, list):
                components[component_type] = [
                    record
                    for record in records
                    if not isinstance(record, dict)
                    or record.get("id") not in target_ids
                ]
    for key in ("main_agents", "subagents", "workflows"):
        records = config.get(key, [])
        if isinstance(records, list):
            config[key] = [
                record
                for record in records
                if not isinstance(record, dict)
                or record.get("id") not in target_ids
            ]


def commit_prepared_import(
    repository: FileConfigRepository,
    prepared: PreparedImport,
    *,
    packages_dir: Path,
    skills_dir: Path,
    runtime_root: Path,
) -> dict[str, object]:
    transaction_id = str(uuid4())
    root = transaction_root(repository.config_root)
    journal_path = root / "journals" / f"{transaction_id}.json"
    staging = root / "staging" / transaction_id
    package_assets = {
        plan.source_id: plan.asset for plan in prepared.package_plans
    }
    skill_assets = {plan.source_id: plan.asset for plan in prepared.skill_plans}
    journal = ImportJournal(
        transaction_id=transaction_id,
        bundle_sha256=prepared.parsed.bundle_sha256,
        state="prepared",
        records=[
            JournalRecord(
                kind=entity.kind,
                type=entity.component_type or None,
                target_id=entity.id,
            )
            for entity in prepared.target_entities
        ],
        packages=[
            JournalPackage(
                adapter=PACKAGE_COMPONENT_SPECS[plan.component_type].adapter,
                target_id=plan.target_id,
                folder=plan.target_folder,
            )
            for plan in prepared.package_plans
        ],
        skill_packages=[
            JournalSkillPackage(
                target_id=plan.target_id,
                folder=plan.target_folder,
            )
            for plan in prepared.skill_plans
        ],
    )
    with repository.exclusive_config_mutation():
        current_ids = {
            entity.id
            for entity in iter_configuration_entities(repository.config())
        }
        if current_ids.intersection(prepared.target_ids.values()):
            raise BundleImportError(
                "target UUID state changed after import preview"
            )
        write_import_journal(journal_path, journal)
        published = False
        durably_committed = False
        try:
            staging.mkdir(parents=True, exist_ok=False)
            staged_packages = staging / "packages"
            staged_skills = staging / "skills"
            staged_packages.mkdir()
            staged_skills.mkdir()
            materialize_package_assets(
                prepared.parsed,
                package_assets,
                {
                    plan.source_id: plan.component_type
                    for plan in prepared.package_plans
                },
                prepared.target_ids,
                {plan.source_id: plan.target_folder for plan in prepared.package_plans},
                staged_packages,
                runtime_root=runtime_root,
            )
            current_skill_plans = materialize_skill_package_assets(
                prepared.parsed,
                skill_assets,
                prepared.target_ids,
                {plan.source_id: plan.target_folder for plan in prepared.skill_plans},
                staged_skills,
            )

            for plan in prepared.package_plans:
                spec = PACKAGE_COMPONENT_SPECS[plan.component_type]
                claim_import_asset(
                    staged_packages / spec.directory / plan.target_folder,
                    transaction_id,
                )
            for plan in current_skill_plans:
                claim_import_asset(
                    staged_skills / plan.target_folder,
                    transaction_id,
                )

            for plan in prepared.package_plans:
                spec = PACKAGE_COMPONENT_SPECS[plan.component_type]
                source = staged_packages / spec.directory / plan.target_folder
                destination = packages_dir / spec.directory / plan.target_folder
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    raise BundleImportError(
                        "a target Python package directory already exists"
                    )
                os.rename(source, destination)
            for plan in current_skill_plans:
                source = staged_skills / plan.target_folder
                destination = skills_dir / plan.target_folder
                skills_dir.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    raise BundleImportError(
                        "a target Skill package directory already exists"
                    )
                os.rename(source, destination)

            repository.update_config(
                lambda config: _append_imported_records(config, prepared)
            )
            published = True
            committed = journal.model_copy(update={"state": "committed"})
            write_import_journal(journal_path, committed)
            durably_committed = True
            try:
                cleanup_import_journal(repository.config_root, committed)
            except Exception:
                # The committed journal makes startup cleanup safe and retryable.
                pass
        except BaseException:
            if durably_committed:
                raise
            rollback_error: BaseException | None = None
            if published:
                try:
                    repository.update_config(
                        lambda config: _remove_imported_records(
                            config, set(prepared.target_ids.values())
                        )
                    )
                except BaseException as exc:
                    rollback_error = exc
            if rollback_error is None:
                try:
                    cleanup_import_journal(repository.config_root, journal)
                except BaseException:
                    pass
            else:
                raise RuntimeError(
                    "configuration import rollback failed; restart is required"
                ) from rollback_error
            raise

    return {
        "bundle_sha256": prepared.parsed.bundle_sha256,
        "root": prepared.public_plan["root"],
        "target_ids": dict(sorted(prepared.target_ids.items())),
        "records": prepared.public_plan["records"],
        "skill_packages": prepared.public_plan["skill_packages"],
        "warnings": prepared.public_plan["warnings"],
    }


__all__ = ["commit_prepared_import"]
