from __future__ import annotations

from .reference_support import *


def test_main_agent_uses_ordered_custom_tool_references(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    blocks = create_blocks(
        client,
        "tool-list",
        ("model-requirement", "agent-event-output", "custom-tool"),
    )
    second = create_blocks(client, "second-tool", ("custom-tool",))["custom-tool"]

    response = client.post(
        "/api/main-agents",
        json={
            "name": "Tool list",
            "capability_refs": references(
                blocks,
                ("model-requirement", "agent-event-output"),
            ),
            "tool_refs": [
                {"tool_id": second["id"]},
                {"tool_id": blocks["custom-tool"]["id"]},
            ],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["tool_refs"] == [
        {"tool_id": second["id"]},
        {"tool_id": blocks["custom-tool"]["id"]},
    ]


def test_custom_tool_is_not_a_single_capability_or_subagent_override(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    blocks = create_blocks(
        client,
        "tool-contract",
        ("model-requirement", "agent-event-output", "custom-tool"),
    )

    main_agent = client.post(
        "/api/main-agents",
        json={
            "name": "Old tool selection",
            "capability_refs": references(
                blocks,
                ("model-requirement", "agent-event-output", "custom-tool"),
            ),
        },
    )
    subagent = client.post(
        "/api/subagents",
        json=subagent_payload(
            "Old tool override",
            capability_overrides=[
                {
                    "type": "custom-tool",
                    "mode": "replace",
                    "block_id": blocks["custom-tool"]["id"],
                }
            ],
        ),
    )

    assert main_agent.status_code == 422
    assert subagent.status_code == 422
    assert main_agent.json()["detail"]["validation"]["issues"][0]["code"].startswith(
        "contract."
    )
    assert subagent.json()["detail"]["validation"]["issues"][0]["code"].startswith(
        "contract."
    )


def test_missing_custom_tool_reference_is_reported(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    blocks = create_blocks(
        client,
        "missing-tool",
        ("model-requirement", "agent-event-output"),
    )

    response = client.post(
        "/api/main-agents",
        json={
            "name": "Missing tool",
            "capability_refs": references(
                blocks,
                ("model-requirement", "agent-event-output"),
            ),
            "tool_refs": [
                {"tool_id": "00000000-0000-4000-8000-000000000099"}
            ],
        },
    )

    assert response.status_code == 422
    issue = response.json()["detail"]["validation"]["issues"][0]
    assert issue["code"] == "assembly.reference_not_found"
    assert issue["path"] == "tool_refs[0].tool_id"


def test_main_agent_and_subagent_have_independent_tool_lists(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    blocks = create_blocks(
        client,
        "tool-owners",
        ("model-requirement", "agent-event-output", "subagent", "custom-tool"),
    )
    child_tool = create_blocks(client, "child-tool", ("custom-tool",))["custom-tool"]
    child_payload = subagent_payload("Tool worker")
    child_payload["settings"]["tool_refs"] = [{"tool_id": child_tool["id"]}]
    child = client.post("/api/subagents", json=child_payload)
    assert child.status_code == 200, child.text

    response = client.post(
        "/api/main-agents",
        json={
            "name": "Independent tools",
            "capability_refs": references(
                blocks,
                ("model-requirement", "agent-event-output", "subagent"),
            ),
            "tool_refs": [{"tool_id": blocks["custom-tool"]["id"]}],
            "subagents": [{"subagent_id": child.json()["id"]}],
        },
    )

    assert response.status_code == 200, response.text
    stored_child = client.get(f"/api/subagents/{child.json()['id']}").json()
    assert stored_child["settings"]["tool_refs"] == [{"tool_id": child_tool["id"]}]


def test_generic_draft_validation_covers_each_target_without_writing(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)

    block_report = client.post(
        "/api/validation/draft",
        json={
            "target": {"kind": "block", "type": "system-prompt"},
            "payload": {
                "name": "Draft prompt",
                "system_prompt": "Text",
                "legacy_field": True,
            },
        },
    )
    main_agent_report = client.post(
        "/api/validation/draft",
        json={
            "target": {"kind": "main_agent"},
            "payload": {"name": "Draft Main Agent", "capability_refs": []},
        },
    )
    subagent_report = client.post(
        "/api/validation/draft",
        json={
            "target": {"kind": "subagent"},
            "payload": subagent_payload(
                "Draft Subagent",
                name="draft_worker",
                capability_overrides=[
                    {
                        "type": "model-requirement",
                        "mode": "replace",
                        "block_id": "00000000-0000-4000-8000-000000000000",
                    }
                ],
            ),
        },
    )

    assert block_report.status_code == 200
    assert main_agent_report.status_code == 200
    assert subagent_report.status_code == 200
    assert block_report.json()["issues"][0]["code"] == "contract.unknown_field"
    assert any(
        issue["code"] == "assembly.required_capability_missing"
        for issue in main_agent_report.json()["issues"]
    )
    assert subagent_report.json()["issues"][0]["code"] == "assembly.reference_not_found"
    assert client.get("/api/blocks/system-prompt").json() == []
    assert client.get("/api/main-agents").json() == []
    assert client.get("/api/subagents").json() == []


def test_draft_validation_rejects_unknown_block_type_with_localized_detail(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/validation/draft",
        json={
            "target": {"kind": "block", "type": "unknown-block"},
            "payload": {},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "unknown_configuration_type",
        "message": "The requested configuration type is not supported.",
        "message_key": "errors.unknownConfigurationType",
        "message_args": {"type": "unknown-block"},
    }
