from __future__ import annotations

import json
import sqlite3
from uuid import UUID

from .reference_support import *

def test_main_agent_reference_delete_detaches_optional_and_protects_required_types(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    original = create_blocks(client, "original")
    replacement = create_blocks(client, "replacement")
    subagent = client.post(
        "/api/subagents",
        json=subagent_payload(
            "Matrix worker",
            name="matrix_worker",
            description="Exercises every selected capability reference.",
        ),
    ).json()

    response = client.post(
        "/api/main-agents",
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

    for capability_type, block in original.items():
        deleted = client.delete(f"/api/blocks/{capability_type}/{block['id']}")
        expected = 409 if capability_type in REQUIRED_TYPES else 200
        assert deleted.status_code == expected, (capability_type, deleted.text)

    updated = client.put(
        f"/api/main-agents/{main_agent['id']}",
        json={
            "name": main_agent["name"],
            "capability_refs": references(replacement, MAIN_AGENT_TYPES),
            "middleware_refs": [{"middleware_id": replacement["custom-middleware"]["id"]}],
            "subagents": main_agent["subagents"],
        },
    )
    assert updated.status_code == 200, updated.text

    for capability_type in REQUIRED_TYPES:
        block = original[capability_type]
        released = client.delete(f"/api/blocks/{capability_type}/{block['id']}")
        assert released.status_code == 200, (capability_type, released.text)
    for capability_type, block in replacement.items():
        deleted = client.delete(f"/api/blocks/{capability_type}/{block['id']}")
        expected = 409 if capability_type in REQUIRED_TYPES else 200
        assert deleted.status_code == expected, (capability_type, deleted.text)

    assert client.delete(f"/api/main-agents/{main_agent['id']}").status_code == 200
    for capability_type in REQUIRED_TYPES:
        block = replacement[capability_type]
        released = client.delete(f"/api/blocks/{capability_type}/{block['id']}")
        assert released.status_code == 200, (capability_type, released.text)

def test_subagent_replace_references_are_detached_when_blocks_are_deleted(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    original = create_blocks(client, "override-original", OVERRIDEABLE_TYPES)

    response = client.post(
        "/api/subagents",
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
        deleted = client.delete(f"/api/blocks/{capability_type}/{block['id']}")
        assert deleted.status_code == 200, (capability_type, deleted.text)
    stored = client.get(f"/api/subagents/{subagent['id']}").json()
    assert stored["settings"]["capability_overrides"] == []

    passive_modes = [
        {
            "type": capability_type,
            "mode": "disabled",
            "block_id": "",
        }
        for index, capability_type in enumerate(OVERRIDEABLE_TYPES)
        if index % 2 == 1
    ]
    updated = client.put(
        f"/api/subagents/{subagent['id']}",
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

    assert client.delete(f"/api/subagents/{subagent['id']}").status_code == 200

def test_subagent_delete_detaches_entity_references(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    required_refs = references(
        create_blocks(client, "binding-required", ("model-requirement", "agent-event-output")),
        ("model-requirement", "agent-event-output"),
    )
    subagent_response = client.post(
        "/api/subagents",
        json=subagent_payload("Shared Subagent", name="draft_worker"),
    )
    assert subagent_response.status_code == 200, subagent_response.text
    subagent = subagent_response.json()

    owner_response = client.post(
        "/api/main-agents",
        json={
            "name": "Override owner",
            "capability_refs": required_refs,
            "subagents": [{"subagent_id": subagent["id"]}],
        },
    )
    assert owner_response.status_code == 200, owner_response.text
    owner = owner_response.json()

    independent_response = client.post(
        "/api/main-agents",
        json={"name": "Independent Main Agent", "capability_refs": required_refs},
    )
    assert independent_response.status_code == 200, independent_response.text
    independent = independent_response.json()
    assert client.delete(f"/api/main-agents/{independent['id']}").status_code == 200

    deleted = client.delete(f"/api/subagents/{subagent['id']}")
    assert deleted.status_code == 200, deleted.text
    stored_owner = client.get(f"/api/main-agents/{owner['id']}").json()
    assert stored_owner["subagents"] == []

    assert client.delete(f"/api/main-agents/{owner['id']}").status_code == 200

def test_subagent_nested_references_are_rejected_before_storage(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    target = client.post(
        "/api/subagents",
        json=subagent_payload("Direct target", name="direct_worker"),
    ).json()
    nested = client.post(
        "/api/subagents",
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
