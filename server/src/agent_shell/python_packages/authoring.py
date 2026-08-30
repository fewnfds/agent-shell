from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any, Callable, Literal
from uuid import uuid4

from agent_shell.configuration.identity import (
    is_configuration_id,
    normalize_configuration_name,
)
from agent_shell.python_packages.packages import (
    PythonPackageManifest,
    inspect_python_package_draft,
    resolve_python_package,
    resolve_owned_python_package_folder,
    scan_python_package,
    scan_python_package_template,
    scan_python_package_templates,
)
from agent_shell.registries.errors import ResourceScanError
from agent_shell.storage.atomic_files import write_bytes_atomic
from agent_shell.storage.owned_paths import is_reparse_point
from agent_shell.storage.staged_changes import StagedPathChange


logger = logging.getLogger(__name__)


PackageAdapterDirectory = Literal[
    "command",
    "agent_middleware",
    "agent_event_output",
    "workflow_event_output",
    "agent_tool",
]


@dataclass(frozen=True, slots=True)
class PackageAdapterSpec:
    template_parts: tuple[str, str]
    example_parts: tuple[str, str]
    family: str
    adapter: str
    directory: PackageAdapterDirectory
    factory_name: str
    factory_parameters: tuple[str, ...] | None


PACKAGE_COMPONENT_SPECS: dict[str, PackageAdapterSpec] = {
    "custom-tool": PackageAdapterSpec(
        template_parts=("agent", "custom_tool"),
        example_parts=("agent-components", "custom-tool"),
        family="tool",
        adapter="agent-tool",
        directory="agent_tool",
        factory_name="create_tool",
        factory_parameters=(),
    ),
    "agent-event-output": PackageAdapterSpec(
        template_parts=("agent", "agent_event_output"),
        example_parts=("agent-components", "agent-event-output"),
        family="event-output",
        adapter="agent-event-output",
        directory="agent_event_output",
        factory_name="output",
        factory_parameters=("event", "origin"),
    ),
    "workflow-event-output": PackageAdapterSpec(
        template_parts=("workflow", "workflow_event_output"),
        example_parts=("workflow-components", "workflow-event-output"),
        family="event-output",
        adapter="workflow-event-output",
        directory="workflow_event_output",
        factory_name="output",
        factory_parameters=("event", "origin"),
    ),
    "command": PackageAdapterSpec(
        template_parts=("workflow", "command"),
        example_parts=("workflow-components", "command"),
        family="workflow-node",
        adapter="command",
        directory="command",
        factory_name="create_command",
        factory_parameters=(),
    ),
    "custom-middleware": PackageAdapterSpec(
        template_parts=("agent", "custom_middleware"),
        example_parts=("agent-components", "custom-middleware"),
        family="middleware",
        adapter="agent-middleware",
        directory="agent_middleware",
        factory_name="create_middleware",
        factory_parameters=None,
    ),
}


BUILTIN_EXAMPLE_TEMPLATE_PREFIX = "内置示例-"


