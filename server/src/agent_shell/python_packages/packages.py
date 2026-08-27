from __future__ import annotations

import ast
from hashlib import sha256
import json
from pathlib import Path
import re
import stat
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from agent_shell.python_packages.contracts import (
    PACKAGE_ID_PATTERN,
    parse_package_folder,
)
from agent_shell.python_packages.dependencies import (
    dependency_metadata,
    read_package_requirements,
)
from agent_shell.registries.errors import ResourceScanError


PythonPackageFamily = Literal["workflow-node", "middleware", "event-output", "tool"]
PythonPackageAdapter = Literal[
    "command",
    "task-dispatcher",
    "agent-middleware",
    "agent-event-output",
    "workflow-event-output",
    "agent-tool",
]
_TEMPLATE_KEY = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")


class _ManifestBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    format_version: Literal[1]
    family: PythonPackageFamily
    adapter: PythonPackageAdapter
    @model_validator(mode="after")
    def validate_adapter_family(self) -> "_ManifestBase":
        expected = {
            "command": "workflow-node",
            "task-dispatcher": "workflow-node",
            "agent-middleware": "middleware",
            "agent-event-output": "event-output",
            "workflow-event-output": "event-output",
            "agent-tool": "tool",
        }[self.adapter]
        if self.family != expected:
            raise ValueError("adapter does not belong to the declared family")
        return self


class PythonPackageManifest(_ManifestBase):
    id: str = Field(min_length=36, max_length=36, pattern=PACKAGE_ID_PATTERN)


