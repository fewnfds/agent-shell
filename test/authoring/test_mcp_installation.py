from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from agent_shell.mcp.installation import McpInstallationManager
from agent_shell.mcp.installation_contract import (
    INSTALLATION_SCHEMA,
    LOCK_SCHEMA,
    McpInstallationError,
)
from agent_shell.mcp.installation_pypi import install_pypi_package


CONNECTION_ID = "11111111-1111-4111-8111-111111111111"


def manager(tmp_path: Path) -> McpInstallationManager:
    locks = tmp_path / "packaging" / "windows"
    locks.mkdir(parents=True)
    (locks / "runtime-lock.json").write_text(
        json.dumps({
            "schema": 1,
            "platform": "windows-x64",
            "python": "3.12.13",
            "uv": {"version": "0.12.2", "url": "uv", "sha256": "uv"},
        }),
        encoding="utf-8",
    )
    (locks / "mcp-runtime-lock.json").write_text(
        json.dumps({
            "schema": 1,
            "platform": "windows-x64",
            "node": {"version": "22.23.2", "url": "node", "sha256": "node"},
        }),
        encoding="utf-8",
    )
    return McpInstallationManager(tmp_path / "data", tmp_path / "runtime")


def connection() -> dict:
    return {
        "name": "Browser",
        "transport": "stdio",
        "package_source": "npm",
        "package": "browser-mcp",
        "version": "1.2.3",
        "entrypoint": None,
        "args": ["--headless"],
        "cwd": None,
        "env": {"TOKEN": "secret", "PATH": r"D:\explicit-tools"},
    }


def test_installation_projects_only_ready_managed_runtime(monkeypatch, tmp_path: Path) -> None:
    installations = manager(tmp_path)

    def fake_install(**values):
        staging = values["staging"]
        command = staging / "toolchain" / "node.exe"
        entry = staging / "node_modules" / "browser-mcp" / "index.js"
        command.parent.mkdir(parents=True)
        entry.parent.mkdir(parents=True)
        command.write_bytes(b"node")
        entry.write_text("server", encoding="utf-8")
        common = {
            "declaration_fingerprint": values["declaration_fingerprint"],
            "toolchain_identity": values["toolchain_identity"],
            "source": "npm",
        }
        return (
            {
                **common,
                "schema": INSTALLATION_SCHEMA,
                "status": "ready",
                "entrypoint": "browser-mcp",
                "command": "toolchain/node.exe",
                "entry": "node_modules/browser-mcp/index.js",
                "path_entries": ["toolchain", "node_modules/.bin"],
            },
            {**common, "schema": LOCK_SCHEMA, "package_lock": {}},
        )

    monkeypatch.setattr(
        "agent_shell.mcp.installation.install_npm_package",
        fake_install,
    )
    assert installations.status(CONNECTION_ID, connection())["status"] == "not_installed"

    installed = installations.install(CONNECTION_ID, connection())
    resolved = installations.resolve_connection(CONNECTION_ID, connection())

    assert installed == {
        "status": "ready",
        "package_source": "npm",
        "package": "browser-mcp",
        "version": "1.2.3",
        "entrypoint": None,
    }
    assert resolved["transport"] == "stdio"
    assert Path(resolved["command"]).is_relative_to(installations.installations_root)
    assert resolved["args"][1:] == ["--headless"]
    assert resolved["env"]["TOKEN"] == "secret"
    assert resolved["env"]["PATH"].endswith(r"D:\explicit-tools")
    lock_path = (
        tmp_path
        / "data"
        / "config"
        / "mcp-connections"
        / f"{CONNECTION_ID}.installation-lock.json"
    )
    assert lock_path.is_file()

    shutil.rmtree(installations.installations_root / CONNECTION_ID)
    assert installations.status(CONNECTION_ID, connection())["status"] == "not_installed"
    assert lock_path.is_file()


def test_failed_installation_projects_discovered_entrypoints(monkeypatch, tmp_path: Path) -> None:
    installations = manager(tmp_path)

    def fail_install(**_values):
        raise McpInstallationError(
            "mcp_entrypoint_required",
            "select an entrypoint",
            entrypoints=("browser", "browser-debug"),
        )

    monkeypatch.setattr(
        "agent_shell.mcp.installation.install_npm_package",
        fail_install,
    )
    with pytest.raises(McpInstallationError):
        installations.install(CONNECTION_ID, connection())

    assert installations.status(CONNECTION_ID, connection()) == {
        "status": "failed",
        "package_source": "npm",
        "package": "browser-mcp",
        "version": "1.2.3",
        "entrypoint": None,
        "error_code": "mcp_entrypoint_required",
        "entrypoints": ["browser", "browser-debug"],
    }


