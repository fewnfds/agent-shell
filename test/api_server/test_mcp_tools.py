from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_shell.mcp_tools.publication import McpToolPublicationService
from agent_shell.runtime.request_snapshot import LANGGRAPH_MCP_TOOL_GRAPH_ID
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.mcp_tools import McpToolStore

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


def _command_graph_document(command_id: str) -> dict:
    document = _graph_document()
    document["definition"]["nodes"] = [
        {"id": "start", "type": "start", "type_version": 1, "config": {}},
        {
            "id": "command",
            "type": "command",
            "type_version": 1,
            "config": {"command_id": command_id},
        },
        {"id": "end", "type": "end", "type_version": 1, "config": {}},
    ]
    document["definition"]["edges"] = [
        {
            "id": "start-command",
            "source": "start",
            "source_handle": "next",
            "target": "command",
            "target_handle": "in",
        },
        {
            "id": "command-end",
            "source": "command",
            "source_handle": "next",
            "target": "end",
            "target_handle": "in",
        },
    ]
    return document


def _write_command_template(tmp_path: Path, key: str) -> None:
    package_dir = (
        tmp_path / "data" / "templates" / "workflow" / "command" / key
    )
    package_dir.mkdir(parents=True)
    (package_dir / "main.py").write_text(
        "def create_command():\n"
        "    async def command(state, runtime):\n"
        "        return {'activate': [], 'update': {}}\n"
        "    return command\n",
        encoding="utf-8",
    )


def _create_command(client: TestClient, *, name: str, key: str) -> dict:
    catalog = client.get(
        "/agent-shell/api/python-package-templates/command"
    ).json()["catalog"]
    template = next(item for item in catalog if item["key"] == key)
    return client.post(
        "/agent-shell/api/blocks/command",
        json={
            "name": name,
            "python_package": {"folder": ""},
            "python_package_template": {
                "key": template["key"],
                "revision": template["revision"],
            },
        },
    ).json()


def _publish_graph(client: TestClient, mcp_tool_id: str, document: dict) -> None:
    response = client.put(
        f"/agent-shell/api/mcp-tools/{mcp_tool_id}/graph",
        json=document,
    )
    assert response.status_code == 200, response.text


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


def test_application_startup_reconciles_mcp_tool_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reconciled: list[str] = []

    async def reconcile(_self: McpToolPublicationService) -> None:
        reconciled.append("reconciled")

    monkeypatch.setattr(McpToolPublicationService, "reconcile", reconcile)

    with make_client(tmp_path, monkeypatch):
        pass

    assert reconciled == ["reconciled"]


def test_invalid_draft_keeps_published_tool_available(
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
                "name": "draft_guard",
                "description": "Keeps its publication state.",
            },
        )
        mcp_tool = created.json()
        _publish_graph(client, mcp_tool["id"], _graph_document())
        assert client.get(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}"
        ).json()["enabled"] is True
        synced.clear()

        rejected = client.put(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}/draft",
            json={"definition": "not-an-mcp-tool-graph", "layout": {}},
        )
        stored = client.get(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}"
        ).json()
        graph = client.get(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}/graph"
        ).json()

    assert rejected.status_code == 422, rejected.text
    issues = rejected.json()["detail"]["validation"]["issues"]
    assert [issue["scope"] for issue in issues] == ["mcp_tool"]
    assert [issue["owner_id"] for issue in issues] == [mcp_tool["id"]]
    assert stored["enabled"] is True
    assert graph == _graph_document()
    assert synced == []


def test_metadata_update_reports_publication_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fail_publication = False

    async def sync(
        _self: McpToolPublicationService,
        _mcp_tool_id: str,
        *,
        enabled: bool,
    ) -> None:
        del enabled
        if fail_publication:
            raise RuntimeError("Agent Server is unavailable")

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)

    with make_client(tmp_path, monkeypatch) as client:
        created = client.post(
            "/agent-shell/api/mcp-tools",
            json={
                "name": "rename_guard",
                "description": "Before rename.",
            },
        )
        mcp_tool = created.json()
        _publish_graph(client, mcp_tool["id"], _graph_document())

        fail_publication = True
        response = client.put(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}",
            json={
                "name": "renamed_guard",
                "description": "After rename.",
            },
        )
        stored = client.get(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}"
        ).json()

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "mcp_tool_publication_failed"
    assert stored["name"] == "renamed_guard"
    assert stored["enabled"] is True


