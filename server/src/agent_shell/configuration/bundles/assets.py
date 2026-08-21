from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from agent_shell.configuration.bundles.archive import (
    BundleArchiveError,
    ParsedBundle,
    materialize_files,
)
from agent_shell.configuration.bundles.contracts import (
    PythonPackageAsset,
    SkillPackageAsset,
)
from agent_shell.python_packages.authoring import PACKAGE_COMPONENT_SPECS
from agent_shell.python_packages.packages import scan_python_package
from agent_shell.registries.errors import ResourceScanError


@dataclass(frozen=True, slots=True)
class PackageAssetPlan:
    source_id: str
    target_id: str
    component_type: str
    asset: PythonPackageAsset
    requirements: bool


@dataclass(frozen=True, slots=True)
class SkillPackageAssetPlan:
    source_id: str
    target_id: str
    asset: SkillPackageAsset


def validate_asset_ownership(
    parsed: ParsedBundle,
    component_types: dict[str, str],
    skill_package_owners: set[str],
) -> tuple[dict[str, PythonPackageAsset], dict[str, SkillPackageAsset]]:
    packages = {
        asset.owner_source_id: asset
        for asset in parsed.manifest.assets
        if isinstance(asset, PythonPackageAsset)
    }
    skills = {
        asset.owner_source_id: asset
        for asset in parsed.manifest.assets
        if isinstance(asset, SkillPackageAsset)
    }
    expected_packages = {
        source_id
        for source_id, component_type in component_types.items()
        if component_type in PACKAGE_COMPONENT_SPECS
    }
    if set(packages) != expected_packages:
        raise BundleArchiveError(
            "bundle Python package assets do not match package-backed records"
        )
    if set(skills) != skill_package_owners:
        raise BundleArchiveError(
            "bundle Skill package assets do not match Skill Component records"
        )
    for source_id, asset in packages.items():
        if asset.path != f"assets/python-packages/{source_id}/":
            raise BundleArchiveError("bundle Python package asset path is not canonical")
    for source_id, asset in skills.items():
        if asset.path != f"assets/skill-packages/{source_id}/":
            raise BundleArchiveError("bundle Skill package asset path is not canonical")
    return packages, skills


def materialize_package_assets(
    parsed: ParsedBundle,
    packages: dict[str, PythonPackageAsset],
    component_types: dict[str, str],
    target_ids: dict[str, str],
    destination: Path,
    *,
    runtime_root: Path,
) -> tuple[PackageAssetPlan, ...]:
    plans: list[PackageAssetPlan] = []
    for source_id, asset in sorted(packages.items()):
        target_id = target_ids[source_id]
        component_type = component_types[source_id]
        spec = PACKAGE_COMPONENT_SPECS[component_type]
        folder = destination / spec.adapter / target_id
        materialize_files(folder, parsed.asset_files(asset.path))
        manifest_path = folder / "package.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BundleArchiveError(
                "bundled Python package has an invalid package.json"
            ) from exc
        if not isinstance(manifest, dict):
            raise BundleArchiveError(
                "bundled Python package package.json must contain an object"
            )
        manifest["id"] = target_id
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            scan_python_package(
                folder,
                owner_id=target_id,
                family=spec.family,  # type: ignore[arg-type]
                adapter=spec.adapter,  # type: ignore[arg-type]
                factory_name=spec.factory_name,
                factory_parameters=spec.factory_parameters,
                runtime_root=runtime_root,
            )
        except ResourceScanError as exc:
            raise BundleArchiveError(
                "bundled Python package does not satisfy its adapter contract"
            ) from exc
        requirements_path = folder / "requirements.txt"
        try:
            requirements = bool(
                requirements_path.is_file()
                and requirements_path.read_text(encoding="utf-8").strip()
            )
        except UnicodeError as exc:
            raise BundleArchiveError(
                "bundled Python package requirements.txt must use UTF-8"
            ) from exc
        plans.append(
            PackageAssetPlan(
                source_id=source_id,
                target_id=target_id,
                component_type=component_type,
                asset=asset,
                requirements=requirements,
            )
        )
    return tuple(plans)


def materialize_skill_package_assets(
    parsed: ParsedBundle,
    skills: dict[str, SkillPackageAsset],
    target_ids: dict[str, str],
    destination: Path,
) -> tuple[SkillPackageAssetPlan, ...]:
    plans: list[SkillPackageAssetPlan] = []
    for source_id, asset in sorted(skills.items()):
        target_id = target_ids[source_id]
        bundled = destination / target_id
        materialize_files(bundled, parsed.asset_files(asset.path))
        plans.append(
            SkillPackageAssetPlan(
                source_id=source_id,
                target_id=target_id,
                asset=asset,
            )
        )
    return tuple(plans)


__all__ = [
    "PackageAssetPlan",
    "SkillPackageAssetPlan",
    "materialize_skill_package_assets",
    "materialize_package_assets",
    "validate_asset_ownership",
]