def test_reinstall_failure_preserves_ready_environment(monkeypatch, tmp_path: Path) -> None:
    installations = manager(tmp_path)

    def install_ready(**values):
        staging = values["staging"]
        command = staging / "toolchain" / "node.exe"
        entry = staging / "server.js"
        command.parent.mkdir(parents=True)
        command.write_bytes(b"node")
        entry.write_text("server", encoding="utf-8")
        common = {
            "declaration_fingerprint": values["declaration_fingerprint"],
            "toolchain_identity": values["toolchain_identity"],
            "source": "npm",
        }
        return (
            {
                **common,
                "schema": INSTALLATION_SCHEMA,
                "status": "ready",
                "entrypoint": "browser-mcp",
                "command": "toolchain/node.exe",
                "entry": "server.js",
                "path_entries": ["toolchain"],
            },
            {**common, "schema": LOCK_SCHEMA, "package_lock": {"version": 1}},
        )

    monkeypatch.setattr(
        "agent_shell.mcp.installation.install_npm_package",
        install_ready,
    )
    installations.install(CONNECTION_ID, connection())
    resolved_before = installations.resolve_connection(CONNECTION_ID, connection())

    def fail_install(**_values):
        raise McpInstallationError("mcp_npm_install_failed", "install failed")

    monkeypatch.setattr(
        "agent_shell.mcp.installation.install_npm_package",
        fail_install,
    )
    with pytest.raises(McpInstallationError):
        installations.install(CONNECTION_ID, connection())

    assert installations.status(CONNECTION_ID, connection())["status"] == "ready"
    assert installations.resolve_connection(CONNECTION_ID, connection()) == resolved_before


def test_publish_failure_preserves_ready_environment(monkeypatch, tmp_path: Path) -> None:
    installations = manager(tmp_path)

    def install_ready(**values):
        staging = values["staging"]
        command = staging / "toolchain" / "node.exe"
        entry = staging / "server.js"
        command.parent.mkdir(parents=True)
        command.write_bytes(b"node")
        entry.write_text("server", encoding="utf-8")
        common = {
            "declaration_fingerprint": values["declaration_fingerprint"],
            "toolchain_identity": values["toolchain_identity"],
            "source": "npm",
        }
        return (
            {
                **common,
                "schema": INSTALLATION_SCHEMA,
                "status": "ready",
                "entrypoint": "browser-mcp",
                "command": "toolchain/node.exe",
                "entry": "server.js",
                "path_entries": ["toolchain"],
            },
            {**common, "schema": LOCK_SCHEMA, "package_lock": {"version": 1}},
        )

    monkeypatch.setattr(
        "agent_shell.mcp.installation.install_npm_package",
        install_ready,
    )
    installations.install(CONNECTION_ID, connection())
    resolved_before = installations.resolve_connection(CONNECTION_ID, connection())

    from agent_shell.mcp import installation as installation_module

    original_write_json = installation_module.write_json

    def fail_lock_write(path: Path, value: dict) -> None:
        if path.name.endswith(".installation-lock.json"):
            raise OSError("lock publication failed")
        original_write_json(path, value)

    monkeypatch.setattr(installation_module, "write_json", fail_lock_write)
    with pytest.raises(McpInstallationError) as captured:
        installations.install(CONNECTION_ID, connection())

    assert captured.value.code == "mcp_installation_failed"
    assert installations.status(CONNECTION_ID, connection())["status"] == "ready"
    assert installations.resolve_connection(CONNECTION_ID, connection()) == resolved_before


