from __future__ import annotations

from .support import *


def test_subagent_references_report_duplicate_entity_name_and_missing_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        first = client.post(
            "/agent-shell/api/subagents",
            json=subagent_payload("First worker", name="worker"),
        ).json()
        second = client.post(
            "/agent-shell/api/subagents",
            json=subagent_payload("Second worker", name="WORKER"),
        ).json()
        payload = {
            "name": main_agent["name"],
            "capability_refs": main_agent["capability_refs"],
            "subagents": [
                {"subagent_id": first["id"]},
                {"subagent_id": first["id"]},
                {"subagent_id": second["id"]},
                {"subagent_id": "00000000-0000-4000-8000-000000000000"},
            ],
        }

        draft = client.post(
            "/agent-shell/api/validation/draft",
            json={"target": {"kind": "main_agent"}, "payload": payload},
        )
        saved = client.put(f"/agent-shell/api/main-agents/{main_agent['id']}", json=payload)

    expected = {
        ("contract.subagent_reference_duplicate", "subagents[1].subagent_id"),
        ("contract.subagent_name_duplicate", "subagents[2].subagent_id"),
        ("configuration.reference_not_found", "subagents[3].subagent_id"),
    }
    assert draft.status_code == 200
    assert {
        (issue["code"], issue["path"]) for issue in draft.json()["issues"]
    } == expected
    assert saved.status_code == 422
    assert {
        (issue["code"], issue["path"])
        for issue in saved.json()["detail"]["validation"]["issues"]
    } == expected


def test_subagent_entity_owns_routing_identity_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/agent-shell/api/subagents",
            json={
                "component_name": "Invalid routing identity",
                "name": "中文名称",
                "description": "",
                "settings": {"capability_overrides": []},
            },
        )

    assert response.status_code == 422
    paths = {
        issue["path"]
        for issue in response.json()["detail"]["validation"]["issues"]
    }
    assert paths == {"name", "description"}


def test_async_main_agent_references_validate_target_self_and_unique_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        parent = create_main_agent(client)
        target = client.post(
            f"/agent-shell/api/main-agents/{parent['id']}/copy",
            json={"name": "Async target"},
        ).json()
        payload = {
            key: value for key, value in parent.items() if key != "id"
        }
        payload["async_subagents"] = [
            {
                "main_agent_id": target["id"],
                "name": "researcher",
                "description": "Research topics in the background.",
            },
            {
                "main_agent_id": parent["id"],
                "name": "RESEARCHER",
                "description": "Invalid self target with a duplicate name.",
            },
            {
                "main_agent_id": "00000000-0000-4000-8000-000000000000",
                "name": "missing",
                "description": "Missing target.",
            },
        ]

        saved = client.put(
            f"/agent-shell/api/main-agents/{parent['id']}",
            json=payload,
        )

    assert saved.status_code == 422
    assert {
        (issue["code"], issue["path"])
        for issue in saved.json()["detail"]["validation"]["issues"]
    } == {
        (
            "contract.async_subagent_name_duplicate",
            "async_subagents[1].name",
        ),
        (
            "contract.async_subagent_self_reference",
            "async_subagents[1].main_agent_id",
        ),
        (
            "configuration.reference_not_found",
            "async_subagents[2].main_agent_id",
        ),
    }


def test_async_main_agent_references_persist_in_authored_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        parent = create_main_agent(client)
        targets = [
            client.post(
                f"/agent-shell/api/main-agents/{parent['id']}/copy",
                json={"name": f"Async target {index}"},
            ).json()
            for index in range(2)
        ]
        payload = {
            key: value for key, value in parent.items() if key != "id"
        }
        payload["async_subagents"] = [
            {
                "main_agent_id": targets[1]["id"],
                "name": "reviewer",
                "description": "Review the result.",
            },
            {
                "main_agent_id": targets[0]["id"],
                "name": "researcher",
                "description": "Research the request.",
            },
        ]

        saved = client.put(
            f"/agent-shell/api/main-agents/{parent['id']}",
            json=payload,
        )

    assert saved.status_code == 200, saved.text
    assert saved.json()["async_subagents"] == payload["async_subagents"]
