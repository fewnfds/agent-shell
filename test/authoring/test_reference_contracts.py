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
        "/agent-shell/api/subagents",
        json=subagent_payload("Self worker", name="self_worker"),
    ).json()
    valid = client.post(
        "/agent-shell/api/main-agents",
        json={
            "name": "Unsaved self Main Agent",
            "capability_refs": required_refs,
            "subagents": [{"subagent_id": subagent["id"]}],
        },
    )
    assert valid.status_code == 200, valid.text
    main_agent = valid.json()
    assert main_agent["subagents"] == [{"subagent_id": subagent["id"]}]

def test_reference_contracts_reject_structural_errors_and_draft_semantic_errors(
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
    for index, capability_refs in enumerate(invalid_main_agent_refs[:2]):
        response = client.post(
            "/agent-shell/api/main-agents",
            json={"name": f"Invalid Main Agent {index}", "capability_refs": capability_refs},
        )
        assert response.status_code == 422, response.text

    wrong_type_payload = {
        "name": "Wrong-type Main Agent",
        "capability_refs": invalid_main_agent_refs[2],
    }
    wrong_type_draft = client.post(
        "/agent-shell/api/main-agents",
        json=wrong_type_payload,
    )
    assert wrong_type_draft.status_code == 200, wrong_type_draft.text
    assert wrong_type_draft.json()["enabled"] is False
    wrong_type_publish = client.put(
        f"/agent-shell/api/main-agents/{wrong_type_draft.json()['id']}/publish",
        json=wrong_type_payload,
    )
    assert wrong_type_publish.status_code == 422, wrong_type_publish.text

    optional_filesystem_disabled = client.post(
        "/agent-shell/api/subagents",
        json=subagent_payload(
            "Disabled Filesystem Subagent",
            name="minimal_filesystem_subagent",
            capability_overrides=[
                {"type": "filesystem", "mode": "disabled", "block_id": ""}
            ],
        ),
    )
    assert optional_filesystem_disabled.status_code == 200

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
            "/agent-shell/api/subagents",
            json=subagent_payload(
                f"Invalid Subagent {index}",
                name=f"invalid_subagent_{index}",
                capability_overrides=capability_overrides,
            ),
        )
        assert response.status_code == 422, response.text

def test_main_agent_draft_and_publish_enforce_delegation_and_skill_contracts(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    blocks = create_blocks(
        client,
        "save-contract",
        (*REQUIRED_TYPES, "filesystem", "skill", "subagent"),
    )
    required_refs = references(blocks, REQUIRED_TYPES)

    missing_required = [required_refs[:index] + required_refs[index + 1 :]
                        for index in range(len(required_refs))]
    for index, capability_refs in enumerate(missing_required):
        payload = {
            "name": f"Missing required {index}",
            "capability_refs": capability_refs,
        }
        response = client.post(
            "/agent-shell/api/main-agents",
            json=payload,
        )
        assert response.status_code == 200, response.text
        assert response.json()["enabled"] is False
        published = client.put(
            f"/agent-shell/api/main-agents/{response.json()['id']}/publish",
            json=payload,
        )
        assert published.status_code == 422, published.text

    without_filesystem = client.post(
        "/agent-shell/api/main-agents",
        json={
            "name": "No filesystem required",
            "capability_refs": [
                item for item in required_refs if item["type"] != "filesystem"
            ],
        },
    )
    assert without_filesystem.status_code == 200, without_filesystem.text
    assert without_filesystem.json()["enabled"] is False

    direct_skill_selection = client.post(
        "/agent-shell/api/main-agents",
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
        f"/agent-shell/api/blocks/filesystem/{filesystem['id']}",
        json={
            "name": filesystem["name"],
            "backend_type": "composite",
            "skill_package_id": blocks["skill"]["id"],
        },
    )
    assert bound_filesystem.status_code == 200, bound_filesystem.text
    assert bound_filesystem.json()["skill_package_id"] == blocks["skill"]["id"]

    delegation = client.post(
        "/agent-shell/api/blocks/subagent",
        json={"name": "Delegation"},
    ).json()
    delegation_without_binding_payload = {
        "name": "Delegation without binding",
        "capability_refs": [
            *required_refs,
            {"type": "subagent", "block_id": delegation["id"]},
        ],
    }
    delegation_without_binding = client.post(
        "/agent-shell/api/main-agents",
        json=delegation_without_binding_payload,
    )
    assert delegation_without_binding.status_code == 200
    assert delegation_without_binding.json()["enabled"] is False
    rejected_delegation = client.put(
        (
            "/agent-shell/api/main-agents/"
            f"{delegation_without_binding.json()['id']}/publish"
        ),
        json=delegation_without_binding_payload,
    )
    assert rejected_delegation.status_code == 422
    issues = rejected_delegation.json()["detail"]["validation"]["issues"]
    assert any(
        issue["code"] == "assembly.subagent_reference_required" for issue in issues
    )

    child_skill_override = client.post(
        "/agent-shell/api/subagents",
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
        "/agent-shell/api/subagents",
        json=subagent_payload("Complete worker", name="self_worker"),
    ).json()
    valid = client.post(
        "/agent-shell/api/main-agents",
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