def test_python_and_npm_connections_use_independent_installations(monkeypatch, tmp_path: Path) -> None:
    installations = manager(tmp_path)
    runtime_app = tmp_path / "runtime" / "app"
    runtime_app.mkdir(parents=True)
    (runtime_app / "runtime-manifest.json").write_text(
        json.dumps({"python": "3.12.13", "uv": "0.12.2"}),
        encoding="utf-8",
    )

    def install_provider(**values):
        staging = values["staging"]
        source = values["connection"]["package_source"]
        command = staging / "environment" / "runner.exe"
        entry = staging / "server.py"
        command.parent.mkdir(parents=True)
        command.write_bytes(source.encode())
        entry.write_text(source, encoding="utf-8")
        common = {
            "declaration_fingerprint": values["declaration_fingerprint"],
            "toolchain_identity": values["toolchain_identity"],
            "source": source,
        }
        return (
            {
                **common,
                "schema": INSTALLATION_SCHEMA,
                "status": "ready",
                "entrypoint": "server",
                "command": "environment/runner.exe",
                "entry": "server.py",
                "path_entries": ["environment"],
            },
            {
                **common,
                "schema": LOCK_SCHEMA,
                **({"requirements": "locked"} if source == "pypi" else {"package_lock": {}}),
            },
        )

    monkeypatch.setattr(
        "agent_shell.mcp.installation.install_npm_package",
        install_provider,
    )
    monkeypatch.setattr(
        "agent_shell.mcp.installation.install_pypi_package",
        install_provider,
    )
    npm_connection = connection()
    python_connection = {
        **connection(),
        "package_source": "pypi",
        "package": "browser-mcp",
    }
    python_id = "22222222-2222-4222-8222-222222222222"

    installations.install(CONNECTION_ID, npm_connection)
    installations.install(python_id, python_connection)

    npm_command = Path(installations.resolve_connection(CONNECTION_ID, npm_connection)["command"])
    python_command = Path(installations.resolve_connection(python_id, python_connection)["command"])
    assert npm_command != python_command
    assert CONNECTION_ID in npm_command.parts
    assert python_id in python_command.parts

    changed = {**npm_connection, "version": "2.0.0"}
    assert installations.status(CONNECTION_ID, changed)["status"] == "not_installed"


def test_pypi_install_prepares_internal_uv_on_first_use(monkeypatch, tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    python = runtime_root / "app" / "python" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"python")
    (runtime_root / "app" / "python-home.txt").write_text(
        "python\n",
        encoding="utf-8",
    )
    uv = runtime_root / "bootstrap" / "uv.exe"
    ensured: list[dict] = []
    commands: list[list[str]] = []

    def ensure_internal_uv(_runtime_root: Path, manifest: dict) -> Path:
        ensured.append(manifest)
        uv.parent.mkdir(parents=True)
        uv.write_bytes(b"uv")
        return uv

    def run_command(command: list[str], *, cwd: Path, **_values) -> None:
        commands.append(command)
        if "venv" in command:
            environment_python = cwd / "environment" / "Scripts" / "python.exe"
            environment_python.parent.mkdir(parents=True)
            environment_python.write_bytes(b"python")

    monkeypatch.setattr(
        "agent_shell.mcp.installation_pypi.ensure_uv",
        ensure_internal_uv,
    )
    monkeypatch.setattr(
        "agent_shell.mcp.installation_pypi.run_install_command",
        run_command,
    )
    monkeypatch.setattr(
        "agent_shell.mcp.installation_pypi._python_entrypoints",
        lambda *_args: ("example-server",),
    )
    runtime_manifest = {
        "python": "3.12.13",
        "uv": "0.12.2",
        "uv_url": "https://example.invalid/uv.zip",
        "uv_sha256": "0" * 64,
    }
    staging = runtime_root / "tmp" / "installation"
    staging.mkdir(parents=True)

    manifest, lock = install_pypi_package(
        staging=staging,
        connection={
            "package_source": "pypi",
            "package": "example-mcp",
            "version": "1.2.3",
            "entrypoint": None,
        },
        declaration_fingerprint="declaration",
        toolchain_identity="toolchain",
        existing_lock={"requirements": "example-mcp==1.2.3 --hash=sha256:00\n"},
        runtime_root=runtime_root,
        cache_root=runtime_root / "mcp" / "cache",
        runtime_manifest=runtime_manifest,
    )

    assert ensured == [runtime_manifest]
    assert all("--only-binary" not in command for command in commands)
    assert manifest["entrypoint"] == "example-server"
    assert manifest["command"] == "environment/Scripts/python.exe"
    assert lock["requirements"].startswith("example-mcp==1.2.3")
