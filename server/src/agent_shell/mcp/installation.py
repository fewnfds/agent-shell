from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from agent_shell.mcp.installation_contract import (
    INSTALLATION_SCHEMA,
    LOCK_SCHEMA,
    McpInstallationError,
    fingerprint,
    is_child,
    load_json,
    write_json,
)
from agent_shell.mcp.installation_npm import install_npm_package
from agent_shell.mcp.installation_pypi import install_pypi_package


def installation_declaration(connection: dict[str, Any]) -> dict[str, str | None]:
    if connection.get("transport") != "stdio":
        raise ValueError("only local package MCP connections have installation declarations")
    return {
        "source": str(connection.get("package_source", "")),
        "package": str(connection.get("package", "")),
        "version": str(connection.get("version", "")),
        "entrypoint": (
            str(connection["entrypoint"])
            if connection.get("entrypoint") is not None
            else None
        ),
    }


class McpInstallationManager:
    """Own managed local MCP package locks and rebuildable isolated runtimes."""

    def __init__(self, data_root: Path, runtime_root: Path) -> None:
        self.data_root = Path(data_root).resolve()
        self.runtime_root = Path(runtime_root).resolve()
        self.application_home = self.runtime_root.parent
        self.root = self.runtime_root / "mcp"
        self.installations_root = self.root / "installations"
        self.status_root = self.root / "status"
        self.cache_root = self.root / "cache"
        self.toolchains_root = self.root / "toolchains"
        self.locks_root = self.data_root / "config" / "mcp-connections"

    def _core_runtime_lock(self) -> dict[str, Any]:
        value = load_json(
            self.application_home / "packaging" / "windows" / "runtime-lock.json"
        )
        if value is None:
            raise McpInstallationError(
                "mcp_toolchain_unavailable",
                "The Agent Shell Windows runtime lock is unavailable.",
            )
        return value

    def _mcp_runtime_lock(self) -> dict[str, Any]:
        value = load_json(
            self.application_home / "packaging" / "windows" / "mcp-runtime-lock.json"
        )
        if value is None:
            raise McpInstallationError(
                "mcp_toolchain_unavailable",
                "The Agent Shell MCP runtime lock is unavailable.",
            )
        return value

    def _toolchain(self, connection: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if connection.get("package_source") == "npm":
            node = self._mcp_runtime_lock().get("node")
            if not isinstance(node, dict):
                raise McpInstallationError(
                    "mcp_node_toolchain_unavailable",
                    "The Agent Shell Node.js toolchain lock is unavailable.",
                )
            value = {"source": "npm", "node": node}
            return fingerprint(value), value
        core = self._core_runtime_lock()
        uv = core.get("uv")
        if not isinstance(uv, dict):
            raise McpInstallationError(
                "mcp_python_toolchain_unavailable",
                "The Agent Shell Python toolchain lock is unavailable.",
            )
        value = {
            "source": "pypi",
            "platform": core.get("platform"),
            "python": core.get("python"),
            "uv": uv,
        }
        return fingerprint(value), value

    def _identity(
        self,
        connection: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        toolchain_identity, toolchain = self._toolchain(connection)
        declaration_fingerprint = fingerprint(
            {
                "declaration": installation_declaration(connection),
                "toolchain_identity": toolchain_identity,
            }
        )
        return declaration_fingerprint, toolchain_identity, toolchain

    def _lock_path(self, connection_id: str) -> Path:
        return self.locks_root / f"{connection_id}.installation-lock.json"

    def _status_path(self, connection_id: str) -> Path:
        return self.status_root / f"{connection_id}.json"

    def _installation_path(self, connection_id: str, declaration_fingerprint: str) -> Path:
        return self.installations_root / connection_id / declaration_fingerprint

    def _manifest_path(self, connection_id: str, declaration_fingerprint: str) -> Path:
        return self._installation_path(connection_id, declaration_fingerprint) / "manifest.json"

    def _load_lock(
        self,
        connection_id: str,
        declaration_fingerprint: str,
        toolchain_identity: str,
    ) -> dict[str, Any] | None:
        value = load_json(self._lock_path(connection_id))
        if (
            value is None
            or value.get("schema") != LOCK_SCHEMA
            or value.get("declaration_fingerprint") != declaration_fingerprint
            or value.get("toolchain_identity") != toolchain_identity
        ):
            return None
        return value

    def _ready_files_exist(
        self,
        connection_id: str,
        declaration_fingerprint: str,
        toolchain_identity: str,
        manifest: dict[str, Any],
    ) -> bool:
        installation = self._installation_path(connection_id, declaration_fingerprint)
        relative_command = manifest.get("command")
        relative_entry = manifest.get("entry")
        lock = self._load_lock(
            connection_id,
            declaration_fingerprint,
            toolchain_identity,
        )
        return (
            lock is not None
            and manifest.get("toolchain_identity") == toolchain_identity
            and manifest.get("installation_lock_fingerprint") == fingerprint(lock)
            and isinstance(relative_command, str)
            and isinstance(relative_entry, str)
            and (installation / relative_command).is_file()
            and (installation / relative_entry).is_file()
        )

    def status(self, connection_id: str, connection: dict[str, Any]) -> dict[str, Any] | None:
        if connection.get("transport") != "stdio":
            return None
        try:
            declaration_fingerprint, toolchain_identity, _ = self._identity(connection)
        except McpInstallationError as exc:
            return self._projection(connection, "failed", error_code=exc.code)
        manifest = load_json(self._manifest_path(connection_id, declaration_fingerprint))
        if (
            manifest is not None
            and manifest.get("schema") == INSTALLATION_SCHEMA
            and manifest.get("status") == "ready"
            and manifest.get("declaration_fingerprint") == declaration_fingerprint
            and self._ready_files_exist(
                connection_id,
                declaration_fingerprint,
                toolchain_identity,
                manifest,
            )
        ):
            return self._projection(
                connection,
                "ready",
            )
        failure = load_json(self._status_path(connection_id))
        if (
            failure is not None
            and failure.get("schema") == INSTALLATION_SCHEMA
            and failure.get("status") == "failed"
            and failure.get("declaration_fingerprint") == declaration_fingerprint
            and failure.get("toolchain_identity") == toolchain_identity
        ):
            entrypoints = failure.get("entrypoints")
            return self._projection(
                connection,
                "failed",
                error_code=str(failure.get("error_code", "mcp_installation_failed")),
                entrypoints=(
                    [str(value) for value in entrypoints]
                    if isinstance(entrypoints, list)
                    else None
                ),
            )
        return self._projection(connection, "not_installed")

    @staticmethod
    def _projection(
        connection: dict[str, Any],
        status: str,
        *,
        error_code: str | None = None,
        entrypoints: list[str] | None = None,
    ) -> dict[str, Any]:
        result = {
            "status": status,
            "package_source": connection["package_source"],
            "package": connection["package"],
            "version": connection["version"],
            "entrypoint": connection.get("entrypoint"),
        }
        if error_code is not None:
            result["error_code"] = error_code
        if entrypoints:
            result["entrypoints"] = entrypoints
        return result

    def resolve_connection(
        self,
        connection_id: str,
        connection: dict[str, Any],
    ) -> dict[str, Any]:
        if connection.get("transport") != "stdio":
            return dict(connection)
        declaration_fingerprint, toolchain_identity, _ = self._identity(connection)
        manifest = load_json(self._manifest_path(connection_id, declaration_fingerprint))
        if (
            manifest is None
            or manifest.get("schema") != INSTALLATION_SCHEMA
            or manifest.get("status") != "ready"
            or manifest.get("declaration_fingerprint") != declaration_fingerprint
            or not self._ready_files_exist(
                connection_id,
                declaration_fingerprint,
                toolchain_identity,
                manifest,
            )
        ):
            raise McpInstallationError(
                "mcp_installation_not_ready",
                "The managed local MCP package must be installed before it can be used.",
            )
        installation = self._installation_path(connection_id, declaration_fingerprint)
        command = (installation / str(manifest["command"])).resolve()
        entry = (installation / str(manifest["entry"])).resolve()
        if not is_child(command, installation) or not is_child(entry, installation):
            raise McpInstallationError(
                "mcp_installation_invalid",
                "The managed local MCP installation manifest is invalid.",
            )
        resolved: dict[str, Any] = {
            "transport": "stdio",
            "command": str(command),
            "args": [
                str(entry),
                *[
                    str(value)
                    for value in manifest.get("launcher_args", [])
                    if isinstance(value, str)
                ],
                *list(connection.get("args", [])),
            ],
        }
        if connection.get("cwd"):
            resolved["cwd"] = str(connection["cwd"])
        path_entries = [
            str((installation / value).resolve())
            for value in manifest.get("path_entries", [])
            if isinstance(value, str) and is_child(installation / value, installation)
        ]
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        path_entries.extend([str(Path(system_root) / "System32"), system_root])
        configured_environment = dict(connection.get("env", {}))
        configured_path = configured_environment.get("PATH")
        if configured_path:
            path_entries.append(configured_path)
        resolved["env"] = {
            **configured_environment,
            "PATH": os.pathsep.join(path_entries),
        }
        return resolved

    def install(self, connection_id: str, connection: dict[str, Any]) -> dict[str, Any]:
        if connection.get("transport") != "stdio":
            raise McpInstallationError(
                "mcp_installation_not_applicable",
                "Remote HTTP MCP connections do not require local installation.",
            )
        declaration_fingerprint, toolchain_identity, toolchain = self._identity(connection)
        final = self._installation_path(connection_id, declaration_fingerprint)
        existing_lock = self._load_lock(
            connection_id,
            declaration_fingerprint,
            toolchain_identity,
        )
        staging = self.runtime_root / "tmp" / f"mcp-install-{uuid4().hex}"
        staging.mkdir(parents=True)
        try:
            if connection["package_source"] == "npm":
                manifest, lock = install_npm_package(
                    staging=staging,
                    connection=connection,
                    declaration_fingerprint=declaration_fingerprint,
                    toolchain_identity=toolchain_identity,
                    existing_lock=existing_lock,
                    node_lock=toolchain["node"],
                    runtime_root=self.runtime_root,
                    cache_root=self.cache_root,
                    toolchains_root=self.toolchains_root,
                )
            else:
                runtime_manifest = load_json(
                    self.runtime_root / "app" / "runtime-manifest.json"
                )
                if (
                    runtime_manifest is None
                    or runtime_manifest.get("python") != toolchain.get("python")
                    or runtime_manifest.get("uv") != toolchain.get("uv", {}).get("version")
                ):
                    raise McpInstallationError(
                        "mcp_python_toolchain_unavailable",
                        "The Agent Shell internal Python runtime does not match its lock.",
                    )
                manifest, lock = install_pypi_package(
                    staging=staging,
                    connection=connection,
                    declaration_fingerprint=declaration_fingerprint,
                    toolchain_identity=toolchain_identity,
                    existing_lock=existing_lock,
                    runtime_root=self.runtime_root,
                    cache_root=self.cache_root,
                    runtime_manifest=runtime_manifest,
                )
            manifest["installation_lock_fingerprint"] = fingerprint(lock)
            write_json(staging / "manifest.json", manifest)
            final.parent.mkdir(parents=True, exist_ok=True)
            previous = final.parent / f".previous-{uuid4().hex}"
            if final.exists():
                final.replace(previous)
            try:
                staging.replace(final)
                try:
                    write_json(self._lock_path(connection_id), lock)
                except BaseException:
                    shutil.rmtree(final, ignore_errors=True)
                    if previous.exists():
                        previous.replace(final)
                    raise
            except BaseException:
                if not final.exists() and previous.exists():
                    previous.replace(final)
                raise
            if previous.exists():
                shutil.rmtree(previous, ignore_errors=True)
            self._status_path(connection_id).unlink(missing_ok=True)
            for sibling in final.parent.iterdir():
                if sibling != final and sibling.is_dir():
                    shutil.rmtree(sibling, ignore_errors=True)
            result = self.status(connection_id, connection)
            assert result is not None and result["status"] == "ready"
            return result
        except McpInstallationError as exc:
            write_json(
                self._status_path(connection_id),
                {
                    "schema": INSTALLATION_SCHEMA,
                    "status": "failed",
                    "declaration_fingerprint": declaration_fingerprint,
                    "toolchain_identity": toolchain_identity,
                    "error_code": exc.code,
                    **(
                        {"entrypoints": list(exc.entrypoints)}
                        if exc.entrypoints
                        else {}
                    ),
                },
            )
            raise
        except OSError as exc:
            error = McpInstallationError(
                "mcp_installation_failed",
                "The managed local MCP installation could not be published.",
            )
            try:
                write_json(
                    self._status_path(connection_id),
                    {
                        "schema": INSTALLATION_SCHEMA,
                        "status": "failed",
                        "declaration_fingerprint": declaration_fingerprint,
                        "toolchain_identity": toolchain_identity,
                        "error_code": error.code,
                    },
                )
            except OSError:
                pass
            raise error from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def remove(self, connection_id: str) -> None:
        installation_root = self.installations_root / connection_id
        if installation_root.exists():
            shutil.rmtree(installation_root, ignore_errors=True)
        self._status_path(connection_id).unlink(missing_ok=True)
        self._lock_path(connection_id).unlink(missing_ok=True)


__all__ = [
    "McpInstallationError",
    "McpInstallationManager",
    "installation_declaration",
]
