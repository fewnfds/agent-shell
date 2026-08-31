from __future__ import annotations

from agent_shell.storage.agent_configs import AgentConfigStore
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import CONFIG_VERSION, FileConfigRepository
from agent_shell.storage.workflows import WorkflowStore

from .app_support import make_client


def test_configuration_collection_views_keep_full_discovery_and_offer_summary_query(
    tmp_path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    for name, prompt in (("Alpha", "a" * 4_096), ("Beta", "b" * 4_096)):
        response = client.post(
            "/api/blocks/system-prompt",
            json={"name": name, "system_prompt": prompt},
        )
        assert response.status_code == 200

    full = client.get("/api/blocks/system-prompt")
    assert full.status_code == 200
    assert isinstance(full.json(), list)
    assert [item["name"] for item in full.json()] == ["Alpha", "Beta"]
    assert len(full.json()[0]["system_prompt"]) == 4_096

    explicit_full = client.get(
        "/api/blocks/system-prompt",
        params={"view": "full", "offset": 0},
    )
    assert explicit_full.status_code == 200
    assert explicit_full.json()["items"] == full.json()
    assert explicit_full.json()["total"] == 2

    summary = client.get(
        "/api/blocks/system-prompt",
        params={"view": "summary", "q": "a", "offset": 1, "limit": 1},
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["items"] == [{"id": full.json()[1]["id"], "name": "Beta"}]
    assert payload["total"] == 2
    assert payload["repository_id"]
    assert payload["repository_revision"] >= 1

    first_revision = payload["repository_revision"]
    created = client.post(
        "/api/blocks/system-prompt",
        json={"name": "Gamma", "system_prompt": "new"},
    )
    assert created.status_code == 200
    refreshed = client.get(
        "/api/blocks/system-prompt", params={"view": "summary"}
    ).json()
    assert refreshed["repository_revision"] > first_revision

    mcp_requirement = client.post(
        "/api/blocks/mcp-requirement",
        json={
            "name": "Browser access",
            "description": "Browser automation tools.",
            "namespace": "browser",
        },
    )
    assert mcp_requirement.status_code == 200
    mcp_summary_response = client.get(
        "/api/blocks/mcp-requirement", params={"view": "summary"}
    ).json()
    mcp_summary = mcp_summary_response["items"]
    assert mcp_summary == [{
        "id": mcp_requirement.json()["id"],
        "name": "Browser access",
        "namespace": "browser",
    }]

    options = client.get("/api/configuration-options")
    assert options.status_code == 200
    assert options.json()["repository_revision"] == mcp_summary_response["repository_revision"]
    assert options.json()["components"]["system-prompt"] == refreshed["items"]
    assert options.json()["components"]["mcp-requirement"] == mcp_summary
    assert "system_prompt" not in options.text
    assert "Browser automation tools." not in options.text

    for path in ("/api/main-agents", "/api/subagents", "/api/workflows"):
        collection = client.get(path, params={"view": "summary"})
        assert collection.status_code == 200
        assert set(collection.json()) == {
            "items",
            "total",
            "repository_id",
            "repository_revision",
        }

    parent_role_only = client.get("/api/workflows", params={"workflow_role": "parent"})
    assert parent_role_only.status_code == 200
    assert isinstance(parent_role_only.json(), list)

    deleted = client.post(
        "/api/blocks/system-prompt/delete",
        json={"q": "gamma"},
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": 1}
    assert len(client.get("/api/blocks/system-prompt").json()) == 2
    assert client.post(
        "/api/blocks/system-prompt/delete",
        json={"ids": [full.json()[0]["id"]], "q": "alpha"},
    ).status_code == 422

    no_match_revision = client.get("/api/configuration-options").json()[
        "repository_revision"
    ]
    for path in ("/api/main-agents/delete", "/api/subagents/delete", "/api/workflows/delete"):
        no_match = client.post(path, json={"q": "does-not-exist"})
        assert no_match.status_code == 200
        assert no_match.json() == {"deleted": 0}
    assert (
        client.get("/api/configuration-options").json()["repository_revision"]
        == no_match_revision
    )

    parent = client.post(
        "/api/workflows",
        json={"name": "Shared parent", "workflow_role": "parent"},
    )
    child = client.post(
        "/api/workflows",
        json={"name": "Shared child", "workflow_role": "child"},
    )
    assert parent.status_code == 200
    assert child.status_code == 200
    deleted_parent = client.post(
        "/api/workflows/delete",
        json={"q": "shared", "workflow_role": "parent"},
    )
    assert deleted_parent.status_code == 200
    assert deleted_parent.json() == {"deleted": 1}
    remaining = client.get("/api/workflows").json()
    assert [item["id"] for item in remaining] == [child.json()["id"]]


def test_configuration_stores_read_owned_sections_without_full_snapshot(
    tmp_path, monkeypatch
) -> None:
    block_id = "10000000-0000-4000-8000-000000000001"
    main_agent_id = "10000000-0000-4000-8000-000000000002"
    workflow_id = "10000000-0000-4000-8000-000000000003"
    repository = FileConfigRepository.from_snapshot(
        tmp_path,
        {
            "config_version": CONFIG_VERSION,
            "components": {
                "system-prompt": [
                    {
                        "id": block_id,
                        "name": "Prompt",
                        "system_prompt": "large payload",
                    }
                ]
            },
            "main_agents": [{"id": main_agent_id, "name": "Agent"}],
            "subagents": [],
            "workflows": [
                {
                    "id": workflow_id,
                    "name": "Workflow",
                    "workflow_role": "parent",
                    "description": "",
                    "checkpointer_id": None,
                    "workflow_event_output_id": None,
                    "cancel_on_upstream_termination": True,
                    "recursion_limit": 100,
                    "execution_timeout_seconds": 300,
                    "max_concurrency": 100,
                    "enabled": False,
                    "definition": {"nodes": [], "edges": []},
                    "layout": {"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
                }
            ],
        },
    )

    def reject_full_snapshot():
        raise AssertionError("ordinary Store reads must not call config()")

    monkeypatch.setattr(repository, "config", reject_full_snapshot)
    blocks = BlockStore(repository)
    agents = AgentConfigStore(repository)
    workflows = WorkflowStore(repository)

    assert blocks.list_block_summaries("system-prompt") == [
        {"id": block_id, "name": "Prompt"}
    ]
    assert blocks.get_block("system-prompt", block_id)["system_prompt"] == "large payload"
    assert agents.get_item("main_agents", main_agent_id)["name"] == "Agent"
    assert workflows.list_item_summaries() == [
        {
            "id": workflow_id,
            "name": "Workflow",
            "workflow_role": "parent",
            "description": "",
            "enabled": False,
        }
    ]
    assert workflows.get_graph(workflow_id) is not None
