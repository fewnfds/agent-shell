from __future__ import annotations

import asyncio
from pathlib import Path
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_shell.api.mcp_connections import build_mcp_connection_router
from agent_shell.mcp.importing import normalize_mcp_servers_import
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.environment import (
    MCP_CONNECTION_ENVIRONMENT_OWNER,
    InstanceEnvironmentStore,
)
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.mcp_connections import McpResourceStore
from agent_shell.storage.mcp_connections import MCP_CONNECTION_ADAPTER


CONNECTION_ID = "11111111-1111-4111-8111-111111111111"
REPOSITORY_ID = "22222222-2222-4222-8222-222222222222"
REQUIREMENT_ID = "33333333-3333-4333-8333-333333333333"


def stdio_connection_payload(name: str = "Browser MCP") -> dict:
    return {
        "name": name,
        "transport": "stdio",
        "package_source": "npm",
        "package": "@playwright/mcp",
        "version": "0.0.1",
        "args": [],
        "cwd": None,
        "env": {
            "ACCESS_TOKEN": {"source": "secret", "value": "top-secret-token"},
            "LOG_LEVEL": {"source": "literal", "value": "warning"},
        },
    }


def managed_resources(tmp_path: Path) -> McpResourceStore:
    lock_root = tmp_path / "packaging" / "windows"
    lock_root.mkdir(parents=True)
    (lock_root / "runtime-lock.json").write_text(
        json.dumps({
            "schema": 1,
            "platform": "windows-x64",
            "python": "3.12.13",
            "uv": {"version": "0.12.2", "url": "uv", "sha256": "uv"},
        }),
        encoding="utf-8",
    )
    (lock_root / "mcp-runtime-lock.json").write_text(
        json.dumps({
            "schema": 1,
            "platform": "windows-x64",
            "node": {"version": "22.23.2", "url": "node", "sha256": "node"},
        }),
        encoding="utf-8",
    )
    return McpResourceStore(tmp_path, runtime_root=tmp_path / "runtime")


def test_mcp_connection_secret_slots_are_write_only_and_binding_is_scoped(
    tmp_path: Path,
) -> None:
    environment = InstanceEnvironmentStore(tmp_path / "config" / "agent-shell.env")
    resources = managed_resources(tmp_path)

    saved = resources.save_connection(CONNECTION_ID, stdio_connection_payload())

    assert saved["env"] == {
        "ACCESS_TOKEN": {"source": "secret", "status": "masked"},
        "LOG_LEVEL": {"source": "literal", "value": "warning"},
    }
    yaml_text = (
        tmp_path / "config" / "mcp-connections" / f"{CONNECTION_ID}.yaml"
    ).read_text(encoding="utf-8")
    assert "top-secret-token" not in yaml_text
    assert saved["installation"]["status"] == "not_installed"
    assert list(
        environment.owned_values(MCP_CONNECTION_ENVIRONMENT_OWNER).values()
    ) == ["top-secret-token"]

    resources.set_binding(REPOSITORY_ID, REQUIREMENT_ID, CONNECTION_ID)
    assert resources.get_binding(REPOSITORY_ID, REQUIREMENT_ID) == CONNECTION_ID
    assert resources.delete_connection(CONNECTION_ID) is True
    assert resources.get_binding(REPOSITORY_ID, REQUIREMENT_ID) is None
    assert environment.owned_values(MCP_CONNECTION_ENVIRONMENT_OWNER) == {}


def test_masked_secret_survives_connection_update_and_copy(tmp_path: Path) -> None:
    environment = InstanceEnvironmentStore(tmp_path / "config" / "agent-shell.env")
    resources = managed_resources(tmp_path)
    saved = resources.save_connection(CONNECTION_ID, stdio_connection_payload())

    updated = resources.save_connection(
        CONNECTION_ID,
        {**stdio_connection_payload("Updated Browser MCP"), "env": saved["env"]},
    )
    copied = resources.copy_connection(
        CONNECTION_ID,
        "Copied Browser MCP",
    )

    assert updated["env"]["ACCESS_TOKEN"]["status"] == "masked"
    assert copied["env"]["ACCESS_TOKEN"]["status"] == "masked"
    assert list(
        environment.owned_values(MCP_CONNECTION_ENVIRONMENT_OWNER).values()
    ) == ["top-secret-token", "top-secret-token"]


