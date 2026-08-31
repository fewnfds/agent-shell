from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil
from typing import Any
from urllib.request import urlopen
from uuid import uuid4
from zipfile import ZipFile

from agent_shell.mcp.installation_contract import (
    INSTALLATION_SCHEMA,
    LOCK_SCHEMA,
    McpInstallationError,
    is_child,
    load_json,
    run_install_command,
    select_entrypoint,
    write_json,
)


def _npm_environment(node_root: Path, cache_root: Path) -> dict[str, str]:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return {
        "PATH": os.pathsep.join([str(node_root), str(system_root / "System32")]),
        "NPM_CONFIG_CACHE": str(cache_root / "npm"),
    }


def _ensure_node_toolchain(
    *,
    node_lock: dict[str, Any],
    runtime_root: Path,
    toolchains_root: Path,
) -> Path:
    version = str(node_lock.get("version", ""))
    target = toolchains_root / f"node-v{version}-win-x64"
    node = target / "node.exe"
    npm_cli = target / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if node.is_file() and npm_cli.is_file():
        return target
    temporary = runtime_root / "tmp" / f"mcp-node-{uuid4().hex}"
    archive = temporary / "node.zip"
    extracted = temporary / "extracted"
    temporary.mkdir(parents=True)
    try:
        with urlopen(str(node_lock.get("url", ""))) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        digest = sha256(archive.read_bytes()).hexdigest()
        if digest.casefold() != str(node_lock.get("sha256", "")).casefold():
            raise McpInstallationError(
                "mcp_node_toolchain_integrity_failed",
                "The downloaded Node.js toolchain failed integrity verification.",
            )
        with ZipFile(archive) as package:
            package.extractall(extracted)
        roots = [item for item in extracted.iterdir() if item.is_dir()]
        if (
            len(roots) != 1
            or not (roots[0] / "node.exe").is_file()
            or not (roots[0] / "node_modules" / "npm" / "bin" / "npm-cli.js").is_file()
        ):
            raise McpInstallationError(
                "mcp_node_toolchain_invalid",
                "The Node.js toolchain archive has an unsupported layout.",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        roots[0].replace(target)
        return target
    except McpInstallationError:
        raise
    except (OSError, ValueError) as exc:
        raise McpInstallationError(
            "mcp_node_toolchain_download_failed",
            "The Agent Shell Node.js toolchain could not be prepared.",
        ) from exc
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _npm_bins(package: str, metadata: dict[str, Any]) -> dict[str, str]:
    raw = metadata.get("bin")
    if isinstance(raw, str):
        return {package.rsplit("/", 1)[-1]: raw}
    if isinstance(raw, dict) and all(
        isinstance(name, str) and isinstance(path, str)
        for name, path in raw.items()
    ):
        return dict(raw)
    raise McpInstallationError(
        "mcp_entrypoint_missing",
        "The installed npm package does not publish an executable entrypoint.",
    )


def install_npm_package(
    *,
    staging: Path,
    connection: dict[str, Any],
    declaration_fingerprint: str,
    toolchain_identity: str,
    existing_lock: dict[str, Any] | None,
    node_lock: dict[str, Any],
    runtime_root: Path,
    cache_root: Path,
    toolchains_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    node_root = _ensure_node_toolchain(
        node_lock=node_lock,
        runtime_root=runtime_root,
        toolchains_root=toolchains_root,
    )
    node = node_root / "node.exe"
    npm_cli = node_root / "node_modules" / "npm" / "bin" / "npm-cli.js"
    package = str(connection["package"])
    package_json = {
        "name": "agent-shell-managed-mcp",
        "private": True,
        "version": "1.0.0",
        "dependencies": {package: str(connection["version"])},
    }
    write_json(staging / "package.json", package_json)
    if existing_lock is not None and isinstance(existing_lock.get("package_lock"), dict):
        write_json(staging / "package-lock.json", existing_lock["package_lock"])
    else:
        run_install_command(
            [
                str(node),
                str(npm_cli),
                "install",
                "--package-lock-only",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
            ],
            cwd=staging,
            environment=_npm_environment(node_root, cache_root),
            error_code="mcp_npm_resolution_failed",
        )
    run_install_command(
        [str(node), str(npm_cli), "ci", "--no-audit", "--no-fund"],
        cwd=staging,
        environment=_npm_environment(node_root, cache_root),
        error_code="mcp_npm_install_failed",
    )
    package_root = staging / "node_modules" / Path(*package.split("/"))
    metadata = load_json(package_root / "package.json")
    if metadata is None:
        raise McpInstallationError(
            "mcp_npm_package_invalid",
            "The installed npm package does not contain package metadata.",
        )
    bins = _npm_bins(package, metadata)
    entrypoint = select_entrypoint(connection.get("entrypoint"), bins)
    entry = (package_root / bins[entrypoint]).resolve()
    if not is_child(entry, package_root) or not entry.is_file():
        raise McpInstallationError(
            "mcp_entrypoint_invalid",
            "The selected npm MCP entrypoint is invalid.",
        )
    local_node = staging / "toolchain" / "node.exe"
    local_node.parent.mkdir(parents=True)
    shutil.copy2(node, local_node)
    package_lock = load_json(staging / "package-lock.json")
    if package_lock is None:
        raise McpInstallationError(
            "mcp_npm_lock_invalid",
            "The npm installation did not produce a package lock.",
        )
    common = {
        "declaration_fingerprint": declaration_fingerprint,
        "toolchain_identity": toolchain_identity,
        "source": "npm",
    }
    return (
        {
            **common,
            "schema": INSTALLATION_SCHEMA,
            "status": "ready",
            "entrypoint": entrypoint,
            "command": "toolchain/node.exe",
            "entry": entry.relative_to(staging).as_posix(),
            "path_entries": ["toolchain", "node_modules/.bin"],
        },
        {**common, "schema": LOCK_SCHEMA, "package_lock": package_lock},
    )


__all__ = ["install_npm_package"]
