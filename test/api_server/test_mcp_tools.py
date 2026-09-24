from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_shell.mcp_tools.publication import McpToolPublicationService
from agent_shell.runtime.request_snapshot import LANGGRAPH_MCP_TOOL_GRAPH_ID
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.mcp_tools import McpToolStore

from .support import create_python_schema, make_client


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

STATE_ONLY_SCHEMA_SOURCE = """
from pydantic import BaseModel


class State(BaseModel):
    topic: str
"""


def _graph_document() -> dict:
    return {
        "definition": {
            "schema_version": 1,
            "state_contract": "agent-shell.workflow.control.v1",
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


def _create_mcp_tool(
    client: TestClient,
    *,
    name: str,
    description: str = "",
    python_schema_id: str | None = None,
) -> dict:
    payload = {
        "name": name,
        "description": description,
    }
    if python_schema_id is not None:
        payload["python_schema_id"] = python_schema_id
    response = client.post(
        "/agent-shell/api/mcp-tools",
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


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
        python_schema = create_python_schema(
            client,
            name="Echo schema",
            source=SCHEMA_SOURCE,
        )
        mcp_tool = _create_mcp_tool(
            client,
            name="echo_topic",
            description="Echo a topic.",
            python_schema_id=python_schema["id"],
        )
        assert mcp_tool["enabled"] is False
        assert mcp_tool["python_schema_id"] == python_schema["id"]

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
        python_schema = create_python_schema(
            client,
            name="State-only schema",
            source=STATE_ONLY_SCHEMA_SOURCE,
        )
        mcp_tool = _create_mcp_tool(
            client,
            name="bad_schema",
            python_schema_id=python_schema["id"],
        )
        document = _graph_document()
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


def test_mcp_tool_rejects_a_missing_python_schema_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_id = "00000000-0000-4000-8000-000000000074"
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/agent-shell/api/mcp-tools",
            json={
                "name": "missing_schema",
                "description": "",
                "python_schema_id": missing_id,
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "python_schema_not_found"


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
        python_schema = create_python_schema(
            client,
            name="Draft guard schema",
            source=SCHEMA_SOURCE,
        )
        mcp_tool = _create_mcp_tool(
            client,
            name="draft_guard",
            description="Keeps its publication state.",
            python_schema_id=python_schema["id"],
        )
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
        python_schema = create_python_schema(
            client,
            name="Rename guard schema",
            source=SCHEMA_SOURCE,
        )
        mcp_tool = _create_mcp_tool(
            client,
            name="rename_guard",
            description="Before rename.",
            python_schema_id=python_schema["id"],
        )
        _publish_graph(client, mcp_tool["id"], _graph_document())

        fail_publication = True
        response = client.put(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}",
            json={
                "name": "renamed_guard",
                "description": "After rename.",
                "python_schema_id": python_schema["id"],
            },
        )
        stored = client.get(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}"
        ).json()
        repair_diagnostics = client.app.state.runtime_diagnostics.snapshot()["entries"]

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "mcp_tool_publication_failed"
    assert stored["name"] == "rename_guard"
    assert stored["description"] == "Before rename."
    assert stored["enabled"] is True
    assert any(
        entry["code"] == "mcp_tool_publication_repair_failed"
        and "Agent Server is unavailable" in entry["summary"]
        for entry in repair_diagnostics
    )


def test_metadata_update_realigns_a_partially_updated_assistant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote_names: dict[str, str] = {}
    fail_after_remote_update = False

    async def sync(self: McpToolPublicationService, mcp_tool_id: str, *, enabled: bool):
        nonlocal fail_after_remote_update
        del enabled
        item = self._store.get_item(mcp_tool_id)
        assert item is not None
        remote_names[mcp_tool_id] = item["name"]
        if fail_after_remote_update:
            fail_after_remote_update = False
            raise RuntimeError("Assistant update was applied before the response failed")

    async def reconcile(self: McpToolPublicationService) -> None:
        for item in self._store.list_items():
            await self._sync(item["id"], enabled=item["enabled"])

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)
    monkeypatch.setattr(McpToolPublicationService, "reconcile", reconcile)

    with make_client(tmp_path, monkeypatch) as client:
        schema = create_python_schema(client, name="Partial sync schema", source=SCHEMA_SOURCE)
        tool = _create_mcp_tool(
            client,
            name="original_remote_name",
            python_schema_id=schema["id"],
        )
        _publish_graph(client, tool["id"], _graph_document())
        fail_after_remote_update = True

        response = client.put(
            f"/agent-shell/api/mcp-tools/{tool['id']}",
            json={
                "name": "partially_applied_name",
                "description": "Candidate",
                "python_schema_id": schema["id"],
            },
        )
        stored = client.get(f"/agent-shell/api/mcp-tools/{tool['id']}").json()

    assert response.status_code == 502, response.text
    assert stored["name"] == "original_remote_name"
    assert remote_names[tool["id"]] == "original_remote_name"


def test_published_mcp_tool_metadata_revalidates_its_current_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def sync(_self, _mcp_tool_id, *, enabled):
        del enabled

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)
    with make_client(tmp_path, monkeypatch) as client:
        complete = create_python_schema(
            client,
            name="Complete MCP schema",
            source=SCHEMA_SOURCE,
        )
        incomplete = create_python_schema(
            client,
            name="State-only MCP schema",
            source=STATE_ONLY_SCHEMA_SOURCE,
        )
        tool = _create_mcp_tool(
            client,
            name="metadata_guard",
            python_schema_id=complete["id"],
        )
        _publish_graph(client, tool["id"], _graph_document())
        rejected = client.put(
            f"/agent-shell/api/mcp-tools/{tool['id']}",
            json={
                "name": "metadata_guard",
                "description": "Candidate",
                "python_schema_id": incomplete["id"],
            },
        )
        stored = client.get(f"/agent-shell/api/mcp-tools/{tool['id']}").json()

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"]["validation"]["issues"][0]["code"] == (
        "mcp_tool.schema_invalid"
    )
    assert stored["enabled"] is True
    assert stored["python_schema_id"] == complete["id"]
    assert stored["description"] == ""


