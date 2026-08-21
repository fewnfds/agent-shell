from __future__ import annotations

from .support import *


def test_subagent_rejects_every_non_empty_child_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        child = client.post(
            "/api/subagents",
            json=subagent_payload("Child", name="child"),
        ).json()
        response = client.post(
            "/api/subagents",
            json={
                **subagent_payload(
                    "Parent-shaped Subagent",
                    name="parent_shaped_subagent",
                ),
                "settings": {
                    "capability_overrides": [],
                    "subagents": [{"subagent_id": child["id"]}],
                },
            },
        )

    assert response.status_code == 422
    issue = response.json()["detail"]["validation"]["issues"][0]
    assert issue["code"] == "contract.unknown_field"
    assert issue["path"] == "settings.subagents"


def test_main_agent_accepts_multiple_direct_subagents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        workers = [
            client.post(
                "/api/subagents",
                json=subagent_payload(
                    f"Worker {index}",
                    name=f"worker_{index}",
                ),
            ).json()
            for index in range(2)
        ]
        delegation = client.post(
            "/api/blocks/subagent",
            json={"name": "Direct delegation"},
        ).json()
        response = client.put(
            f"/api/main-agents/{main_agent['id']}",
            json={
                "name": main_agent["name"],
                "capability_refs": [
                    *main_agent["capability_refs"],
                    {"type": "subagent", "block_id": delegation["id"]},
                ],
                "subagents": [
                    {"subagent_id": worker["id"]} for worker in workers
                ],
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["subagents"] == [
        {"subagent_id": worker["id"]} for worker in workers
    ]
