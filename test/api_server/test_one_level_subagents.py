from __future__ import annotations

from .support import *


def test_main_agent_with_subagents_constructs_without_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(
            client,
            include_filesystem=False,
            is_model_entry=True,
        )
        worker = client.post(
            "/agent-shell/api/subagents",
            json=subagent_payload("Worker", name="worker"),
        ).json()
        delegation = client.post(
            "/agent-shell/api/blocks/subagent",
            json={"name": "Delegation"},
        ).json()
        payload = main_agent_payload(main_agent)
        payload["capability_refs"] = [
            *payload["capability_refs"],
            {"type": "subagent", "block_id": delegation["id"]},
        ]
        payload["subagents"] = [{"subagent_id": worker["id"]}]
        published = publish_main_agent(client, main_agent, payload)
        response = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": published["name"],
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 200, response.text


def test_subagent_rejects_every_non_empty_child_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        child = client.post(
            "/agent-shell/api/subagents",
            json=subagent_payload("Child", name="child"),
        ).json()
        response = client.post(
            "/agent-shell/api/subagents",
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
                "/agent-shell/api/subagents",
                json=subagent_payload(
                    f"Worker {index}",
                    name=f"worker_{index}",
                ),
            ).json()
            for index in range(2)
        ]
        delegation = client.post(
            "/agent-shell/api/blocks/subagent",
            json={"name": "Direct delegation"},
        ).json()
        response = client.put(
            f"/agent-shell/api/main-agents/{main_agent['id']}",
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