def test_failed_graph_publication_restores_previous_published_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fail_publication = False

    async def sync(_self, _mcp_tool_id, *, enabled):
        del enabled
        if fail_publication:
            raise RuntimeError("Agent Server is unavailable")

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)
    with make_client(tmp_path, monkeypatch) as client:
        schema = create_python_schema(
            client,
            name="Graph rollback schema",
            source=SCHEMA_SOURCE,
        )
        tool = _create_mcp_tool(
            client,
            name="graph_rollback",
            python_schema_id=schema["id"],
        )
        original = _graph_document()
        _publish_graph(client, tool["id"], original)
        replacement = _graph_document()
        replacement["layout"]["nodes"]["end"]["x"] = 720

        fail_publication = True
        rejected = client.put(
            f"/agent-shell/api/mcp-tools/{tool['id']}/graph",
            json=replacement,
        )
        stored = client.get(f"/agent-shell/api/mcp-tools/{tool['id']}").json()
        graph = client.get(
            f"/agent-shell/api/mcp-tools/{tool['id']}/graph"
        ).json()

    assert rejected.status_code == 502, rejected.text
    assert stored["enabled"] is True
    assert graph == original


def test_failed_first_graph_publication_realigns_a_partially_enabled_assistant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote_enabled: dict[str, bool] = {}
    fail_after_remote_update = False

    async def sync(
        self: McpToolPublicationService,
        mcp_tool_id: str,
        *,
        enabled: bool,
    ) -> None:
        nonlocal fail_after_remote_update
        remote_enabled[mcp_tool_id] = enabled
        if fail_after_remote_update:
            fail_after_remote_update = False
            raise RuntimeError(
                "Assistant enable was applied before the response failed"
            )

    async def reconcile(self: McpToolPublicationService) -> None:
        for item in self._store.list_items():
            await self._sync(item["id"], enabled=item["enabled"])

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)
    monkeypatch.setattr(McpToolPublicationService, "reconcile", reconcile)

    with make_client(tmp_path, monkeypatch) as client:
        tool = _create_mcp_tool(client, name="partial_graph_publish")
        fail_after_remote_update = True

        rejected = client.put(
            f"/agent-shell/api/mcp-tools/{tool['id']}/graph",
            json=_graph_document(),
        )
        stored = client.get(f"/agent-shell/api/mcp-tools/{tool['id']}").json()

    assert rejected.status_code == 502, rejected.text
    assert stored["enabled"] is False
    assert remote_enabled[tool["id"]] is False


