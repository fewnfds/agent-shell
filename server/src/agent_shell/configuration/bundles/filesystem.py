from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from agent_shell.configuration.bundles.contracts import FilesystemBindingResolution
from agent_shell.configuration.bundles.errors import bundle_issue
from agent_shell.storage.owned_paths import (
    OwnedPathError,
    resolve_configured_local_path,
)


BindingKind = Literal[
    "mapped-directory",
    "local-shell-workspace",
    "virtual-directory",
    "virtual-file",
]


@dataclass(frozen=True, slots=True)
class FilesystemBinding:
    binding_id: str
    source_id: str
    configuration_name: str
    path: str
    kind: BindingKind
    source_value: str
    source_path_origin: str
    location: tuple[str | int, ...]
    required: bool

    def as_dict(self, data_root: Path) -> dict[str, object]:
        if self.source_path_origin == "data-root-relative":
            try:
                target = resolve_configured_local_path(
                    data_root,
                    self.source_value,
                    path_origin=self.source_path_origin,
                    label="filesystem binding",
                )
            except OwnedPathError:
                exists = False
            else:
                exists = (
                    target.is_file()
                    if self.kind == "virtual-file"
                    else target.is_dir()
                )
            status = "ready" if exists else "target-missing"
            target_value: str | None = self.source_value
        else:
            status = "binding-required"
            target_value = None
        return {
            "binding_id": self.binding_id,
            "source_id": self.source_id,
            "configuration_name": self.configuration_name,
            "path": self.path,
            "kind": self.kind,
            "source_value": self.source_value,
            "source_path_origin": self.source_path_origin,
            "required": self.required,
            "status": status,
            "target_value": target_value,
        }


def _records(value: object) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []


def collect_filesystem_bindings(
    records: dict[str, tuple[str, str, dict[str, Any]]],
) -> tuple[FilesystemBinding, ...]:
    bindings: list[FilesystemBinding] = []
    for source_id, (component_type, name, payload) in sorted(records.items()):
        if component_type != "filesystem":
            continue
        if payload.get("backend_type", "composite") == "local-shell":
            workspace = payload.get("workspace")
            if isinstance(workspace, dict):
                value = str(workspace.get("local_path", ""))
                origin = str(workspace.get("path_origin", "absolute"))
                path = "workspace.local_path"
                bindings.append(
                    FilesystemBinding(
                        binding_id=f"{source_id}:{path}",
                        source_id=source_id,
                        configuration_name=name,
                        path=path,
                        kind="local-shell-workspace",
                        source_value=value,
                        source_path_origin=origin,
                        location=("workspace", "local_path"),
                        required=origin == "absolute",
                    )
                )
            continue
        for index, item in enumerate(_records(payload.get("mapped_directories"))):
            value = str(item.get("local_path", ""))
            origin = str(item.get("path_origin", "absolute"))
            path = f"mapped_directories[{index}].local_path"
            bindings.append(
                FilesystemBinding(
                    binding_id=f"{source_id}:{path}",
                    source_id=source_id,
                    configuration_name=name,
                    path=path,
                    kind="mapped-directory",
                    source_value=value,
                    source_path_origin=origin,
                    location=("mapped_directories", index, "local_path"),
                    required=origin == "absolute",
                )
            )
        for field, kind in (
            ("virtual_directories", "virtual-directory"),
            ("virtual_files", "virtual-file"),
        ):
            for index, item in enumerate(_records(payload.get(field))):
                value = str(item.get("source_path", ""))
                origin = str(item.get("path_origin", "absolute"))
                path = f"{field}[{index}].source_path"
                bindings.append(
                    FilesystemBinding(
                        binding_id=f"{source_id}:{path}",
                        source_id=source_id,
                        configuration_name=name,
                        path=path,
                        kind=kind,  # type: ignore[arg-type]
                        source_value=value,
                        source_path_origin=origin,
                        location=(field, index, "source_path"),
                        required=origin == "absolute",
                    )
                )
    return tuple(bindings)


def _set_value(payload: dict[str, Any], location: tuple[str | int, ...], value: str) -> None:
    current: Any = payload
    for segment in location[:-1]:
        current = current[segment]
    current[location[-1]] = value


def apply_filesystem_bindings(
    payloads: dict[str, dict[str, Any]],
    bindings: tuple[FilesystemBinding, ...],
    resolutions: dict[str, FilesystemBindingResolution],
    *,
    data_root: Path,
    require_resolved: bool,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, object]]]:
    known = {binding.binding_id for binding in bindings}
    unknown = set(resolutions).difference(known)
    if unknown:
        raise ValueError("filesystem resolutions contain unknown binding ids")
    output = deepcopy(payloads)
    errors: list[dict[str, object]] = []
    for binding in bindings:
        resolution = resolutions.get(binding.binding_id)
        if resolution is None:
            if binding.required and require_resolved:
                errors.append(
                    bundle_issue(
                        "filesystem_binding_required",
                        "A target filesystem path must be selected.",
                        source_id=binding.source_id,
                        path=binding.path,
                    )
                )
            continue
        try:
            resolved_target = resolve_configured_local_path(
                data_root,
                resolution.value,
                path_origin=resolution.path_origin,
                label="filesystem binding",
            )
        except OwnedPathError:
            valid = False
        else:
            if resolution.path_origin == "data-root-relative":
                valid = True
            elif binding.kind == "virtual-file":
                valid = resolved_target.is_file()
            else:
                valid = resolved_target.is_dir()
        if not valid:
            issue_code = (
                "filesystem_directory_invalid"
                if binding.kind in {"mapped-directory", "local-shell-workspace"}
                else "filesystem_source_invalid"
            )
            errors.append(
                bundle_issue(
                    issue_code,
                    "The target filesystem binding is invalid.",
                    source_id=binding.source_id,
                    path=binding.path,
                )
            )
            continue
        parent: Any = output[binding.source_id]
        for segment in binding.location[:-1]:
            parent = parent[segment]
        parent["path_origin"] = resolution.path_origin
        _set_value(output[binding.source_id], binding.location, resolution.value)
    return output, errors


def apply_validation_placeholders(
    payloads: dict[str, dict[str, Any]],
    bindings: tuple[FilesystemBinding, ...],
    folder: Path,
) -> dict[str, dict[str, Any]]:
    output = deepcopy(payloads)
    for index, binding in enumerate(bindings):
        if not binding.required:
            continue
        target = folder / str(index)
        if binding.kind == "virtual-file":
            payload = output[binding.source_id]
            field = binding.location[0]
            item_index = binding.location[1]
            virtual_path = payload[field][item_index]["virtual_path"]
            target.mkdir(parents=True, exist_ok=True)
            target = target / Path(str(virtual_path)).name
            target.write_bytes(b"")
        else:
            target.mkdir(parents=True, exist_ok=True)
        _set_value(output[binding.source_id], binding.location, str(target.resolve()))
        parent: Any = output[binding.source_id]
        for segment in binding.location[:-1]:
            parent = parent[segment]
        parent["path_origin"] = "absolute"
    return output


__all__ = [
    "FilesystemBinding",
    "apply_filesystem_bindings",
    "apply_validation_placeholders",
    "collect_filesystem_bindings",
]
