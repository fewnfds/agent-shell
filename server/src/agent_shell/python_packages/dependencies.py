from __future__ import annotations

import argparse
from hashlib import sha256
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Literal
from uuid import uuid4

from packaging.utils import canonicalize_name

from agent_shell.configuration.identity import is_configuration_id
from agent_shell.python_requirements import (
    PythonRequirements as PackageRequirements,
    PythonRequirementsError,
    parse_python_requirements,
)
from agent_shell.registries.errors import ResourceScanError
from agent_shell.runtime.windows_toolchains import ensure_uv


DEPENDENCY_STATE_SCHEMA = 1
PYPI_INDEX = "https://pypi.org/simple"
REQUIREMENTS_FILE = "requirements.txt"
RUNTIME_FOLDER = "python_packages"
SITE_PACKAGES_FOLDER = "site-packages"
STATE_FILE = "dependency-state.json"

DependencyStatus = Literal["ready", "restart_required", "failed"]


def _is_link(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & reparse_flag)


def read_package_requirements(folder: Path) -> PackageRequirements:
    path = folder / REQUIREMENTS_FILE
    if not path.exists():
        return parse_python_requirements(())
    if not path.is_file() or _is_link(path):
        raise ResourceScanError(
            "resource.error.pythonPackage.requirementsLinkUnsupported",
            "requirements.txt must be an ordinary file.",
        )
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ResourceScanError(
            "resource.error.pythonPackage.requirementsReadFailed",
            "requirements.txt could not be read.",
        ) from exc
    try:
        text = content.decode("utf-8")
    except UnicodeError as exc:
        raise ResourceScanError(
            "resource.error.pythonPackage.requirementsInvalidEncoding",
            "requirements.txt must use UTF-8 encoding.",
        ) from exc

    try:
        return parse_python_requirements(text.splitlines())
    except PythonRequirementsError as exc:
        key = {
            "duplicate": "requirementsDuplicate",
        }.get(exc.code, "requirementsInvalid")
        details = {"line": exc.line} if exc.line else {}
        if exc.package:
            details["package"] = exc.package
        raise ResourceScanError(
            f"resource.error.pythonPackage.{key}",
            str(exc),
            details,
        ) from exc


def package_runtime_root(runtime_root: Path) -> Path:
    return runtime_root / RUNTIME_FOLDER


def dependency_state_path(runtime_root: Path) -> Path:
    return package_runtime_root(runtime_root) / STATE_FILE


def package_site_packages(runtime_root: Path) -> Path:
    return package_runtime_root(runtime_root) / SITE_PACKAGES_FOLDER


def load_dependency_state(runtime_root: Path | None) -> dict[str, Any] | None:
    if runtime_root is None:
        return None
    path = dependency_state_path(runtime_root)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or value.get("schema") != DEPENDENCY_STATE_SCHEMA
        or value.get("status") not in {"ready", "failed"}
        or not isinstance(value.get("records"), dict)
    ):
        return None
    return value


def dependency_metadata(
    script_id: str,
    requirements: PackageRequirements,
    runtime_root: Path | None,
) -> dict[str, object]:
    if not requirements.values:
        status: DependencyStatus = "ready"
        error_code = ""
    else:
        state = load_dependency_state(runtime_root)
        package_state = (
            state.get("records", {}).get(script_id)
            if state is not None
            else None
        )
        if (
            isinstance(package_state, dict)
            and package_state.get("requirements_fingerprint")
            == requirements.fingerprint
            and package_state.get("status") in {"ready", "failed"}
        ):
            status = package_state["status"]
            error_code = str(package_state.get("error_code", ""))
        else:
            status = "restart_required"
            error_code = ""
    return {
        "python_requirements": list(requirements.values),
        "requirements_fingerprint": requirements.fingerprint,
        "dependency_status": status,
        "dependency_error_code": error_code,
    }


def repository_restart_required(
    packages_root: Path,
    runtime_root: Path,
) -> bool:
    if not packages_root.exists():
        return False
    for adapter in packages_root.iterdir():
        if not adapter.is_dir():
            continue
        for folder in adapter.iterdir():
            if not folder.is_dir():
                continue
            try:
                requirements = read_package_requirements(folder)
                manifest = json.loads(
                    (folder / "package.json").read_text(encoding="utf-8")
                )
                package_id = manifest.get("id") if isinstance(manifest, dict) else None
                if not is_configuration_id(package_id):
                    continue
            except (OSError, UnicodeError, json.JSONDecodeError, ResourceScanError):
                continue
            metadata = dependency_metadata(
                f"python-package:{package_id}",
                requirements,
                runtime_root,
            )
            if metadata["dependency_status"] == "restart_required":
                return True
    return False


