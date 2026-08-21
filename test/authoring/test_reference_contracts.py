from __future__ import annotations

from .reference_support import *

def test_main_agent_subagent_reference_only_stores_entity_id(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    required_refs = references(
        create_blocks(client, "binding-flags-required", ("model-requirement", "agent-event-output")),
        ("model-requirement", "agent-event-output"),
    )
    subagent = client.post(
        "/api/subagents",
        json=subagent_payload("Self worker", name="self_worker"),
    ).json()
    valid = client.post(
        "/api/main-agents",
        json={
            "name": "Unsaved self Main Agent",
            "capability_refs": required_refs,
            "subagents": [{"subagent_id": subagent["id"]}],
        },
    )
    assert valid.status_code == 200, valid.text
    main_agent = valid.json()
    assert main_agent["subagents"] == [{"subagent_id": subagent["id"]}]

def test_reference_contracts_reject_unknown_duplicate_wrong_type_and_force_removed(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    required = create_blocks(client, "validation", ("model-requirement", "agent-event-output"))
    requirement = required["model-requirement"]
    required_refs = references(required, ("model-requirement", "agent-event-output"))

    invalid_main_agent_refs = [
        [
            *required_refs,
            {"type": "unknown-capability", "block_id": requirement["id"]},
        ],
        [
            {"type": "model-requirement", "block_id": requirement["id"]},
            {"type": "model-requirement", "block_id": requirement["id"]},
            required_refs[1],
        ],
        [
            required_refs[0],
            {"type": "filesystem", "block_id": requirement["id"]},
            required_refs[1],
        ],
    ]
    for index, capability_refs in enumerate(invalid_main_agent_refs):
        response = client.post(
            "/api/main-agents",
            json={"name": f"Invalid Main Agent {index}", "capability_refs": capability_refs},
        )
        assert response.status_code == 422, response.text

    minimal_filesystem = client.post(
        "/api/subagents",
        json=subagent_payload(
            "Minimal Filesystem Subagent",
            name="minimal_filesystem_subagent",
            capability_overrides=[
                {"type": "filesystem", "mode": "disabled", "block_id": ""}
            ],
        ),
    )
    assert minimal_filesystem.status_code == 200, minimal_filesystem.text
    assert minimal_filesystem.json()["settings"]["capability_overrides"] == [
        {"type": "filesystem", "mode": "disabled", "block_id": ""}
    ]

    invalid_overrides = [
        [{"type": "unknown-capability", "mode": "inherit", "block_id": ""}],
        [{"type": "model-requirement", "mode": "unsupported", "block_id": ""}],
        [{"type": "model-requirement", "mode": "replace", "block_id": ""}],
        [{"type": "model-requirement", "mode": "disabled", "block_id": ""}],
        [{"type": "subagent", "mode": "disabled", "block_id": ""}],
        [
            {"type": "model-requirement", "mode": "inherit", "block_id": ""},
            {"type": "model-requirement", "mode": "disabled", "block_id": ""},
        ],
    ]
    for index, capability_overrides in enumerate(invalid_overrides):
        response = client.post(
            "/api/subagents",
            json=subagent_payload(
                f"Invalid Subagent {index}",
                name=f"invalid_subagent_{index}",
                capability_overrides=capability_overrides,
            ),
        )
        assert response.status_code == 422, response.text

def test_main_agent_save_enforces_required_and_delegation_contracts_with_skill_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    blocks = create_blocks(
        client,
        "save-contract",
        ("model-requirement", "agent-event-output", "filesystem", "skill", "subagent"),
    )
    required_refs = references(blocks, ("model-requirement", "agent-event-output"))

    missing_required = [
        [],
        [required_refs[1]],
        [required_refs[0]],
    ]
    for index, capability_refs in enumerate(missing_required):
        response = client.post(
            "/api/main-agents",
            json={
                "name": f"Missing required {index}",
                "capability_refs": capability_refs,
            },
        )
        assert response.status_code == 422, response.text

    without_filesystem = client.post(
        "/api/main-agents",
        json={
            "name": "No filesystem required",
            "capability_refs": required_refs,
        },
    )
    assert without_filesystem.status_code == 200, without_filesystem.text

    skill_without_filesystem = client.post(
        "/api/main-agents",
        json={
            "name": "Skill without filesystem",
            "capability_refs": [
                *required_refs,
                {"type": "skill", "block_id": blocks["skill"]["id"]},
            ],
        },
    )
    assert skill_without_filesystem.status_code == 200, skill_without_filesystem.text

    delegation = client.post(
        "/api/blocks/subagent",
        json={"name": "Delegation"},
    ).json()
    delegation_without_binding = client.post(
        "/api/main-agents",
        json={
            "name": "Delegation without binding",
            "capability_refs": [
                *required_refs,
                {"type": "subagent", "block_id": delegation["id"]},
            ],
        },
    )
    assert delegation_without_binding.status_code == 422
    issues = delegation_without_binding.json()["detail"]["validation"]["issues"]
    assert any(
        issue["code"] == "assembly.subagent_reference_required" for issue in issues
    )

    child_skill_override = client.post(
        "/api/subagents",
        json=subagent_payload(
            "Child skill without filesystem",
            name="skill_worker",
            description="Selects a Skill without a filesystem.",
            capability_overrides=[
                {
                    "type": "skill",
                    "mode": "replace",
                    "block_id": blocks["skill"]["id"],
                }
            ],
        ),
    )
    assert child_skill_override.status_code == 200, child_skill_override.text
    child_skill_without_filesystem = client.post(
        "/api/main-agents",
        json={
            "name": "Child Skill fallback",
            "capability_refs": [
                *required_refs,
                {"type": "subagent", "block_id": delegation["id"]},
            ],
            "subagents": [{"subagent_id": child_skill_override.json()["id"]}],
        },
    )
    assert child_skill_without_filesystem.status_code == 200, (
        child_skill_without_filesystem.text
    )

    complete_worker = client.post(
        "/api/subagents",
        json=subagent_payload("Complete worker", name="self_worker"),
    ).json()
    valid = client.post(
        "/api/main-agents",
        json={
            "name": "Complete required contract",
            "capability_refs": [
                *required_refs,
                {"type": "skill", "block_id": blocks["skill"]["id"]},
                {"type": "subagent", "block_id": delegation["id"]},
            ],
            "subagents": [{"subagent_id": complete_worker["id"]}],
        },
    )
    assert valid.status_code == 200, valid.text
