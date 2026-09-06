from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any

from agent_shell import __version__
from agent_shell.configuration.bundles.archive import (
    build_bundle,
    canonical_tree_sha256,
    is_windows_reserved_name,
    materialize_files,
    snapshot_directory,
)
from agent_shell.configuration.bundles.contracts import (
    BundleManifest,
    BundleRecord,
    BundleRoot,
    PythonPackageAsset,
    SkillPackageAsset,
)
from agent_shell.configuration.bundles.validation import validate_bundle_snapshot
from agent_shell.configuration.dependencies import (
    ConfigurationEntity,
    iter_configuration_entities,
    iter_configuration_references,
)
from agent_shell.contracts import MANAGED_COMPONENT_MODELS
from agent_shell.python_packages.authoring import PACKAGE_COMPONENT_SPECS
from agent_shell.python_packages.packages import (
    resolve_owned_python_package_folder,
    scan_python_package,
)
from agent_shell.storage.file_config import CONFIG_VERSION, FileConfigRepository


class BundleExportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExportedBundle:
    content: bytes
    filename: str


def _bundle_download_filename(name: str, fallback: str) -> str:
    safe_name = "".join(
        character
        if character.isascii()
        and (character.isalnum() or character in {"-", "_", "."})
        else "-"
        for character in name.strip()
    ).strip("-.")
    safe_name = safe_name or fallback
    if is_windows_reserved_name(safe_name):
        safe_name = f"configuration-{safe_name}"
    return f"{safe_name}.agent-shell-config.zip"


def _matches_reference(target: ConfigurationEntity, reference: Any) -> bool:
    return target.kind == reference.target_kind and (
        target.kind != "component"
        or target.component_type == reference.target_component_type
    )


def _configuration_closure(
    config: dict[str, Any],
    root: BundleRoot,
) -> tuple[ConfigurationEntity, ...]:
    entities = tuple(iter_configuration_entities(config))
    by_id = {entity.id: entity for entity in entities}
    root_entity = by_id.get(root.source_id)
    if root_entity is None:
        raise BundleExportError("configuration bundle root does not exist")
    if (
        root_entity.kind != root.kind
        or (
            root.kind == "component"
            and root_entity.component_type != root.component_type
        )
    ):
        raise BundleExportError("configuration bundle root kind or type is incorrect")

    pending = [root_entity]
    included: dict[str, ConfigurationEntity] = {}
    while pending:
        owner = pending.pop()
        if owner.id in included:
            continue
        included[owner.id] = owner
        for reference in iter_configuration_references(owner):
            target = by_id.get(reference.target_id)
            if target is None:
                raise BundleExportError(
                    f"configuration reference is missing: {reference.path}"
                )
            if not _matches_reference(target, reference):
                raise BundleExportError(
                    f"configuration reference has the wrong type: {reference.path}"
                )
            pending.append(target)
    return tuple(
        sorted(
            included.values(),
            key=lambda item: (item.kind, item.component_type, item.id),
        )
    )


def _record(entity: ConfigurationEntity) -> BundleRecord:
    payload = deepcopy(entity.payload)
    payload.pop("id", None)
    identity_field = (
        "component_name"
        if entity.kind in {"subagent", "async_subagent"}
        else "name"
    )
    name = str(payload.pop(identity_field, ""))
    return BundleRecord(
        kind=entity.kind,
        type=entity.component_type or None,
        source_id=entity.id,
        name=name,
        payload=payload,
    )


def snapshot_config(entities: tuple[ConfigurationEntity, ...]) -> dict[str, Any]:
    config: dict[str, Any] = {
        "config_version": CONFIG_VERSION,
        "components": {},
        "main_agents": [],
        "subagents": [],
        "async_subagents": [],
        "workflows": [],
    }
    for entity in entities:
        record = deepcopy(entity.payload)
        if entity.kind == "component":
            config["components"].setdefault(entity.component_type, []).append(record)
        elif entity.kind == "main_agent":
            config["main_agents"].append(record)
        elif entity.kind == "subagent":
            config["subagents"].append(record)
        elif entity.kind == "async_subagent":
            config["async_subagents"].append(record)
        else:
            config["workflows"].append(record)
    return config