def test_failed_draft_store_commit_reconciles_the_published_assistant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synced: list[tuple[str, bool]] = []
    fail_draft_commit = False
    save_graph = McpToolStore.save_graph_and_enabled

    async def sync(_self, mcp_tool_id, *, enabled):
        synced.append((mcp_tool_id, enabled))

    async def reconcile(self: McpToolPublicationService) -> None:
        for item in await asyncio.to_thread(self._store.list_items):
            await self._sync(str(item["id"]), enabled=bool(item["enabled"]))

    def save_graph_with_failure(self, item_id, document, *, enabled, **kwargs):
        if fail_draft_commit and not enabled:
            raise OSError("repository write failed")
        return save_graph(
            self,
            item_id,
            document,
            enabled=enabled,
            **kwargs,
        )

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)
    monkeypatch.setattr(McpToolPublicationService, "reconcile", reconcile)
    monkeypatch.setattr(
        McpToolStore,
        "save_graph_and_enabled",
        save_graph_with_failure,
    )

    with make_client(tmp_path, monkeypatch) as client:
        tool = _create_mcp_tool(client, name="draft_commit_guard")
        original = _graph_document()
        _publish_graph(client, tool["id"], original)
        synced.clear()
        fail_draft_commit = True

        with pytest.raises(OSError, match="repository write failed"):
            client.put(
                f"/agent-shell/api/mcp-tools/{tool['id']}/draft",
                json=_graph_document(),
            )
        stored = client.get(f"/agent-shell/api/mcp-tools/{tool['id']}").json()
        graph = client.get(
            f"/agent-shell/api/mcp-tools/{tool['id']}/graph"
        ).json()

    assert stored["enabled"] is True
    assert graph == original
    assert synced == [(tool["id"], False), (tool["id"], True)]


def test_partial_bulk_withdrawal_reconciles_all_surviving_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synced: list[tuple[str, bool]] = []
    fail_tool_id = ""

    async def sync(_self, mcp_tool_id, *, enabled):
        synced.append((mcp_tool_id, enabled))
        if not enabled and mcp_tool_id == fail_tool_id:
            raise RuntimeError("withdrawal failed")

    async def reconcile(self: McpToolPublicationService) -> None:
        for item in await asyncio.to_thread(self._store.list_items):
            await self._sync(str(item["id"]), enabled=bool(item["enabled"]))

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)
    monkeypatch.setattr(McpToolPublicationService, "reconcile", reconcile)

    with make_client(tmp_path, monkeypatch) as client:
        first = _create_mcp_tool(client, name="bulk_guard_a")
        second = _create_mcp_tool(client, name="bulk_guard_b")
        _publish_graph(client, first["id"], _graph_document())
        _publish_graph(client, second["id"], _graph_document())
        synced.clear()
        fail_tool_id = second["id"]

        rejected = client.post(
            "/agent-shell/api/mcp-tools/delete",
            json={"ids": [first["id"], second["id"]]},
        )
        stored = {
            item["id"]: item
            for item in client.get("/agent-shell/api/mcp-tools").json()
        }

    assert rejected.status_code == 502, rejected.text
    assert all(stored[item_id]["enabled"] for item_id in (first["id"], second["id"]))
    assert synced == [
        (first["id"], False),
        (second["id"], False),
        (first["id"], True),
        (second["id"], True),
    ]


def test_delete_does_not_commit_to_a_repository_activated_during_withdrawal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch_repository_id = ""
    switch_on_withdrawal = False

    async def sync(self: McpToolPublicationService, _item_id, *, enabled):
        if switch_on_withdrawal and not enabled:
            self._store._repository.switch_repository(switch_repository_id)

    async def reconcile(_self: McpToolPublicationService) -> None:
        return None

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)
    monkeypatch.setattr(McpToolPublicationService, "reconcile", reconcile)

    with make_client(tmp_path, monkeypatch) as client:
        default_repository_id = client.get(
            "/agent-shell/api/configuration-repositories"
        ).json()["active_id"]
        alternate = client.post(
            "/agent-shell/api/configuration-repositories",
            json={"name": "Delete race target"},
        )
        assert alternate.status_code == 200, alternate.text
        switch_repository_id = alternate.json()["id"]
        tool = _create_mcp_tool(client, name="repository_delete_guard")
        _publish_graph(client, tool["id"], _graph_document())
        switch_on_withdrawal = True

        rejected = client.delete(f"/agent-shell/api/mcp-tools/{tool['id']}")
        alternate_items = client.get("/agent-shell/api/mcp-tools").json()
        client.app.state.mcp_tool_store._repository.switch_repository(
            default_repository_id
        )
        original = client.get(f"/agent-shell/api/mcp-tools/{tool['id']}")

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "configuration_repository_changed"
    assert alternate_items == []
    assert original.status_code == 200, original.text
    assert original.json()["enabled"] is True