def test_deleting_referenced_command_demotes_published_mcp_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_command_template(tmp_path, "mcp-tool-command")
    withdrawn: list[str] = []
    synced: list[tuple[str, bool]] = []

    async def sync(
        _self: McpToolPublicationService,
        mcp_tool_id: str,
        *,
        enabled: bool,
    ) -> None:
        synced.append((mcp_tool_id, enabled))

    async def unpublish_disabled(_self: McpToolPublicationService) -> None:
        withdrawn.append("withdrawn")

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)
    monkeypatch.setattr(
        McpToolPublicationService,
        "unpublish_disabled",
        unpublish_disabled,
    )

    with make_client(tmp_path, monkeypatch) as client:
        command = _create_command(
            client,
            name="MCP Tool command",
            key="mcp-tool-command",
        )
        created = client.post(
            "/agent-shell/api/mcp-tools",
            json={
                "name": "demoted_tool",
                "description": "Depends on one Command.",
            },
        )
        mcp_tool = created.json()
        _publish_graph(
            client,
            mcp_tool["id"],
            _command_graph_document(command["id"]),
        )

        deleted = client.delete(
            f"/agent-shell/api/blocks/command/{command['id']}"
        )
        stored = client.get(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}"
        ).json()

    assert deleted.status_code == 200, deleted.text
    assert stored["enabled"] is False
    assert withdrawn == ["withdrawn"]


class _FakeAssistants:
    def __init__(self, assistants: list[dict[str, Any]]) -> None:
        self._assistants = assistants
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self.searches: list[dict[str, Any]] = []

    async def create(self, graph_id: str, **kwargs: Any) -> dict[str, Any]:
        self.created.append({"graph_id": graph_id, **kwargs})
        return {"assistant_id": kwargs.get("assistant_id")}

    async def update(
        self,
        assistant_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.updated.append((assistant_id, kwargs))
        return {"assistant_id": assistant_id}

    async def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.searches.append(kwargs)
        return list(self._assistants) if not kwargs.get("offset") else []


class _FakeAgentServer:
    def __init__(self, assistants: list[dict[str, Any]]) -> None:
        self.assistants = _FakeAssistants(assistants)

    async def aclose(self) -> None:
        return None


def _store(tmp_path: Path) -> tuple[McpToolStore, str, str]:
    store = McpToolStore(FileConfigRepository(tmp_path / "data"))
    published_id = store.new_id()
    store.save_item(
        published_id,
        {
            "name": "published_tool",
            "description": "Published.",
            "enabled": True,
        },
    )
    draft_id = store.new_id()
    store.save_item(
        draft_id,
        {
            "name": "draft_tool",
            "description": "Draft.",
            "enabled": False,
        },
    )
    return store, published_id, draft_id


def test_mcp_tool_publication_reconcile_aligns_official_assistants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, published_id, draft_id = _store(tmp_path)
    orphan_id = "44444444-4444-4444-8444-444444444444"
    server = _FakeAgentServer(
        [
            {
                "assistant_id": orphan_id,
                "name": "orphan_tool",
                "description": "",
                "metadata": {
                    "owner": "agent-shell",
                    "graph_kind": "mcp_tool",
                    "mcp_tool_id": orphan_id,
                    "agent_shell_mcp_tool": True,
                },
            }
        ]
    )
    monkeypatch.setattr(
        "agent_shell.mcp_tools.publication.get_client",
        lambda url=None: server,
    )

    asyncio.run(McpToolPublicationService(store).reconcile())

    created = {
        str(call["assistant_id"]): call["metadata"]["agent_shell_mcp_tool"]
        for call in server.assistants.created
    }
    assert created == {published_id: True, draft_id: False}
    assert server.assistants.searches[0]["graph_id"] == (
        LANGGRAPH_MCP_TOOL_GRAPH_ID
    )
    hidden = [
        (assistant_id, kwargs["metadata"]["agent_shell_mcp_tool"])
        for assistant_id, kwargs in server.assistants.updated
        if "metadata" in kwargs
    ]
    assert (orphan_id, False) in hidden


def test_mcp_tool_publication_reconcile_can_hide_orphans_from_empty_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = McpToolStore(FileConfigRepository(tmp_path / "data"))
    orphan_id = "44444444-4444-4444-8444-444444444444"
    server = _FakeAgentServer(
        [
            {
                "assistant_id": orphan_id,
                "name": "orphan_tool",
                "description": "",
                "metadata": {
                    "owner": "agent-shell",
                    "graph_kind": "mcp_tool",
                    "mcp_tool_id": orphan_id,
                    "agent_shell_mcp_tool": True,
                },
            }
        ]
    )
    monkeypatch.setattr(
        "agent_shell.mcp_tools.publication.get_client",
        lambda url=None: server,
    )

    asyncio.run(
        McpToolPublicationService(store).reconcile(include_empty=True)
    )

    hidden = [
        (assistant_id, kwargs["metadata"]["agent_shell_mcp_tool"])
        for assistant_id, kwargs in server.assistants.updated
        if "metadata" in kwargs
    ]
    assert hidden == [(orphan_id, False)]


def test_mcp_tool_publication_withdraws_disabled_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, published_id, draft_id = _store(tmp_path)
    synced: list[tuple[str, bool]] = []

    async def sync(
        _self: McpToolPublicationService,
        mcp_tool_id: str,
        *,
        enabled: bool,
    ) -> None:
        synced.append((mcp_tool_id, enabled))

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)

    asyncio.run(McpToolPublicationService(store).unpublish_disabled())

    assert synced == [(draft_id, False)]
    assert published_id not in {item[0] for item in synced}