class ConfigurationBundleExporter:
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

    def _stable_package_snapshot(
        self,
        entity: ConfigurationEntity,
        folder: Path,
    ) -> dict[str, bytes]:
        spec = PACKAGE_COMPONENT_SPECS[entity.component_type]
        before = snapshot_directory(folder, exclude_python_runtime=True)
        temporary_root = self._runtime_root / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="configuration-bundle-export-",
            dir=temporary_root,
        ) as temporary_name:
            staged = Path(temporary_name) / entity.id
            materialize_files(staged, before)
            scan_python_package(
                staged,
                owner_id=entity.id,
                family=spec.family,  # type: ignore[arg-type]
                adapter=spec.adapter,  # type: ignore[arg-type]
                factory_name=spec.factory_name,
                factory_parameters=spec.factory_parameters,
                runtime_root=self._runtime_root,
            )
        after = snapshot_directory(folder, exclude_python_runtime=True)
        if canonical_tree_sha256(before) != canonical_tree_sha256(after):
            raise BundleExportError(
                f"Python package changed while it was exported: {entity.id}"
            )
        return before

    def _stable_skill_snapshot(self, owner_id: str, folder: Path) -> dict[str, bytes]:
        before = snapshot_directory(folder)
        after = snapshot_directory(folder)
        if canonical_tree_sha256(before) != canonical_tree_sha256(after):
            raise BundleExportError(
                f"Skill package changed while it was exported: {owner_id}"
            )
        return before

    def export(self, root: BundleRoot) -> ExportedBundle:
        entities = _configuration_closure(self._repository.config(), root)
        for entity in entities:
            if (
                entity.kind == "component"
                and entity.component_type not in MANAGED_COMPONENT_MODELS
            ):
                raise BundleExportError(
                    f"configuration component type is unsupported: {entity.component_type}"
                )
        report = validate_bundle_snapshot(
            snapshot_config(entities),
            data_root=self._repository.data_root,
            packages_dir=self._packages_dir,
            runtime_root=self._runtime_root,
        )
        if not report.valid:
            first = next(issue for issue in report.issues if issue.severity == "error")
            raise BundleExportError(
                f"configuration closure is invalid: {first.path}: {first.message}"
            )

        records = tuple(_record(entity) for entity in entities)
        assets: list[PythonPackageAsset | SkillPackageAsset] = []
        archive_files: dict[str, bytes] = {}
        for entity in entities:
            if entity.kind != "component":
                continue
            spec = PACKAGE_COMPONENT_SPECS.get(entity.component_type)
            if spec is not None:
                reference = entity.payload.get("python_package", {})
                folder_name = (
                    str(reference.get("folder", ""))
                    if isinstance(reference, dict)
                    else ""
                )
                if folder_name != entity.name:
                    raise BundleExportError(
                        "Python package folder does not match its Component name"
                    )
                folder = resolve_owned_python_package_folder(
                    folder_name,
                    self._packages_dir,
                    owner_id=entity.id,
                    adapter=spec.adapter,  # type: ignore[arg-type]
                )
                if folder is None:
                    raise BundleExportError(
                        f"Python package is missing for configuration {entity.id}"
                    )
                files = self._stable_package_snapshot(entity, folder)
                prefix = f"assets/python_packages/{entity.id}/"
                archive_files.update(
                    {f"{prefix}{path}": content for path, content in files.items()}
                )
                assets.append(
                    PythonPackageAsset(
                        kind="python-package",
                        owner_source_id=entity.id,
                        path=prefix,
                        sha256=canonical_tree_sha256(files),
                    )
                )
            if entity.component_type == "skill":
                reference = entity.payload.get("skill_package")
                if not isinstance(reference, dict) or reference.get("folder") != entity.name:
                    raise BundleExportError(
                        "Skill package folder does not match its Component name"
                    )
                folder = self._skills_dir / entity.name
                if not folder.is_dir() or folder.is_symlink():
                    raise BundleExportError(
                        f"Skill package is missing for configuration {entity.id}"
                    )
                files = self._stable_skill_snapshot(entity.id, folder)
                prefix = f"assets/skill_packages/{entity.id}/"
                archive_files.update(
                    {f"{prefix}{path}": content for path, content in files.items()}
                )
                assets.append(
                    SkillPackageAsset(
                        kind="skill-package",
                        owner_source_id=entity.id,
                        path=prefix,
                        sha256=canonical_tree_sha256(files),
                    )
                )

        manifest = BundleManifest(
            source_application_version=__version__,
            root=root,
            records=list(records),
            assets=sorted(
                assets,
                key=lambda asset: (
                    asset.kind,
                    getattr(asset, "owner_source_id", ""),
                    "",
                ),
            ),
        )
        filename_name = next(
            record.name for record in records if record.source_id == root.source_id
        )
        return ExportedBundle(
            content=build_bundle(manifest, archive_files),
            filename=_bundle_download_filename(filename_name, root.kind),
        )


__all__ = [
    "BundleExportError",
    "ConfigurationBundleExporter",
    "ExportedBundle",
    "snapshot_config",
]
