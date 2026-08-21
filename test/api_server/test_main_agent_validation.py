from __future__ import annotations

from .support import *


def test_subagent_references_report_duplicate_entity_name_and_missing_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        first = client.post(
            "/api/subagents",
            json=subagent_payload("First worker", name="worker"),
        ).json()
        second = client.post(
            "/api/subagents",
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
            "/api/validation/draft",
            json={"target": {"kind": "main_agent"}, "payload": payload},
        )
        saved = client.put(f"/api/main-agents/{main_agent['id']}", json=payload)

    expected = {
        ("contract.subagent_reference_duplicate", "subagents[1].subagent_id"),
        ("contract.subagent_name_duplicate", "subagents[2].subagent_id"),
        ("assembly.subagent_not_found", "subagents[3].subagent_id"),
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
            "/api/subagents",
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