def test_repository_activation_waits_for_an_active_publication_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    block_publication = False
    publication_started = threading.Event()
    release_publication = threading.Event()

    async def sync(
        _self: McpToolPublicationService,
        _item_id: str,
        *,
        enabled: bool,
    ) -> None:
        if block_publication and enabled:
            publication_started.set()
            assert await asyncio.to_thread(release_publication.wait, 5)

    async def reconcile(_self: McpToolPublicationService) -> None:
        return None

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)
    monkeypatch.setattr(McpToolPublicationService, "reconcile", reconcile)

    with make_client(tmp_path, monkeypatch) as client:
        alternate = client.post(
            "/agent-shell/api/configuration-repositories",
            json={"name": "Publication command target"},
        )
        assert alternate.status_code == 200, alternate.text
        alternate_id = alternate.json()["id"]
        tool = _create_mcp_tool(client, name="publication_command_guard")
        _publish_graph(client, tool["id"], _graph_document())
        replacement = _graph_document()
        replacement["layout"]["nodes"]["end"]["x"] = 720

        repository = client.app.state.mcp_tool_store._repository
        original_switch = repository.switch_repository
        repository_switched = threading.Event()

        def observed_switch(repository_id: str):
            result = original_switch(repository_id)
            if repository_id == alternate_id:
                repository_switched.set()
            return result

        monkeypatch.setattr(repository, "switch_repository", observed_switch)
        block_publication = True

        with ThreadPoolExecutor(max_workers=2) as executor:
            publishing = executor.submit(
                client.put,
                f"/agent-shell/api/mcp-tools/{tool['id']}/graph",
                json=replacement,
            )
            assert publication_started.wait(timeout=5)
            activating = executor.submit(
                client.post,
                "/agent-shell/api/configuration-repositories/"
                f"{alternate_id}/activate",
            )
            assert not repository_switched.wait(timeout=0.2)
            release_publication.set()
            published = publishing.result(timeout=5)
            activated = activating.result(timeout=5)

        active_id = client.get(
            "/agent-shell/api/configuration-repositories"
        ).json()["active_id"]

    assert published.status_code == 200, published.text
    assert activated.status_code == 200, activated.text
    assert active_id == alternate_id


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
        python_schema = create_python_schema(
            client,
            name="Demotion schema",
            source=SCHEMA_SOURCE,
        )
        command = _create_command(
            client,
            name="MCP Tool command",
            key="mcp-tool-command",
        )
        mcp_tool = _create_mcp_tool(
            client,
            name="demoted_tool",
            description="Depends on one Command.",
            python_schema_id=python_schema["id"],
        )
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


def test_deleting_referenced_python_schema_demotes_mcp_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    withdrawn: list[str] = []

    async def sync(
        _self: McpToolPublicationService,
        _mcp_tool_id: str,
        *,
        enabled: bool,
    ) -> None:
        del enabled

    async def unpublish_disabled(_self: McpToolPublicationService) -> None:
        withdrawn.append("withdrawn")

    monkeypatch.setattr(McpToolPublicationService, "_sync", sync)
    monkeypatch.setattr(
        McpToolPublicationService,
        "unpublish_disabled",
        unpublish_disabled,
    )

    with make_client(tmp_path, monkeypatch) as client:
        python_schema = create_python_schema(
            client,
            name="Referenced MCP schema",
            source=SCHEMA_SOURCE,
        )
        mcp_tool = _create_mcp_tool(
            client,
            name="schema_dependent_tool",
            python_schema_id=python_schema["id"],
        )
        _publish_graph(client, mcp_tool["id"], _graph_document())

        deleted = client.delete(
            "/agent-shell/api/blocks/python-schema/"
            f"{python_schema['id']}"
        )
        stored = client.get(
            f"/agent-shell/api/mcp-tools/{mcp_tool['id']}"
        ).json()

    assert deleted.status_code == 200, deleted.text
    assert stored["python_schema_id"] == python_schema["id"]
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


def test_mcp_tool_publication_reconcile_hides_orphans_from_empty_store(
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

    asyncio.run(McpToolPublicationService(store).reconcile())

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
