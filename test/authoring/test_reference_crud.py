from __future__ import annotations

import json
import sqlite3
from uuid import UUID

from .reference_support import *


def repository_reference_issues(client, *, owner_id: str) -> list[dict]:
    return [
        issue
        for issue in client.get("/agent-shell/api/validation/repository").json()["issues"]
        if issue["owner_id"] == owner_id
        and issue["code"].startswith("configuration.reference_")
    ]


def test_main_agent_reference_delete_preserves_ids_and_reports_missing_targets(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    original = create_blocks(client, "original")
    replacement = create_blocks(client, "replacement")
    subagent = client.post(
        "/agent-shell/api/subagents",
        json=subagent_payload(
            "Matrix worker",
            name="matrix_worker",
            description="Exercises every selected capability reference.",
        ),
    ).json()

    response = client.post(
        "/agent-shell/api/main-agents",
        json={
            "name": "Main Agent matrix",
            "capability_refs": references(original, MAIN_AGENT_TYPES),
            "middleware_refs": [{"middleware_id": original["custom-middleware"]["id"]}],
            "subagents": [{"subagent_id": subagent["id"]}],
        },
    )
    assert response.status_code == 200, response.text
    main_agent = response.json()
    assert [item["type"] for item in main_agent["capability_refs"]] == list(
        MAIN_AGENT_TYPES
    )

    expected_original_ids = {
        item["block_id"] for item in main_agent["capability_refs"]
    } | {main_agent["middleware_refs"][0]["middleware_id"]}
    for capability_type, block in original.items():
        deleted = client.delete(f"/agent-shell/api/blocks/{capability_type}/{block['id']}")
        assert deleted.status_code == 200, (capability_type, deleted.text)

    stored = client.get(f"/agent-shell/api/main-agents/{main_agent['id']}").json()
    assert stored["capability_refs"] == main_agent["capability_refs"]
    assert stored["middleware_refs"] == main_agent["middleware_refs"]
    issues = repository_reference_issues(client, owner_id=main_agent["id"])
    assert {issue["message_args"]["reference_id"] for issue in issues} == (
        expected_original_ids
    )
    assert all(issue["code"] == "configuration.reference_not_found" for issue in issues)

    updated = client.put(
        f"/agent-shell/api/main-agents/{main_agent['id']}",
        json={
            "name": main_agent["name"],
            "capability_refs": references(replacement, MAIN_AGENT_TYPES),
            "middleware_refs": [{"middleware_id": replacement["custom-middleware"]["id"]}],
            "subagents": main_agent["subagents"],
        },
    )
    assert updated.status_code == 200, updated.text

    for capability_type, block in replacement.items():
        deleted = client.delete(f"/agent-shell/api/blocks/{capability_type}/{block['id']}")
        assert deleted.status_code == 200, (capability_type, deleted.text)

    stored = client.get(f"/agent-shell/api/main-agents/{main_agent['id']}").json()
    assert stored["capability_refs"] == updated.json()["capability_refs"]
    assert client.delete(f"/agent-shell/api/main-agents/{main_agent['id']}").status_code == 200


def test_subagent_replace_reference_delete_preserves_ids_and_reports_owner(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    original = create_blocks(client, "override-original", OVERRIDEABLE_TYPES)

    response = client.post(
        "/agent-shell/api/subagents",
        json=subagent_payload(
            "Override matrix",
            name="override_matrix",
            capability_overrides=[
                {
                    "type": capability_type,
                    "mode": "replace",
                    "block_id": original[capability_type]["id"],
                }
                for capability_type in OVERRIDEABLE_TYPES
            ],
        ),
    )
    assert response.status_code == 200, response.text
    subagent = response.json()

    for capability_type, block in original.items():
        deleted = client.delete(f"/agent-shell/api/blocks/{capability_type}/{block['id']}")
        assert deleted.status_code == 200, (capability_type, deleted.text)
    stored = client.get(f"/agent-shell/api/subagents/{subagent['id']}").json()
    assert stored["settings"]["capability_overrides"] == subagent["settings"][
        "capability_overrides"
    ]
    issues = repository_reference_issues(client, owner_id=subagent["id"])
    assert {issue["message_args"]["reference_id"] for issue in issues} == {
        block["id"] for block in original.values()
    }

    passive_modes = [
        {
            "type": capability_type,
            "mode": "disabled",
            "block_id": "",
        }
        for index, capability_type in enumerate(OVERRIDEABLE_TYPES)
        if index % 2 == 1 and capability_type not in REQUIRED_TYPES
    ]
    updated = client.put(
        f"/agent-shell/api/subagents/{subagent['id']}",
        json=subagent_payload(
            subagent["component_name"],
            name=subagent["name"],
            description=subagent["description"],
            capability_overrides=passive_modes,
        ),
    )
    assert updated.status_code == 200, updated.text
    assert [
        item["mode"]
        for item in updated.json()["settings"]["capability_overrides"]
    ] == [
        item["mode"] for item in passive_modes
    ]

    assert client.delete(f"/agent-shell/api/subagents/{subagent['id']}").status_code == 200


def test_skill_package_delete_preserves_composite_filesystem_reference(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    skill = create_blocks(client, "filesystem-skill", ("skill",))["skill"]
    filesystem_response = client.post(
        "/agent-shell/api/blocks/filesystem",
        json={
            "name": "Skill package workspace",
            "backend_type": "composite",
            "skill_package_id": skill["id"],
        },
    )
    assert filesystem_response.status_code == 200, filesystem_response.text
    filesystem = filesystem_response.json()

    deleted = client.delete(f"/agent-shell/api/blocks/skill/{skill['id']}")
    assert deleted.status_code == 200, deleted.text
    stored = client.get(f"/agent-shell/api/blocks/filesystem/{filesystem['id']}").json()
    assert stored["skill_package_id"] == skill["id"]
    assert repository_reference_issues(client, owner_id=filesystem["id"]) == [
        {
            "code": "configuration.reference_not_found",
            "scope": "block",
            "owner_id": filesystem["id"],
            "owner_name": filesystem["name"],
            "owner_type": "filesystem",
            "path": "skill_package_id",
            "message": "The referenced skill configuration does not exist.",
            "message_key": "validation.issue.configuration.referenceNotFound",
            "message_args": {
                "expected_type": "skill",
                "reference_id": skill["id"],
            },
            "severity": "error",
        }
    ]


def test_subagent_delete_preserves_entity_references_and_reports_owner(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    required_refs = references(
        create_blocks(client, "binding-required", REQUIRED_TYPES),
        REQUIRED_TYPES,
    )
    subagent_response = client.post(
        "/agent-shell/api/subagents",
        json=subagent_payload("Shared Subagent", name="draft_worker"),
    )
    assert subagent_response.status_code == 200, subagent_response.text
    subagent = subagent_response.json()

    owner_response = client.post(
        "/agent-shell/api/main-agents",
        json={
            "name": "Override owner",
            "capability_refs": required_refs,
            "subagents": [{"subagent_id": subagent["id"]}],
        },
    )
    assert owner_response.status_code == 200, owner_response.text
    owner = owner_response.json()

    independent_response = client.post(
        "/agent-shell/api/main-agents",
        json={"name": "Independent Main Agent", "capability_refs": required_refs},
    )
    assert independent_response.status_code == 200, independent_response.text
    independent = independent_response.json()
    assert client.delete(f"/agent-shell/api/main-agents/{independent['id']}").status_code == 200

    deleted = client.delete(f"/agent-shell/api/subagents/{subagent['id']}")
    assert deleted.status_code == 200, deleted.text
    stored_owner = client.get(f"/agent-shell/api/main-agents/{owner['id']}").json()
    assert stored_owner["subagents"] == owner["subagents"]
    issue = repository_reference_issues(client, owner_id=owner["id"])
    assert len(issue) == 1
    assert issue[0]["path"] == "subagents[0].subagent_id"
    assert issue[0]["message_args"] == {
        "expected_type": "subagent",
        "reference_id": subagent["id"],
    }

    assert client.delete(f"/agent-shell/api/main-agents/{owner['id']}").status_code == 200

def test_subagent_nested_references_are_rejected_before_storage(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    target = client.post(
        "/agent-shell/api/subagents",
        json=subagent_payload("Direct target", name="direct_worker"),
    ).json()
    nested = client.post(
        "/agent-shell/api/subagents",
        json={
            **subagent_payload(
                "Invalid nested owner",
                name="invalid_nested_owner",
            ),
            "settings": {
                "capability_overrides": [],
                "subagents": [{"subagent_id": target["id"]}],
            },
        },
    )
    assert nested.status_code == 422
    issue = nested.json()["detail"]["validation"]["issues"][0]
    assert issue["code"] == "contract.unknown_field"