class PythonPackageAuthoringError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class PythonPackageAuthoringService:
    def __init__(
        self,
        *,
        templates_root: Path,
        examples_root: Path,
        instances_root: Path | Callable[[], Path],
        runtime_root: Path,
    ) -> None:
        self._templates_root = templates_root
        self._examples_root = examples_root
        self._instances_root_source = instances_root
        self._runtime_root = runtime_root

    @property
    def _instances_root(self) -> Path:
        value = (
            self._instances_root_source()
            if callable(self._instances_root_source)
            else self._instances_root_source
        )
        return Path(value).resolve()

    @staticmethod
    def supports(block_type: str) -> bool:
        return block_type in PACKAGE_COMPONENT_SPECS

    def _spec(self, block_type: str) -> PackageAdapterSpec:
        try:
            return PACKAGE_COMPONENT_SPECS[block_type]
        except KeyError as exc:
            raise PythonPackageAuthoringError(
                "python_package_component_unsupported",
                "The component type does not support a Python extension.",
            ) from exc

    def _template_root(self, spec: PackageAdapterSpec) -> Path:
        return self._templates_root.joinpath(*spec.template_parts)

    def _example_root(self, spec: PackageAdapterSpec) -> Path:
        return self._examples_root.joinpath(*spec.example_parts)

    def _adapter_root(self, spec: PackageAdapterSpec) -> Path:
        return self._instances_root / spec.directory

    def template_catalog(self, block_type: str) -> dict[str, object]:
        spec = self._spec(block_type)
        templates = scan_python_package_templates(
            self._template_root(spec),
            family=spec.family,  # type: ignore[arg-type]
            adapter=spec.adapter,  # type: ignore[arg-type]
            factory_name=spec.factory_name,
            factory_parameters=spec.factory_parameters,
        )
        examples = scan_python_package_templates(
            self._example_root(spec),
            family=spec.family,  # type: ignore[arg-type]
            adapter=spec.adapter,  # type: ignore[arg-type]
            factory_name=spec.factory_name,
            factory_parameters=spec.factory_parameters,
        )
        example_catalog = []
        for item in examples["catalog"]:
            assert isinstance(item, dict)
            key = str(item["key"])
            example_catalog.append(
                {
                    **item,
                    "key": f"{BUILTIN_EXAMPLE_TEMPLATE_PREFIX}{key}",
                    "name": f"{BUILTIN_EXAMPLE_TEMPLATE_PREFIX}{item['name']}",
                }
            )
        example_errors = {
            f"{BUILTIN_EXAMPLE_TEMPLATE_PREFIX}{key}": value
            for key, value in examples["errors"].items()
        }
        return {
            "catalog": [*templates["catalog"], *example_catalog],
            "errors": {**templates["errors"], **example_errors},
        }

    def _scan_instance(
        self,
        block_type: str,
        owner_id: str,
        folder: str,
    ) -> tuple[dict[str, object], Path]:
        spec = self._spec(block_type)
        try:
            resolved = resolve_python_package(
                folder,
                self._instances_root,
                owner_id=owner_id,
                family=spec.family,  # type: ignore[arg-type]
                adapter=spec.adapter,  # type: ignore[arg-type]
                adapter_directory=spec.directory,
                factory_name=spec.factory_name,
                factory_parameters=spec.factory_parameters,
                runtime_root=self._runtime_root,
            )
        except ResourceScanError as exc:
            raise PythonPackageAuthoringError(
                "python_package_invalid",
                "The configuration-owned Python extension is invalid.",
            ) from exc
        if resolved is None:
            raise PythonPackageAuthoringError(
                "python_package_not_found",
                "The Python extension directory is missing or is not owned by this configuration.",
                status_code=404,
            )
        return resolved

    def _inspect_instance(
        self,
        block_type: str,
        owner_id: str,
        folder_name: str,
    ) -> tuple[dict[str, object], Path]:
        spec = self._spec(block_type)
        folder = resolve_owned_python_package_folder(
            folder_name,
            self._instances_root,
            owner_id=owner_id,
            adapter=spec.adapter,  # type: ignore[arg-type]
            adapter_directory=spec.directory,
        )
        if folder is None:
            raise PythonPackageAuthoringError(
                "python_package_not_found",
                "The Python extension directory is missing or is not owned by this configuration.",
                status_code=404,
            )
        try:
            return (
                inspect_python_package_draft(
                    folder,
                    owner_id=owner_id,
                    family=spec.family,  # type: ignore[arg-type]
                    adapter=spec.adapter,  # type: ignore[arg-type]
                    factory_name=spec.factory_name,
                    factory_parameters=spec.factory_parameters,
                    runtime_root=self._runtime_root,
                ),
                folder,
            )
        except ResourceScanError as exc:
            raise PythonPackageAuthoringError(
                "python_package_read_failed",
                f"The configuration-owned Python extension could not be inspected ({exc.message_key}).",
            ) from exc

    def project(
        self,
        block_type: str,
        owner_id: str,
        reference: dict[str, Any],
        *,
        repository_id: str,
        repository_name: str,
    ) -> dict[str, object]:
        if not is_configuration_id(repository_id):
            raise PythonPackageAuthoringError(
                "python_package_repository_invalid",
                "The active configuration repository id is invalid.",
            )
        repository_name = normalize_configuration_name(
            repository_name,
            label="configuration repository name",
        )
        inspection, folder = self._inspect_instance(
            block_type, owner_id, str(reference.get("folder", ""))
        )
        spec = self._spec(block_type)
        metadata = inspection["metadata"]
        assert metadata is None or isinstance(metadata, dict)
        package_error = inspection["error"]
        error_code = (
            str(package_error.get("message_key", "python_package_invalid"))
            if isinstance(package_error, dict)
            else ""
        )
        files: list[dict[str, object]] = []
        pending = [folder]
        try:
            while pending:
                directory = pending.pop()
                with os.scandir(directory) as scanner:
                    entries = sorted(scanner, key=lambda item: item.name.casefold())
                child_directories: list[Path] = []
                for entry in entries:
                    path = Path(entry.path)
                    file_metadata = path.lstat()
                    if is_reparse_point(path):
                        raise OSError("Python package entries may not be reparse points")
                    if stat.S_ISDIR(file_metadata.st_mode):
                        child_directories.append(path)
                        continue
                    if not stat.S_ISREG(file_metadata.st_mode):
                        raise OSError("Python package entries must be regular files")
                    relative = path.relative_to(folder).as_posix()
                    files.append(
                        {
                            "path": relative,
                            "file_manager_path": (
                                f"data/config_repos/{repository_name}/python_packages/"
                                f"{spec.directory}/{folder.name}/{relative}"
                            ),
                            "size": file_metadata.st_size,
                            "modified_at": datetime.fromtimestamp(
                                file_metadata.st_mtime, timezone.utc
                            )
                            .isoformat()
                            .replace("+00:00", "Z"),
                        }
                    )
                pending.extend(reversed(child_directories))
        except OSError as exc:
            raise PythonPackageAuthoringError(
                "python_package_read_failed",
                "The configuration-owned Python extension could not be enumerated.",
            ) from exc
        files.sort(key=lambda item: str(item["path"]).casefold())
        return {
            "repository_id": repository_id,
            "owner_id": owner_id,
            "revision": inspection["revision"],
            "files": files,
            "python_package_manifest": inspection["manifest"],
            "python_package_error": package_error,
            "requirements_fingerprint": (
                metadata["requirements_fingerprint"] if metadata is not None else ""
            ),
            "dependency_status": (
                metadata["dependency_status"] if metadata is not None else "failed"
            ),
            "dependency_error_code": (
                metadata["dependency_error_code"] if metadata is not None else error_code
            ),
        }

    def create(
        self,
        block_type: str,
        owner_id: str,
        owner_name: str,
        *,
        template_key: str,
        template_revision: str,
    ) -> tuple[dict[str, str], StagedPathChange]:
        spec = self._spec(block_type)
        if template_key.startswith(BUILTIN_EXAMPLE_TEMPLATE_PREFIX):
            template_root = self._example_root(spec)
            folder_key = template_key.removeprefix(BUILTIN_EXAMPLE_TEMPLATE_PREFIX)
        else:
            template_root = self._template_root(spec)
            folder_key = template_key
        template = template_root / folder_key
        if not folder_key or template.parent != template_root:
            raise PythonPackageAuthoringError(
                "python_package_template_invalid",
                "The selected Python package template key must name one template folder.",
            )
        try:
            template_metadata = scan_python_package_template(
                template,
                family=spec.family,  # type: ignore[arg-type]
                adapter=spec.adapter,  # type: ignore[arg-type]
                factory_name=spec.factory_name,
                factory_parameters=spec.factory_parameters,
            )
        except ResourceScanError as exc:
            raise PythonPackageAuthoringError(
                "python_package_template_invalid",
                "The selected Python package template is invalid.",
            ) from exc
        if template_metadata["revision"] != template_revision:
            raise PythonPackageAuthoringError(
                "python_package_template_revision_conflict",
                "The Python package template changed after it was loaded.",
                status_code=409,
            )

        folder_name = normalize_configuration_name(
            owner_name,
            label="configuration name",
        )
        adapter_root = self._adapter_root(spec)
        adapter_root.mkdir(parents=True, exist_ok=True)
        staging_root = Path(tempfile.mkdtemp(prefix=".authoring-", dir=adapter_root))
        staged = staging_root / folder_name
        final = adapter_root / folder_name
        try:
            if os.path.lexists(final):
                raise PythonPackageAuthoringError(
                    "python_package_exists",
                    "A Python extension directory with this configuration name already exists.",
                    status_code=409,
                )
            shutil.copytree(template, staged, symlinks=True)
            manifest = PythonPackageManifest.model_validate(
                {
                    "format_version": 1,
                    "id": owner_id,
                    "family": spec.family,
                    "adapter": spec.adapter,
                }
            )
            write_bytes_atomic(
                staged / "package.json",
                (
                    json.dumps(
                        manifest.model_dump(mode="json"),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                ).encode("utf-8"),
            )
            scan_python_package(
                staged,
                owner_id=owner_id,
                family=spec.family,  # type: ignore[arg-type]
                adapter=spec.adapter,  # type: ignore[arg-type]
                factory_name=spec.factory_name,
                factory_parameters=spec.factory_parameters,
                runtime_root=self._runtime_root,
            )
            os.replace(staged, final)
        except ResourceScanError as exc:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise PythonPackageAuthoringError(
                "python_package_invalid",
                "The Python extension does not satisfy its adapter contract.",
            ) from exc
        except BaseException:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise
        shutil.rmtree(staging_root, ignore_errors=True)
        return (
            {"folder": folder_name},
            StagedPathChange(lambda: shutil.rmtree(final, ignore_errors=True)),
        )

    def copy(
        self,
        block_type: str,
        source_owner_id: str,
        target_owner_id: str,
        target_owner_name: str,
        reference: dict[str, Any],
    ) -> tuple[dict[str, str], StagedPathChange]:
        _metadata, source = self._scan_instance(
            block_type, source_owner_id, str(reference.get("folder", ""))
        )
        spec = self._spec(block_type)
        folder_name = normalize_configuration_name(
            target_owner_name,
            label="configuration name",
        )
        final = self._adapter_root(spec) / folder_name
        staging_root = Path(
            tempfile.mkdtemp(prefix=".authoring-", dir=self._adapter_root(spec))
        )
        staged = staging_root / folder_name
        try:
            if os.path.lexists(final):
                raise PythonPackageAuthoringError(
                    "python_package_exists",
                    "A Python extension directory with this configuration name already exists.",
                    status_code=409,
                )
            shutil.copytree(source, staged, symlinks=True)
            manifest_path = staged / "package.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["id"] = target_owner_id
            write_bytes_atomic(
                manifest_path,
                (
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
                ).encode("utf-8"),
            )
            scan_python_package(
                staged,
                owner_id=target_owner_id,
                family=spec.family,  # type: ignore[arg-type]
                adapter=spec.adapter,  # type: ignore[arg-type]
                factory_name=spec.factory_name,
                factory_parameters=spec.factory_parameters,
                runtime_root=self._runtime_root,
            )
            os.replace(staged, final)
        except ResourceScanError as exc:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise PythonPackageAuthoringError(
                "python_package_invalid",
                "The copied Python package does not satisfy its adapter contract.",
            ) from exc
        except BaseException:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise
        shutil.rmtree(staging_root, ignore_errors=True)
        return (
            {"folder": folder_name},
            StagedPathChange(lambda: shutil.rmtree(final, ignore_errors=True)),
        )

    def stage_delete(
        self,
        block_type: str,
        owner_id: str,
        reference: dict[str, Any],
    ) -> StagedPathChange:
        spec = self._spec(block_type)
        folder_name = str(reference.get("folder", ""))
        folder = resolve_owned_python_package_folder(
            folder_name,
            self._instances_root,
            owner_id=owner_id,
            adapter=spec.adapter,  # type: ignore[arg-type]
            adapter_directory=spec.directory,
        )
        if folder is None:
            logger.warning(
                "Skipping Python extension cleanup: code=python_package_not_found owner_id=%s folder=%s",
                owner_id,
                folder_name,
            )
            return StagedPathChange(lambda: None)
        try:
            inspect_python_package_draft(
                folder,
                owner_id=owner_id,
                family=spec.family,  # type: ignore[arg-type]
                adapter=spec.adapter,  # type: ignore[arg-type]
                factory_name=spec.factory_name,
                factory_parameters=spec.factory_parameters,
                runtime_root=self._runtime_root,
            )
        except ResourceScanError as exc:
            logger.warning(
                "Skipping unsafe Python extension cleanup: code=%s owner_id=%s folder=%s",
                exc.message_key,
                owner_id,
                folder_name,
            )
            return StagedPathChange(lambda: None)
        tombstone_root = folder.parent / f".deleted-{uuid4()}"
        tombstone_root.mkdir(parents=True)
        tombstone = tombstone_root / folder.name
        os.replace(folder, tombstone)

        def rollback() -> None:
            folder.parent.mkdir(parents=True, exist_ok=True)
            if tombstone.exists():
                os.replace(tombstone, folder)
            shutil.rmtree(tombstone_root, ignore_errors=True)

        def finalize() -> None:
            shutil.rmtree(tombstone_root, ignore_errors=True)

        return StagedPathChange(rollback, finalize)

    def stage_rename(
        self,
        block_type: str,
        owner_id: str,
        reference: dict[str, Any],
        owner_name: str,
    ) -> tuple[dict[str, str], StagedPathChange]:
        spec = self._spec(block_type)
        source = resolve_owned_python_package_folder(
            str(reference.get("folder", "")),
            self._instances_root,
            owner_id=owner_id,
            adapter=spec.adapter,  # type: ignore[arg-type]
            adapter_directory=spec.directory,
        )
        if source is None:
            raise PythonPackageAuthoringError(
                "python_package_not_found",
                "The Python extension directory is missing or is not owned by this configuration.",
                status_code=404,
            )
        folder_name = normalize_configuration_name(
            owner_name,
            label="configuration name",
        )
        target = source.parent / folder_name
        if source.name == folder_name:
            return {"folder": folder_name}, StagedPathChange(lambda: None)
        if target != source and os.path.lexists(target):
            raise PythonPackageAuthoringError(
                "python_package_exists",
                "A Python extension directory with this configuration name already exists.",
                status_code=409,
            )
        os.replace(source, target)

        def rollback() -> None:
            if target.exists():
                os.replace(target, source)

        return {"folder": folder_name}, StagedPathChange(rollback)


__all__ = [
    "BUILTIN_EXAMPLE_TEMPLATE_PREFIX",
    "PACKAGE_COMPONENT_SPECS",
    "PackageAdapterDirectory",
    "PythonPackageAuthoringError",
    "PythonPackageAuthoringService",
]
