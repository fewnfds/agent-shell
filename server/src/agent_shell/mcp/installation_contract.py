from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from agent_shell.storage.atomic_files import write_text_atomic


INSTALLATION_SCHEMA = 1
LOCK_SCHEMA = 1
PYPI_INDEX = "https://pypi.org/simple"


class McpInstallationError(RuntimeError):
    def __init__(self, code: str, message: str, *, entrypoints: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.entrypoints = entrypoints


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def write_json(path: Path, value: dict[str, Any]) -> None:
    write_text_atomic(path, canonical_json(value) + "\n")


def is_child(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def fingerprint(value: object) -> str:
    return sha256(canonical_json(value).encode("ascii")).hexdigest()


def select_entrypoint(requested: Any, entrypoints: dict[str, str]) -> str:
    available = tuple(sorted(entrypoints))
    if isinstance(requested, str) and requested:
        if requested not in entrypoints:
            raise McpInstallationError(
                "mcp_entrypoint_missing",
                "The configured MCP entrypoint is not published by the package.",
                entrypoints=available,
            )
        return requested
    if len(available) != 1:
        raise McpInstallationError(
            "mcp_entrypoint_required",
            "The MCP package publishes multiple entrypoints; select one explicitly.",
            entrypoints=available,
        )
    return available[0]


def run_install_command(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    error_code: str,
) -> None:
    inherited = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in {
            "APPDATA",
            "HOMEDRIVE",
            "HOMEPATH",
            "LOCALAPPDATA",
            "PATHEXT",
            "SYSTEMDRIVE",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "USERPROFILE",
        }
    }
    result = subprocess.run(
        command,
        cwd=cwd,
        env={**inherited, **environment},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise McpInstallationError(
            error_code,
            "The MCP package installation command failed.",
        )


__all__ = [
    "INSTALLATION_SCHEMA",
    "LOCK_SCHEMA",
    "McpInstallationError",
    "PYPI_INDEX",
    "canonical_json",
    "fingerprint",
    "is_child",
    "load_json",
    "run_install_command",
    "select_entrypoint",
    "write_json",
]
