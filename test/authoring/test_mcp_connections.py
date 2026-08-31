from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_shell.api.mcp_connections import build_mcp_connection_router
from agent_shell.mcp.importing import normalize_mcp_servers_import
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.environment import (
    MCP_CONNECTION_ENVIRONMENT_OWNER,
    InstanceEnvironmentStore,
)
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.mcp_connections import McpResourceStore


CONNECTION_ID = "11111111-1111-4111-8111-111111111111"
REPOSITORY_ID = "22222222-2222-4222-8222-222222222222"
REQUIREMENT_ID = "33333333-3333-4333-8333-333333333333"


def stdio_connection_payload(name: str = "Browser MCP") -> dict:
    return {
        "name": name,
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@playwright/mcp@latest"],
        "cwd": None,
        "env": {
            "ACCESS_TOKEN": {"source": "secret", "value": "top-secret-token"},
            "LOG_LEVEL": {"source": "literal", "value": "warning"},
        },
    }


def test_mcp_connection_secret_slots_are_write_only_and_binding_is_scoped(
    tmp_path: Path,
) -> None:
    environment = InstanceEnvironmentStore(tmp_path / "config" / "agent-shell.env")
    resources = McpResourceStore(tmp_path)

    saved = resources.save_connection(CONNECTION_ID, stdio_connection_payload())

    assert saved["env"] == {
        "ACCESS_TOKEN": {"source": "secret", "status": "masked"},
        "LOG_LEVEL": {"source": "literal", "value": "warning"},
    }
    yaml_text = (
        tmp_path / "config" / "mcp-connections" / f"{CONNECTION_ID}.yaml"
    ).read_text(encoding="utf-8")
    assert "top-secret-token" not in yaml_text
    resolved = resources.resolve_connection(CONNECTION_ID)
    assert resolved["env"] == {
        "ACCESS_TOKEN": "top-secret-token",
        "LOG_LEVEL": "warning",
    }
    assert list(
        environment.owned_values(MCP_CONNECTION_ENVIRONMENT_OWNER).values()
    ) == ["top-secret-token"]

    resources.set_binding(REPOSITORY_ID, REQUIREMENT_ID, CONNECTION_ID)
    assert resources.get_binding(REPOSITORY_ID, REQUIREMENT_ID) == CONNECTION_ID
    assert resources.delete_connection(CONNECTION_ID) is True
    assert resources.get_binding(REPOSITORY_ID, REQUIREMENT_ID) is None
    assert environment.owned_values(MCP_CONNECTION_ENVIRONMENT_OWNER) == {}


def test_masked_secret_survives_connection_update_and_copy(tmp_path: Path) -> None:
    resources = McpResourceStore(tmp_path)
    saved = resources.save_connection(CONNECTION_ID, stdio_connection_payload())

    updated = resources.save_connection(
        CONNECTION_ID,
        {**saved, "name": "Updated Browser MCP"},
    )
    copied = resources.copy_connection(
        CONNECTION_ID,
        "Copied Browser MCP",
    )

    assert updated["env"]["ACCESS_TOKEN"]["status"] == "masked"
    assert copied["env"]["ACCESS_TOKEN"]["status"] == "masked"
    assert resources.resolve_connection(CONNECTION_ID)["env"]["ACCESS_TOKEN"] == "top-secret-token"
    assert resources.resolve_connection(copied["id"])["env"]["ACCESS_TOKEN"] == "top-secret-token"


def test_mcp_servers_import_normalizes_aliases_and_requires_explicit_values() -> None:
    document = {
        "mcpServers": {
            "browser": {
                "command": "npx",
                "args": ["-y", "@playwright/mcp@latest"],
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
    assert normalized[0]["env"]["TOKEN"] == {
        "source": "literal",
        "value": "secret",
    }
    assert normalized[1]["transport"] == "http"
    assert normalized[1]["headers"]["Authorization"] == {
        "source": "secret",
        "value": "Bearer token",
    }

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


def test_mcp_connection_api_imports_atomically_and_maps_requirement(
    tmp_path: Path,
) -> None:
    repository = FileConfigRepository.empty(tmp_path)
    blocks = BlockStore(repository)
    resources = McpResourceStore(tmp_path)
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
                "args": ["-y", "@playwright/mcp@latest"],
                "env": {"TOKEN": "secret"},
            }
        }
    }

    preview = client.post(
        "/api/mcp-connections/import/preview",
        json={"document": document},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["connections"][0]["values"] == [
        {"target": "env", "name": "TOKEN", "source": "secret"}
    ]

    imported = client.post(
        "/api/mcp-connections/import",
        json={"document": document},
    )
    assert imported.status_code == 200, imported.text
    connection_id = imported.json()[0]["id"]
    assert imported.json()[0]["env"]["TOKEN"]["status"] == "masked"

    requirements = client.get("/api/mcp-requirements").json()
    assert requirements[0]["binding"] is None
    bound = client.put(
        f"/api/mcp-requirements/{requirement_id}/binding",
        json={"connection_id": connection_id},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["binding"] == connection_id

    failed = client.post(
        "/api/mcp-connections/import",
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