def _is_link(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _read_bytes(path: Path, *, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ResourceScanError(
            "resource.error.pythonPackage.readFailed",
            f"{label} could not be read.",
        ) from exc


def _read_text(path: Path, *, label: str) -> str:
    try:
        return _read_bytes(path, label=label).decode("utf-8")
    except UnicodeError as exc:
        raise ResourceScanError(
            "resource.error.pythonPackage.invalidEncoding",
            f"{label} must use UTF-8 encoding.",
        ) from exc


def _inspect_folder(folder: Path) -> tuple[Path, ...]:
    if _is_link(folder):
        raise ResourceScanError(
            "resource.error.pythonPackage.linkUnsupported",
            "Python package folders may not be links or reparse points.",
        )
    try:
        entries = tuple(folder.rglob("*"))
    except OSError as exc:
        raise ResourceScanError(
            "resource.error.pythonPackage.readFailed",
            "The Python package directory could not be read.",
        ) from exc
    if any(_is_link(path) for path in entries):
        raise ResourceScanError(
            "resource.error.pythonPackage.linkUnsupported",
            "Python package contents may not be links or reparse points.",
        )
    return entries


def _is_python_runtime_artifact(folder: Path, path: Path) -> bool:
    relative = path.relative_to(folder)
    return "__pycache__" in relative.parts or path.suffix.casefold() == ".pyc"


def _directory_revision(folder: Path, entries: tuple[Path, ...]) -> str:
    digest = sha256()
    for path in sorted(
        (
            entry
            for entry in entries
            if entry.is_file()
            and not _is_python_runtime_artifact(folder, entry)
        ),
        key=lambda value: value.relative_to(folder).as_posix(),
    ):
        relative = path.relative_to(folder).as_posix().encode("utf-8")
        content = _read_bytes(path, label=path.name)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _read_manifest(
    path: Path,
    *,
    label: str,
    model: type[PythonPackageManifest],
) -> PythonPackageManifest:
    try:
        raw_manifest = json.loads(_read_text(path, label=label))
    except json.JSONDecodeError as exc:
        raise ResourceScanError(
            "resource.error.pythonPackage.manifestInvalid",
            f"{label} must contain a valid JSON object.",
        ) from exc
    try:
        return model.model_validate(raw_manifest)
    except ValidationError as exc:
        raise ResourceScanError(
            "resource.error.pythonPackage.manifestInvalid",
            f"{label} does not satisfy the current manifest contract.",
        ) from exc


def _parse_main(folder: Path) -> tuple[str, ast.Module]:
    main_path = folder / "main.py"
    source = _read_text(main_path, label="main.py")
    try:
        return source, ast.parse(source, filename=str(main_path))
    except SyntaxError as exc:
        raise ResourceScanError(
            "resource.error.pythonPackage.syntax",
            f"main.py contains a syntax error on line {exc.lineno or 1}.",
            {"line": exc.lineno or 1},
        ) from exc


def _required_files(folder: Path) -> None:
    if not (folder / "package.json").is_file() or not (folder / "main.py").is_file():
        raise ResourceScanError(
            "resource.error.pythonPackage.filesRequired",
            "The folder must contain package.json and main.py.",
        )


def _validate_factory(
    tree: ast.Module,
    *,
    name: str,
    parameters: tuple[str, ...] | None,
) -> None:
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    signature = ", ".join(parameters or ())
    if len(functions) != 1 or isinstance(functions[0], ast.AsyncFunctionDef):
        raise ResourceScanError(
            "resource.error.pythonPackage.entrypointRequired",
            f"main.py must define exactly one module-level def {name}({signature}).",
        )
    function = functions[0]
    if parameters is None:
        return
    positional = [*function.args.posonlyargs, *function.args.args]
    if (
        [argument.arg for argument in positional] != list(parameters)
        or function.args.vararg is not None
        or function.args.kwarg is not None
        or function.args.kwonlyargs
        or function.args.defaults
    ):
        raise ResourceScanError(
            "resource.error.pythonPackage.entrypointSignatureInvalid",
            f"The {name} entrypoint must accept exactly: {signature}.",
        )


def scan_python_package_template(
    folder: Path,
    *,
    family: PythonPackageFamily,
    adapter: PythonPackageAdapter,
    factory_name: str,
    factory_parameters: tuple[str, ...] | None,
) -> dict[str, object]:
    if not _TEMPLATE_KEY.fullmatch(folder.name):
        raise ResourceScanError(
            "resource.error.pythonPackage.templateNameInvalid",
            "Python package template folder names must use lowercase letters, digits, underscores, or hyphens.",
        )
    entries = _inspect_folder(folder)
    if not (folder / "main.py").is_file():
        raise ResourceScanError(
            "resource.error.pythonPackage.templateMainRequired",
            "The template folder must contain main.py.",
        )
    _source, tree = _parse_main(folder)
    _validate_factory(tree, name=factory_name, parameters=factory_parameters)
    requirements = read_package_requirements(folder)
    text_files: list[dict[str, object]] = []
    for path in sorted(
        (
            entry
            for entry in entries
            if entry.is_file()
            and not _is_python_runtime_artifact(folder, entry)
        ),
        key=lambda value: value.relative_to(folder).as_posix(),
    ):
        try:
            content = _read_text(path, label=path.name)
        except ResourceScanError as exc:
            if exc.message_key == "resource.error.pythonPackage.invalidEncoding":
                continue
            raise
        text_files.append(
            {
                "path": path.relative_to(folder).as_posix(),
                "content": content.replace("\r\n", "\n").replace("\r", "\n"),
                "exists": True,
            }
        )
    return {
        "format_version": 1,
        "key": folder.name,
        "folder": folder.name,
        "family": family,
        "adapter": adapter,
        "name": folder.name,
        "files": text_files,
        "python_requirements": list(requirements.values),
        "revision": _directory_revision(folder, entries),
    }


def scan_python_package_templates(
    directory: Path,
    *,
    family: PythonPackageFamily,
    adapter: PythonPackageAdapter,
    factory_name: str,
    factory_parameters: tuple[str, ...] | None,
) -> dict[str, object]:
    catalog: list[dict[str, object]] = []
    errors: dict[str, dict[str, object]] = {}
    if not directory.exists():
        return {"catalog": catalog, "errors": errors}
    for folder in sorted(directory.iterdir(), key=lambda path: path.name.casefold()):
        if not folder.is_dir():
            continue
        try:
            catalog.append(
                scan_python_package_template(
                    folder,
                    family=family,
                    adapter=adapter,
                    factory_name=factory_name,
                    factory_parameters=factory_parameters,
                )
            )
        except ResourceScanError as exc:
            errors[folder.name] = exc.as_dict()
    return {"catalog": catalog, "errors": errors}


def scan_python_package(
    folder: Path,
    *,
    owner_id: str,
    family: PythonPackageFamily,
    adapter: PythonPackageAdapter,
    factory_name: str,
    factory_parameters: tuple[str, ...] | None,
    runtime_root: Path | None = None,
) -> dict[str, object]:
    parsed = parse_package_folder(folder.name)
    if parsed is None:
        raise ResourceScanError(
            "resource.error.pythonPackage.ownerMismatch",
            "The Python package folder name is invalid.",
        )
    entries = _inspect_folder(folder)
    _required_files(folder)
    manifest = _read_manifest(
        folder / "package.json",
        label="package.json",
        model=PythonPackageManifest,
    )
    assert isinstance(manifest, PythonPackageManifest)
    if manifest.id != owner_id:
        raise ResourceScanError(
            "resource.error.pythonPackage.idMismatch",
            "The manifest id must match the owner configuration UUID.",
            {"declared_id": manifest.id},
        )
    if manifest.family != family or manifest.adapter != adapter:
        raise ResourceScanError(
            "resource.error.pythonPackage.typeMismatch",
            "The Python package does not implement the expected adapter.",
            {"expected_family": family, "expected_adapter": adapter},
        )
    _source, tree = _parse_main(folder)
    _validate_factory(tree, name=factory_name, parameters=factory_parameters)
    requirements = read_package_requirements(folder)
    return {
        **manifest.model_dump(mode="json", by_alias=True, exclude_none=True),
        "folder": folder.name,
        "revision": _directory_revision(folder, entries),
        **dependency_metadata(
            f"python-package:{manifest.id}", requirements, runtime_root
        ),
    }


def resolve_owned_python_package_folder(
    folder_name: str,
    directory: Path,
    *,
    owner_id: str,
    adapter: PythonPackageAdapter,
    adapter_directory: str | None = None,
) -> Path | None:
    parsed = parse_package_folder(folder_name)
    if parsed is None:
        return None
    folder = directory / (adapter_directory or adapter.replace("-", "_")) / parsed
    if not folder.is_dir() or _is_link(folder):
        return None
    return folder


def inspect_python_package_draft(
    folder: Path,
    *,
    owner_id: str,
    family: PythonPackageFamily,
    adapter: PythonPackageAdapter,
    factory_name: str,
    factory_parameters: tuple[str, ...] | None,
    runtime_root: Path | None = None,
) -> dict[str, object]:
    parsed = parse_package_folder(folder.name)
    if parsed is None:
        raise ResourceScanError(
            "resource.error.pythonPackage.ownerMismatch",
            "The Python package folder name is invalid.",
        )
    entries = _inspect_folder(folder)
    revision = _directory_revision(folder, entries)
    error: ResourceScanError | None = None
    metadata: dict[str, object] | None = None
    try:
        metadata = scan_python_package(
            folder,
            owner_id=owner_id,
            family=family,
            adapter=adapter,
            factory_name=factory_name,
            factory_parameters=factory_parameters,
            runtime_root=runtime_root,
        )
    except ResourceScanError as exc:
        error = exc

    manifest: dict[str, object] | None = None
    try:
        if not (folder / "package.json").is_file():
            raise ResourceScanError(
                "resource.error.pythonPackage.filesRequired",
                "The folder must contain package.json and main.py.",
            )
        parsed_manifest = _read_manifest(
            folder / "package.json",
            label="package.json",
            model=PythonPackageManifest,
        )
        assert isinstance(parsed_manifest, PythonPackageManifest)
        if parsed_manifest.id != owner_id:
            raise ResourceScanError(
                "resource.error.pythonPackage.idMismatch",
                "The manifest id must match the owner configuration UUID.",
                {"declared_id": parsed_manifest.id},
            )
        if parsed_manifest.family != family or parsed_manifest.adapter != adapter:
            raise ResourceScanError(
                "resource.error.pythonPackage.typeMismatch",
                "The Python package does not implement the expected adapter.",
                {"expected_family": family, "expected_adapter": adapter},
            )
        manifest = {
            **parsed_manifest.model_dump(mode="json", by_alias=True, exclude_none=True),
            "folder": folder.name,
        }
    except ResourceScanError as exc:
        if error is None:
            error = exc

    return {
        "manifest": manifest,
        "metadata": metadata,
        "revision": revision,
        "error": error.as_dict() if error is not None else None,
    }


def resolve_python_package(
    folder_name: str,
    directory: Path,
    *,
    owner_id: str,
    family: PythonPackageFamily,
    adapter: PythonPackageAdapter,
    adapter_directory: str | None = None,
    factory_name: str,
    factory_parameters: tuple[str, ...] | None,
    runtime_root: Path | None = None,
) -> tuple[dict[str, object], Path] | None:
    folder = resolve_owned_python_package_folder(
        folder_name,
        directory,
        owner_id=owner_id,
        adapter=adapter,
        adapter_directory=adapter_directory,
    )
    if folder is None:
        return None
    return (
        scan_python_package(
            folder,
            owner_id=owner_id,
            family=family,
            adapter=adapter,
            factory_name=factory_name,
            factory_parameters=factory_parameters,
            runtime_root=runtime_root,
        ),
        folder,
    )


__all__ = [
    "PythonPackageAdapter",
    "PythonPackageFamily",
    "PythonPackageManifest",
    "inspect_python_package_draft",
    "resolve_python_package",
    "resolve_owned_python_package_folder",
    "scan_python_package",
    "scan_python_package_template",
    "scan_python_package_templates",
]
