from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

from agent_shell.mcp.installation_contract import (
    INSTALLATION_SCHEMA,
    LOCK_SCHEMA,
    McpInstallationError,
    PYPI_INDEX,
    run_install_command,
    select_entrypoint,
)
from agent_shell.runtime.windows_toolchains import ensure_uv


def _uv_environment(cache_root: Path) -> dict[str, str]:
    return {
        "PATH": str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"),
        "UV_CACHE_DIR": str(cache_root / "uv"),
        "UV_PYTHON_DOWNLOADS": "never",
    }


def _python_entrypoints(python: Path, package: str) -> tuple[str, ...]:
    script = (
        "import json,sys; from importlib.metadata import distribution; "
        "print(json.dumps(sorted(e.name for e in distribution(sys.argv[1]).entry_points "
        "if e.group == 'console_scripts')))"
    )
    result = subprocess.run(
        [str(python), "-I", "-B", "-c", script, package],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise McpInstallationError(
            "mcp_pypi_package_invalid",
            "The installed Python package metadata could not be read.",
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise McpInstallationError(
            "mcp_pypi_package_invalid",
            "The installed Python package entrypoints are invalid.",
        ) from exc
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) for item in value)
    ):
        raise McpInstallationError(
            "mcp_entrypoint_missing",
            "The installed Python package does not publish a console entrypoint.",
        )
    return tuple(value)


def install_pypi_package(
    *,
    staging: Path,
    connection: dict[str, Any],
    declaration_fingerprint: str,
    toolchain_identity: str,
    existing_lock: dict[str, Any] | None,
    runtime_root: Path,
    cache_root: Path,
    runtime_manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    python_home_path = runtime_root / "app" / "python-home.txt"
    try:
        python_home = python_home_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise McpInstallationError(
            "mcp_python_toolchain_unavailable",
            "The Agent Shell internal Python runtime is unavailable.",
        ) from exc
    python = runtime_root / "app" / python_home / "python.exe"
    if not python.is_file():
        raise McpInstallationError(
            "mcp_python_toolchain_unavailable",
            "The Agent Shell internal Python toolchain is unavailable.",
        )
    try:
        uv = ensure_uv(runtime_root, runtime_manifest)
    except (OSError, ValueError) as exc:
        raise McpInstallationError(
            "mcp_python_toolchain_unavailable",
            "The Agent Shell internal Python toolchain is unavailable.",
        ) from exc
    requirement = f"{connection['package']}=={connection['version']}"
    requirements_in = staging / "requirements.in"
    requirements_lock = staging / "requirements.lock"
    requirements_in.write_text(requirement + "\n", encoding="utf-8")
    if existing_lock is not None and isinstance(existing_lock.get("requirements"), str):
        requirements_lock.write_text(existing_lock["requirements"], encoding="utf-8")
    else:
        run_install_command(
            [
                str(uv),
                "pip",
                "compile",
                str(requirements_in),
                "--output-file",
                str(requirements_lock),
                "--generate-hashes",
                "--no-annotate",
                "--no-header",
                "--python",
                str(python),
                "--python-version",
                str(runtime_manifest.get("python", "")),
                "--python-platform",
                "x86_64-pc-windows-msvc",
                "--no-config",
                "--default-index",
                PYPI_INDEX,
            ],
            cwd=staging,
            environment=_uv_environment(cache_root),
            error_code="mcp_pypi_resolution_failed",
        )
    environment_root = staging / "environment"
    run_install_command(
        [
            str(uv),
            "venv",
            str(environment_root),
            "--python",
            str(python),
            "--no-python-downloads",
        ],
        cwd=staging,
        environment=_uv_environment(cache_root),
        error_code="mcp_pypi_environment_failed",
    )
    environment_python = environment_root / "Scripts" / "python.exe"
    run_install_command(
        [
            str(uv),
            "pip",
            "install",
            "--python",
            str(environment_python),
            "--require-hashes",
            "--requirements",
            str(requirements_lock),
            "--no-config",
            "--default-index",
            PYPI_INDEX,
        ],
        cwd=staging,
        environment=_uv_environment(cache_root),
        error_code="mcp_pypi_install_failed",
    )
    entrypoint = select_entrypoint(
        connection.get("entrypoint"),
        {name: name for name in _python_entrypoints(environment_python, str(connection["package"]))},
    )
    launcher = staging / "launch_mcp.py"
    launcher.write_text(
        "from importlib.metadata import distribution\n"
        "import sys\n"
        "package, name = sys.argv[1], sys.argv[2]\n"
        "entry = next(item for item in distribution(package).entry_points "
        "if item.group == 'console_scripts' and item.name == name)\n"
        "sys.argv = [name, *sys.argv[3:]]\n"
        "result = entry.load()()\n"
        "raise SystemExit(result if isinstance(result, int) else 0)\n",
        encoding="utf-8",
    )
    common = {
        "declaration_fingerprint": declaration_fingerprint,
        "toolchain_identity": toolchain_identity,
        "source": "pypi",
    }
    return (
        {
            **common,
            "schema": INSTALLATION_SCHEMA,
            "status": "ready",
            "entrypoint": entrypoint,
            "command": "environment/Scripts/python.exe",
            "entry": "launch_mcp.py",
            "path_entries": ["environment/Scripts"],
            "launcher_args": [str(connection["package"]), entrypoint],
        },
        {
            **common,
            "schema": LOCK_SCHEMA,
            "requirements": requirements_lock.read_text(encoding="utf-8"),
        },
    )


__all__ = ["install_pypi_package"]
