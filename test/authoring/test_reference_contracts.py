from __future__ import annotations

from .reference_support import *

def test_main_agent_subagent_reference_only_stores_entity_id(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    required_refs = references(
        create_blocks(client, "binding-flags-required", REQUIRED_TYPES),
        REQUIRED_TYPES,
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
    required = create_blocks(client, "validation", REQUIRED_TYPES)
    requirement = required["model-requirement"]
    required_refs = references(required, REQUIRED_TYPES)

    invalid_main_agent_refs = [
        [
            *required_refs,
            {"type": "unknown-capability", "block_id": requirement["id"]},
        ],
        [
            {"type": "model-requirement", "block_id": requirement["id"]},
            {"type": "model-requirement", "block_id": requirement["id"]},
            *required_refs[1:],
        ],
        [
            required_refs[0],
            {"type": "filesystem", "block_id": requirement["id"]},
            *required_refs[1:],
        ],
    ]
    for index, capability_refs in enumerate(invalid_main_agent_refs):
        response = client.post(
            "/api/main-agents",
            json={"name": f"Invalid Main Agent {index}", "capability_refs": capability_refs},
        )
        assert response.status_code == 422, response.text

    required_filesystem_disabled = client.post(
        "/api/subagents",
        json=subagent_payload(
            "Disabled Filesystem Subagent",
            name="minimal_filesystem_subagent",
            capability_overrides=[
                {"type": "filesystem", "mode": "disabled", "block_id": ""}
            ],
        ),
    )
    assert required_filesystem_disabled.status_code == 422

    invalid_overrides = [
        [{"type": "unknown-capability", "mode": "inherit", "block_id": ""}],
        [{"type": "model-requirement", "mode": "unsupported", "block_id": ""}],
        [{"type": "model-requirement", "mode": "replace", "block_id": ""}],
        [{"type": "model-requirement", "mode": "disabled", "block_id": ""}],
        [{"type": "subagent", "mode": "disabled", "block_id": ""}],
        [{"type": "skill", "mode": "replace", "block_id": requirement["id"]}],
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

def test_main_agent_save_enforces_required_delegation_and_skill_package_contracts(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    blocks = create_blocks(
        client,
        "save-contract",
        (*REQUIRED_TYPES, "skill", "subagent"),
    )
    required_refs = references(blocks, REQUIRED_TYPES)

    missing_required = [required_refs[:index] + required_refs[index + 1 :]
                        for index in range(len(required_refs))]
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
            "capability_refs": [
                item for item in required_refs if item["type"] != "filesystem"
            ],
        },
    )
    assert without_filesystem.status_code == 422, without_filesystem.text

    direct_skill_selection = client.post(
        "/api/main-agents",
        json={
            "name": "Direct Skill selection",
            "capability_refs": [
                *required_refs,
                {"type": "skill", "block_id": blocks["skill"]["id"]},
            ],
        },
    )
    assert direct_skill_selection.status_code == 422, direct_skill_selection.text

    filesystem = blocks["filesystem"]
    bound_filesystem = client.put(
        f"/api/blocks/filesystem/{filesystem['id']}",
        json={
            "name": filesystem["name"],
            "backend_type": "composite",
            "skill_package_id": blocks["skill"]["id"],
        },
    )
    assert bound_filesystem.status_code == 200, bound_filesystem.text
    assert bound_filesystem.json()["skill_package_id"] == blocks["skill"]["id"]

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
    assert child_skill_override.status_code == 422, child_skill_override.text

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
                {"type": "subagent", "block_id": delegation["id"]},
            ],
            "subagents": [{"subagent_id": complete_worker["id"]}],
        },
    )
    assert valid.status_code == 200, valid.text