def test_mcp_servers_import_normalizes_aliases_and_requires_explicit_values() -> None:
    document = {
        "mcpServers": {
            "browser": {
                "command": "npx",
                "args": ["-y", "@playwright/mcp@0.0.1"],
                "env": {"TOKEN": "secret"},
                "enabled": False,
            },
            "docs": {
                "type": "streamable-http",
                "url": "https://example.com/mcp",
                "headers": {"Authorization": "Bearer token"},
            },
        }
    }

    normalized = normalize_mcp_servers_import(
        document,
        value_sources={
            "browser": {"env": {"TOKEN": "literal"}},
            "docs": {"headers": {}},
        },
    )

    assert normalized[0]["transport"] == "stdio"
    assert normalized[0]["package_source"] == "npm"
    assert normalized[0]["package"] == "@playwright/mcp"
    assert normalized[0]["version"] == "0.0.1"
    assert normalized[0]["env"]["TOKEN"] == {
        "source": "literal",
        "value": "secret",
    }
    assert normalized[1]["transport"] == "http"
    assert normalized[1]["headers"]["Authorization"] == {
        "source": "secret",
        "value": "Bearer token",
    }

    for candidate in normalized:
        MCP_CONNECTION_ADAPTER.validate_python(candidate)

    python_package = normalize_mcp_servers_import({
        "mcpServers": {
            "python-tools": {
                "command": "uvx",
                "args": ["--from", "example-mcp==1.2.3", "example-server", "--stdio"],
            }
        }
    })[0]
    assert python_package == {
        "name": "python-tools",
        "transport": "stdio",
        "package_source": "pypi",
        "package": "example-mcp",
        "version": "1.2.3",
        "entrypoint": "example-server",
        "args": ["--stdio"],
        "env": {},
    }
    MCP_CONNECTION_ADAPTER.validate_python(python_package)

    aliased = normalize_mcp_servers_import(
        {
            "mcpServers": {
                "docs": {
                    "type": "streamable-http",
                    "transport": "streamable_http",
                    "url": "https://example.com/mcp",
                }
            }
        }
    )
    assert aliased[0]["transport"] == "http"

    try:
        normalize_mcp_servers_import(
            {"mcpServers": {"docs": {"type": "sse", "url": "https://example.com/sse"}}}
        )
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("legacy SSE must not be silently imported")

    try:
        normalize_mcp_servers_import(
            {"mcpServers": {"docs": {"url": "https://example.com/mcp", "headers": {"Authorization": "${TOKEN}"}}}}
        )
    except ValueError as exc:
        assert "unresolved environment references" in str(exc)
    else:
        raise AssertionError("host environment references must not be resolved")

    for command, args in [
        ("npx", ["-y", "@playwright/mcp@latest"]),
        ("python", ["server.py"]),
    ]:
        try:
            normalize_mcp_servers_import(
                {"mcpServers": {"browser": {"command": command, "args": args}}}
            )
        except ValueError:
            pass
        else:
            raise AssertionError("host commands and floating package versions must be rejected")

    with pytest.raises(ValueError):
        MCP_CONNECTION_ADAPTER.validate_python({
            **stdio_connection_payload(),
            "version": "latest",
        })


def test_mcp_connection_api_imports_atomically_and_maps_requirement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = FileConfigRepository.empty(tmp_path)
    blocks = BlockStore(repository)
    resources = managed_resources(tmp_path)
    requirement_id = repository.new_configuration_id()
    blocks.save_block(
        "mcp-requirement",
        requirement_id,
        {
            "name": "Browser capability",
            "description": "Browser automation Tools.",
            "namespace": "browser",
        },
    )
    app = FastAPI()
    app.include_router(build_mcp_connection_router(repository, blocks, resources))
    client = TestClient(app)
    document = {
        "mcpServers": {
            "browser": {
                "command": "npx",
                "args": ["-y", "@playwright/mcp@0.0.1"],
                "env": {"TOKEN": "secret"},
            }
        }
    }

    preview = client.post(
        "/agent-shell/api/mcp-connections/import/preview",
        json={"document": document},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["connections"][0]["package_source"] == "npm"
    assert preview.json()["connections"][0]["values"] == [
        {"target": "env", "name": "TOKEN", "source": "secret"}
    ]

    imported = client.post(
        "/agent-shell/api/mcp-connections/import",
        json={"document": document},
    )
    assert imported.status_code == 200, imported.text
    connection_id = imported.json()[0]["id"]
    assert imported.json()[0]["env"]["TOKEN"]["status"] == "masked"

    class FakeTool:
        name = "navigate"

    class FakeClient:
        def __init__(self, connections):
            assert connections["installation_test"]["command"] == "internal-node.exe"

        async def get_tools(self, *, server_name=None):
            assert server_name == "installation_test"
            return [FakeTool()]

    monkeypatch.setattr(resources, "install_connection", lambda value: {"status": "ready"})
    def resolve_connection_outside_event_loop(value: str) -> dict:
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return {
            "transport": "stdio",
            "command": "internal-node.exe",
            "args": ["server.js"],
        }

    monkeypatch.setattr(
        resources,
        "resolve_connection",
        resolve_connection_outside_event_loop,
    )
    monkeypatch.setattr(
        "agent_shell.api.mcp_connections.MultiServerMCPClient",
        FakeClient,
    )
    installed = client.post(f"/agent-shell/api/mcp-connections/{connection_id}/install")
    assert installed.status_code == 200, installed.text
    assert installed.json()["tools"] == ["navigate"]

    requirements = client.get("/agent-shell/api/mcp-requirements").json()
    assert requirements[0]["binding"] is None
    bound = client.put(
        f"/agent-shell/api/mcp-requirements/{requirement_id}/binding",
        json={"connection_id": connection_id},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["binding"] == connection_id

    failed = client.post(
        "/agent-shell/api/mcp-connections/import",
        json={
            "document": {
                "mcpServers": {
                    "new-server": {"command": "python"},
                    "broken": {"type": "websocket", "url": "ws://example.com"},
                }
            }
        },
    )
    assert failed.status_code == 422
    assert [item["name"] for item in resources.list_connections()] == ["browser"]
