from __future__ import annotations

from uuid import UUID

from agent_shell.storage.file_config import FileConfigRepository

from .reference_support import *


def test_main_agent_and_subagent_copy_create_server_ids_and_preserve_sources(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    required = create_blocks(
        client, "copy-required", REQUIRED_TYPES
    )
    subagent = client.post(
        "/agent-shell/api/subagents",
        json=subagent_payload("Copy source Subagent", name="saved_worker"),
    ).json()
    main_agent = client.post(
        "/agent-shell/api/main-agents",
        json={
            "name": "Copy source Main Agent",
            "capability_refs": references(required, REQUIRED_TYPES),
            "subagents": [{"subagent_id": subagent["id"]}],
        },
    ).json()

    main_agent_copy_response = client.post(
        f"/agent-shell/api/main-agents/{main_agent['id']}/copy",
        json={"name": "  Copied Main Agent  "},
    )
    subagent_copy_response = client.post(
        f"/agent-shell/api/subagents/{subagent['id']}/copy",
        json={"component_name": "Copied Subagent"},
    )

    assert main_agent_copy_response.status_code == 200, main_agent_copy_response.text
    assert subagent_copy_response.status_code == 200, subagent_copy_response.text
    main_agent_copy = main_agent_copy_response.json()
    subagent_copy = subagent_copy_response.json()
    assert UUID(main_agent_copy["id"]) and main_agent_copy["id"] != main_agent["id"]
    assert UUID(subagent_copy["id"]) and subagent_copy["id"] != subagent["id"]
    assert main_agent_copy["name"] == "Copied Main Agent"
    assert subagent_copy["component_name"] == "Copied Subagent"
    assert subagent_copy["name"] == subagent["name"]
    assert main_agent_copy["capability_refs"] == main_agent["capability_refs"]
    assert main_agent_copy["subagents"] == main_agent["subagents"]
    assert subagent_copy["settings"] == subagent["settings"]
    assert client.get(f"/agent-shell/api/main-agents/{main_agent['id']}").json() == main_agent
    assert client.get(f"/agent-shell/api/subagents/{subagent['id']}").json() == subagent


def test_component_bulk_delete_preserves_references_for_repository_validation(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    required = create_blocks(
        client, "bulk-required", (*REQUIRED_TYPES, "system-prompt")
    )
    second = client.post(
        "/agent-shell/api/blocks/system-prompt",
        json=block_payload("system-prompt", "bulk-second-system-prompt"),
    ).json()
    main_agent = client.post(
        "/agent-shell/api/main-agents",
        json={
            "name": "Bulk owner",
            "capability_refs": references(
                required, (*REQUIRED_TYPES, "system-prompt")
            ),
        },
    ).json()
    ids = [required["system-prompt"]["id"], second["id"]]

    deleted = client.post("/agent-shell/api/blocks/system-prompt/delete", json={"ids": ids})
    assert deleted.json() == {"deleted": 2}
    assert all(
        client.get(f"/agent-shell/api/blocks/system-prompt/{item_id}").status_code == 404
        for item_id in ids
    )
    stored = client.get(f"/agent-shell/api/main-agents/{main_agent['id']}").json()
    assert next(
        item for item in stored["capability_refs"] if item["type"] == "system-prompt"
    )["block_id"] == required["system-prompt"]["id"]
    issues = [
        issue
        for issue in client.get("/agent-shell/api/validation/repository").json()["issues"]
        if issue["owner_id"] == main_agent["id"]
        and issue["code"] == "configuration.reference_not_found"
    ]
    assert len(issues) == 1
    assert issues[0]["message_args"]["reference_id"] == required[
        "system-prompt"
    ]["id"]

    assert client.delete(f"/agent-shell/api/main-agents/{main_agent['id']}").status_code == 200
    assert client.get("/agent-shell/api/blocks/system-prompt").json() == []


def test_agent_configuration_bulk_delete_uses_one_command_per_category(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    required = create_blocks(
        client, "bulk-agents", REQUIRED_TYPES
    )
    main_agent_ids = []
    subagent_ids = []
    for index in range(2):
        main_agent_ids.append(client.post(
            "/agent-shell/api/main-agents",
            json={
                "name": f"Bulk Main Agent {index}",
                "capability_refs": references(required, REQUIRED_TYPES),
            },
        ).json()["id"])
        subagent_ids.append(client.post(
            "/agent-shell/api/subagents",
            json=subagent_payload(
                f"Bulk Subagent {index}",
                name=f"bulk_worker_{index}",
            ),
        ).json()["id"])

    assert client.post(
        "/agent-shell/api/main-agents/delete", json={"ids": main_agent_ids}
    ).json() == {"deleted": 2}
    assert client.post(
        "/agent-shell/api/subagents/delete", json={"ids": subagent_ids}
    ).json() == {"deleted": 2}
    assert client.get("/agent-shell/api/main-agents").json() == []
    assert client.get("/agent-shell/api/subagents").json() == []


def test_agent_config_copy_rejects_duplicate_names_without_writing(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    required = create_blocks(
        client, "duplicate-copy", REQUIRED_TYPES
    )
    main_agent = client.post(
        "/agent-shell/api/main-agents",
        json={
            "name": "Duplicate Main Agent",
            "capability_refs": references(required, REQUIRED_TYPES),
        },
    ).json()
    subagent = client.post(
        "/agent-shell/api/subagents",
        json=subagent_payload("Duplicate Subagent", name="duplicate_worker"),
    ).json()

    main_agent_copy = client.post(
        f"/agent-shell/api/main-agents/{main_agent['id']}/copy",
        json={"name": main_agent["name"]},
    )
    subagent_copy = client.post(
        f"/agent-shell/api/subagents/{subagent['id']}/copy",
        json={"component_name": subagent["component_name"]},
    )

    assert main_agent_copy.status_code == 409
    assert subagent_copy.status_code == 409
    assert client.get("/agent-shell/api/main-agents").json() == [main_agent]
    assert client.get("/agent-shell/api/subagents").json() == [subagent]


def test_agent_config_copy_returns_not_found_without_writing(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)

    main_agent_copy = client.post(
        "/agent-shell/api/main-agents/missing/copy", json={"name": "Missing Main Agent copy"}
    )
    subagent_copy = client.post(
        "/agent-shell/api/subagents/missing/copy",
        json={"component_name": "Missing Subagent copy"},
    )

    assert main_agent_copy.status_code == 404
    assert subagent_copy.status_code == 404
    assert client.get("/agent-shell/api/main-agents").json() == []
    assert client.get("/agent-shell/api/subagents").json() == []


def test_agent_config_copy_revalidates_invalid_stored_sources_before_writing(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    required = create_blocks(
        client, "invalid-copy", REQUIRED_TYPES
    )
    main_agent = client.post(
        "/agent-shell/api/main-agents",
        json={
            "name": "Invalid stored Main Agent",
            "capability_refs": references(required, REQUIRED_TYPES),
        },
    ).json()
    subagent = client.post(
        "/agent-shell/api/subagents",
        json=subagent_payload("Invalid stored Subagent", name="invalid_worker"),
    ).json()
    client.close()
    configuration = FileConfigRepository(tmp_path / "data")

    def corrupt_stored_sources(config: dict) -> None:
        for record in config["main_agents"]:
            if record.get("id") == main_agent["id"]:
                record["capability_refs"][0]["block_id"] = (
                    "00000000-0000-4000-8000-000000000098"
                )
        for record in config["subagents"]:
            if record.get("id") == subagent["id"]:
                record["settings"]["capability_overrides"] = [
                    {
                        "type": "model-requirement",
                        "mode": "replace",
                        "block_id": "00000000-0000-4000-8000-000000000098",
                    }
                ]

    configuration.update_config(corrupt_stored_sources)
    client = make_client(tmp_path, monkeypatch)

    before_main_agent = client.get(f"/agent-shell/api/main-agents/{main_agent['id']}").json()
    before_subagent = client.get(f"/agent-shell/api/subagents/{subagent['id']}").json()
    main_agent_copy = client.post(
        f"/agent-shell/api/main-agents/{main_agent['id']}/copy",
        json={"name": "Rejected Main Agent copy"},
    )
    subagent_copy = client.post(
        f"/agent-shell/api/subagents/{subagent['id']}/copy",
        json={"component_name": "Rejected Subagent copy"},
    )

    assert main_agent_copy.status_code == 422
    assert subagent_copy.status_code == 422
    assert client.get(f"/agent-shell/api/main-agents/{main_agent['id']}").json() == before_main_agent
    assert client.get(f"/agent-shell/api/subagents/{subagent['id']}").json() == before_subagent
    assert len(client.get("/agent-shell/api/main-agents").json()) == 1
    assert len(client.get("/agent-shell/api/subagents").json()) == 1
