from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_shell.mcp_tools.publication import McpToolPublicationService

from .support import make_client


SCHEMA_SOURCE = """
from pydantic import BaseModel, ConfigDict


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str


class State(Input):
    answer: str = ""


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    answer: str
"""


def _graph_document() -> dict:
    return {
        "definition": {
            "schema_version": 1,
            "state_contract": "agent-shell.workflow.control.v1",
            "schema_source": SCHEMA_SOURCE,
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "type_version": 1,
                    "config": {},
                },
                {
                    "id": "end",
                    "type": "end",
                    "type_version": 1,
                    "config": {},
                },
            ],
            "edges": [
                {
                    "id": "start-end",
                    "source": "start",
                    "source_handle": "next",
                    "target": "end",
                    "target_handle": "in",
                }
            ],
        },
        "layout": {
            "nodes": {
                "start": {"x": 80, "y": 160},
                "end": {"x": 640, "y": 160},
            },
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    }


def test_mcp_tool_draft_publish_and_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synced: list[tuple[str, bool]] = []

    async def sync(
        _self: McpToolPublicationService,
        mcp_tool_id: str,
        *,
        enabled: bool,
    ) -> None:
        synced.append((mcp_tool_id, enabled))

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)

    with make_client(tmp_path, monkeypatch) as client:
        created = client.post(
            "/agent-shell/api/mcp-tools",
            json={
                "name": "echo_topic",
                "description": "Echo a topic.",
            },
        )
        assert created.status_code == 200, created.text
        mcp_tool = created.json()
        assert mcp_tool["enabled"] is False

        options = client.get("/agent-shell/api/configuration-options")
        assert options.status_code == 200, options.text
        assert [
            item["id"] for item in options.json()["mcp_tools"]
        ] == [mcp_tool["id"]]

        graph_url = (
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}/graph"
        )
        draft = client.put(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}/draft",
            json=_graph_document(),
        )
        assert draft.status_code == 200, draft.text
        assert client.get(graph_url).json() == _graph_document()

        published = client.put(graph_url, json=_graph_document())
        assert published.status_code == 200, published.text
        assert client.get(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}"
        ).json()["enabled"] is True
        assert synced == [
            (mcp_tool["id"], False),
            (mcp_tool["id"], True),
        ]

        deleted = client.delete(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}"
        )
        assert deleted.status_code == 200, deleted.text
        assert synced[-1] == (mcp_tool["id"], False)


def test_mcp_tool_validation_returns_resource_scoped_issues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def sync(
        _self: McpToolPublicationService,
        _mcp_tool_id: str,
        *,
        enabled: bool,
    ) -> None:
        del enabled

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)

    with make_client(tmp_path, monkeypatch) as client:
        mcp_tool = client.post(
            "/agent-shell/api/mcp-tools",
            json={
                "name": "bad_schema",
                "description": "",
            },
        ).json()
        document = _graph_document()
        document["definition"]["schema_source"] = "class State("
        response = client.post(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}/validate",
            json=document,
        )
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["valid"] is False
        assert report["issues"][0]["code"] == "mcp_tool.schema_invalid"
        assert report["issues"][0]["scope"] == "mcp_tool"


def test_mcp_tool_update_requires_an_existing_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def sync(
        _self: McpToolPublicationService,
        _mcp_tool_id: str,
        *,
        enabled: bool,
    ) -> None:
        del enabled

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)

    with make_client(tmp_path, monkeypatch) as client:
        response = client.put(
            "/agent-shell/api/mcp-tools/"
            "11111111-1111-4111-8111-111111111111",
            json={
                "name": "missing_tool",
                "description": "",
            },
        )
        assert response.status_code == 404, response.text
        assert response.json()["detail"]["code"] == "mcp_tool_not_found"