def activate_package_site(runtime_root: Path) -> None:
    state = load_dependency_state(runtime_root)
    site_packages = package_site_packages(runtime_root)
    if state is None or state.get("status") != "ready" or not site_packages.is_dir():
        return
    site_text = str(site_packages.resolve())
    if site_text not in sys.path:
        # Core site-packages stays first so packages cannot shadow locked core modules.
        sys.path.append(site_text)


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=True, separators=(",", ":"))
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _runtime_manifest(runtime_root: Path) -> dict[str, Any]:
    path = runtime_root / "app" / "runtime-manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("The Windows runtime manifest is invalid.")
    return value


def _input_fingerprint(
    core_fingerprint: str,
    records: list[dict[str, object]],
) -> str:
    payload = {
        "core": core_fingerprint,
        "records": [
            [item["id"], item["requirements_fingerprint"]]
            for item in sorted(records, key=lambda value: str(value["id"]))
            if item["python_requirements"]
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _record_states(
    records: list[dict[str, object]],
    *,
    status: Literal["ready", "failed"],
    error_code: str = "",
) -> dict[str, dict[str, str]]:
    return {
        str(item["id"]): {
            "requirements_fingerprint": str(item["requirements_fingerprint"]),
            "status": status,
            "error_code": error_code,
        }
        for item in records
        if item["python_requirements"]
    }


def _write_failure_state(
    runtime_root: Path,
    records: list[dict[str, object]],
    *,
    input_fingerprint: str,
    core_fingerprint: str,
    error_code: str,
) -> None:
    _atomic_write_json(
        dependency_state_path(runtime_root),
        {
            "schema": DEPENDENCY_STATE_SCHEMA,
            "platform": "windows-x64",
            "status": "failed",
            "input_fingerprint": input_fingerprint,
            "core_fingerprint": core_fingerprint,
            "records": _record_states(
                records, status="failed", error_code=error_code
            ),
        },
    )


def _core_constraints() -> tuple[str, ...]:
    values: dict[str, str] = {}
    for distribution in distributions():
        name = distribution.metadata.get("Name")
        if not name or not distribution.version:
            continue
        values[canonicalize_name(name)] = f"{name}=={distribution.version}"
    return tuple(values[name] for name in sorted(values))


def _replace_site_packages(runtime_root: Path, prepared: Path) -> None:
    target = package_site_packages(runtime_root)
    previous = target.parent / f"site-packages.previous.{uuid4().hex}"
    target.parent.mkdir(parents=True, exist_ok=True)
    had_target = target.is_dir()
    if had_target:
        os.replace(target, previous)
    try:
        os.replace(prepared, target)
    except BaseException:
        if had_target and not target.exists():
            os.replace(previous, target)
        raise
    if previous.exists():
        shutil.rmtree(previous)


def _package_layout_is_supported(site_packages: Path) -> bool:
    for path in site_packages.rglob("*"):
        if _is_link(path):
            return False
    return not any(site_packages.glob("*.pth"))


def prepare_windows_dependencies(
    *,
    data_root: Path,
    runtime_root: Path,
) -> None:
    from agent_shell.command_packages import resolve_command_package
    from agent_shell.event_output_packages import (
        resolve_agent_event_output_package,
        resolve_workflow_event_output_package,
    )
    from agent_shell.middleware_packages.packages import resolve_middleware_package
    from agent_shell.tool_packages import resolve_tool_package
    from agent_shell.configuration.bundles.journal import recover_configuration_imports
    from agent_shell.storage.file_config import FileConfigRepository

    manifest = _runtime_manifest(runtime_root)
    core_fingerprint = str(manifest.get("build_fingerprint", ""))
    if not core_fingerprint:
        raise ValueError("The Windows runtime manifest lacks its build fingerprint.")
    recover_configuration_imports(data_root)
    repository = FileConfigRepository(data_root)
    packages_dir = repository.python_packages_root
    config = repository.config()
    components = config.get("components", {})

    active_command_ids: set[str] = set()
    active_workflow_event_output_ids: set[str] = set()
    for workflow in config.get("workflows", []):
        if not isinstance(workflow, dict) or workflow.get("enabled") is not True:
            continue
        workflow_event_output_id = workflow.get("workflow_event_output_id")
        if isinstance(workflow_event_output_id, str) and workflow_event_output_id:
            active_workflow_event_output_ids.add(workflow_event_output_id)
        definition = workflow.get("definition", {})
        for node in definition.get("nodes", []) if isinstance(definition, dict) else []:
            if not isinstance(node, dict):
                continue
            node_config = node.get("config", {})
            if not isinstance(node_config, dict):
                continue
            if node.get("type") == "command":
                active_command_ids.add(
                    str(node_config.get("command_id", ""))
                )
    active_command_ids.discard("")

    main_agents = {
        str(item.get("id", "")): item
        for item in config.get("main_agents", [])
        if isinstance(item, dict)
    }
    # Main Agents are independent root graphs and may be selected directly or
    # dynamically by a Command, so startup prepares every configured profile.
    active_main_agent_ids = set(main_agents)
    subagents = {
        str(item.get("id", "")): item
        for item in config.get("subagents", [])
        if isinstance(item, dict)
    }

    def referenced_ids(component_type: str) -> set[str]:
        if component_type == "command":
            return set(active_command_ids)
        if component_type == "workflow-event-output":
            return set(active_workflow_event_output_ids)
        found: set[str] = set()
        active_subagent_ids: set[str] = set()
        for main_agent_id in active_main_agent_ids:
            agent = main_agents.get(main_agent_id)
            if agent is None:
                continue
            for reference in agent.get("capability_refs", []):
                if isinstance(reference, dict) and reference.get("type") == component_type:
                    found.add(str(reference.get("block_id", "")))
            if component_type == "custom-tool":
                for reference in agent.get("tool_refs", []):
                    if isinstance(reference, dict):
                        found.add(str(reference.get("tool_id", "")))
            if component_type == "custom-middleware":
                for reference in agent.get("middleware_refs", []):
                    if isinstance(reference, dict):
                        found.add(str(reference.get("middleware_id", "")))
            for reference in agent.get("subagents", []):
                if isinstance(reference, dict):
                    active_subagent_ids.add(str(reference.get("subagent_id", "")))
        for subagent_id in active_subagent_ids:
            profile = subagents.get(subagent_id)
            settings = profile.get("settings") if profile is not None else None
            overrides = (
                settings.get("capability_overrides", [])
                if isinstance(settings, dict)
                else []
            )
            for override in overrides:
                if (
                    isinstance(override, dict)
                    and override.get("type") == component_type
                    and override.get("mode") == "replace"
                ):
                    found.add(str(override.get("block_id", "")))
            if component_type == "custom-tool" and isinstance(settings, dict):
                for reference in settings.get("tool_refs", []):
                    if isinstance(reference, dict):
                        found.add(str(reference.get("tool_id", "")))
            if component_type == "custom-middleware" and isinstance(settings, dict):
                for reference in settings.get("middleware_refs", []):
                    if isinstance(reference, dict):
                        found.add(str(reference.get("middleware_id", "")))
        return {item for item in found if item}

    records: list[dict[str, object]] = []
    resolver_specs = {
        "custom-tool": (
            resolve_tool_package,
            "tool",
            "agent-tool",
        ),
        "agent-event-output": (
            resolve_agent_event_output_package,
            "event-output",
            "agent-event-output",
        ),
        "workflow-event-output": (
            resolve_workflow_event_output_package,
            "event-output",
            "workflow-event-output",
        ),
        "custom-middleware": (
            resolve_middleware_package,
            "middleware",
            "agent-middleware",
        ),
        "command": (
            resolve_command_package,
            "workflow-node",
            "command",
        ),
    }
    for component_type, (resolver, family, adapter) in resolver_specs.items():
        by_id = {
            str(item.get("id", "")): item
            for item in components.get(component_type, [])
            if isinstance(item, dict)
        }
        for component_id in referenced_ids(component_type):
            component = by_id.get(component_id)
            reference = component.get("python_package") if component else None
            if not isinstance(reference, dict):
                print(
                    "WARNING: Skipping invalid Python extension reference "
                    f"for {component_type}/{component_id}."
                )
                continue
            try:
                resolved = resolver(
                    str(reference.get("folder", "")),
                    packages_dir,
                    owner_id=component_id,
                    runtime_root=None,
                )
            except ResourceScanError as exc:
                print(
                    "WARNING: Skipping invalid Python extension "
                    f"for {component_type}/{component_id}: {exc.message_key}."
                )
                continue
            if resolved is None:
                print(
                    "WARNING: Skipping missing Python extension "
                    f"for {component_type}/{component_id}."
                )
                continue
            item, _folder = resolved
            records.append({**dict(item), "id": f"python-package:{item['id']}"})
    input_fingerprint = _input_fingerprint(core_fingerprint, records)
    current = load_dependency_state(runtime_root)
    target = package_site_packages(runtime_root)
    if (
        current is not None
        and current.get("status") == "ready"
        and current.get("input_fingerprint") == input_fingerprint
        and target.is_dir()
    ):
        print("Python package dependencies are already current.")
        return

    requirements = [
        requirement
        for record in records
        for requirement in record["python_requirements"]
    ]
    build_root = runtime_root / "tmp" / f"python-packages-{uuid4().hex}"
    prepared = build_root / SITE_PACKAGES_FOLDER
    prepared.mkdir(parents=True)
    try:
        if requirements:
            print("Python requirements:")
            for requirement in requirements:
                print(f"  {requirement}")
            uv_path = ensure_uv(runtime_root, manifest)
            requirements_path = build_root / "requirements.txt"
            constraints_path = build_root / "core-constraints.txt"
            requirements_path.write_text(
                "\n".join(str(value) for value in requirements) + "\n",
                encoding="utf-8",
            )
            constraints_path.write_text(
                "\n".join(_core_constraints()) + "\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            for name in tuple(environment):
                if name.upper().startswith(("UV_", "PIP_")):
                    environment.pop(name)
            environment["UV_CACHE_DIR"] = str(runtime_root / "cache" / "uv")
            result = subprocess.run(
                [
                    str(uv_path),
                    "pip",
                    "install",
                    "--target",
                    str(prepared),
                    "--python-version",
                    str(manifest.get("python", "")),
                    "--python-platform",
                    "x86_64-pc-windows-msvc",
                    "--no-config",
                    "--default-index",
                    PYPI_INDEX,
                    "--constraints",
                    str(constraints_path),
                    "--requirements",
                    str(requirements_path),
                ],
                check=False,
                env=environment,
            )
            if result.returncode != 0:
                _write_failure_state(
                    runtime_root,
                    records,
                    input_fingerprint=input_fingerprint,
                    core_fingerprint=core_fingerprint,
                    error_code="dependency_resolution_failed",
                )
                print(
                    "WARNING: Python package dependencies could not be resolved. "
                    "Agent Shell will start without the package dependency layer.",
                    file=sys.stderr,
                )
                return
            if not _package_layout_is_supported(prepared):
                _write_failure_state(
                    runtime_root,
                    records,
                    input_fingerprint=input_fingerprint,
                    core_fingerprint=core_fingerprint,
                    error_code="dependency_layout_unsupported",
                )
                print(
                    "WARNING: Python package dependencies contain unsupported "
                    "links or Python path files. Agent Shell will start without the "
                    "package dependency layer.",
                    file=sys.stderr,
                )
                return

        _replace_site_packages(runtime_root, prepared)
        _atomic_write_json(
            dependency_state_path(runtime_root),
            {
                "schema": DEPENDENCY_STATE_SCHEMA,
                "platform": "windows-x64",
                "status": "ready",
                "input_fingerprint": input_fingerprint,
                "core_fingerprint": core_fingerprint,
                "records": _record_states(records, status="ready"),
            },
        )
        print("Python package dependencies are ready.")
    finally:
        shutil.rmtree(build_root, ignore_errors=True)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent_shell.python_packages.dependencies"
    )
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--data-dir", type=Path)
    parsed = parser.parse_args(arguments)
    home = parsed.home.resolve()
    data_root = parsed.data_dir or (home / "data")
    data_root = (
        data_root.resolve()
        if data_root.is_absolute()
        else (home / data_root).resolve()
    )
    try:
        prepare_windows_dependencies(
            data_root=data_root,
            runtime_root=(home / "runtime").resolve(),
        )
    except Exception as exc:
        print(f"Python package dependency preparation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
