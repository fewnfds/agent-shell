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
        first = client.post(
            "/agent-shell/api/async-subagents",
            json=async_subagent_payload(
                "Research profile",
                target["id"],
                name="researcher",
                description="Research topics in the background.",
            ),
        ).json()
        self_target = client.post(
            "/agent-shell/api/async-subagents",
            json=async_subagent_payload(
                "Invalid self profile",
                parent["id"],
                name="RESEARCHER",
                description="Invalid self target with a duplicate name.",
            ),
        ).json()
        payload = {
            key: value for key, value in parent.items() if key != "id"
        }
        payload["async_subagents"] = [
            {"async_subagent_id": first["id"]},
            {"async_subagent_id": self_target["id"]},
            {"async_subagent_id": "00000000-0000-4000-8000-000000000000"},
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
            "async_subagents[1].async_subagent_id",
        ),
        (
            "contract.async_subagent_self_reference",
            "async_subagents[1].async_subagent_id",
        ),
        (
            "configuration.reference_not_found",
            "async_subagents[2].async_subagent_id",
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
        profiles = [
            client.post(
                "/agent-shell/api/async-subagents",
                json=async_subagent_payload(
                    f"Async profile {index}",
                    target["id"],
                    name=("researcher" if index == 0 else "reviewer"),
                    description=(
                        "Research the request."
                        if index == 0
                        else "Review the result."
                    ),
                ),
            ).json()
            for index, target in enumerate(targets)
        ]
        payload = {
            key: value for key, value in parent.items() if key != "id"
        }
        payload["async_subagents"] = [
            {"async_subagent_id": profiles[1]["id"]},
            {"async_subagent_id": profiles[0]["id"]},
        ]

        saved = client.put(
            f"/agent-shell/api/main-agents/{parent['id']}",
            json=payload,
        )

    assert saved.status_code == 200, saved.text
    assert saved.json()["async_subagents"] == payload["async_subagents"]


def test_async_subagent_configuration_resource_crud_and_target_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        target = create_main_agent(client)
        invalid = client.post(
            "/agent-shell/api/async-subagents",
            json=async_subagent_payload(
                "Missing target",
                "00000000-0000-4000-8000-000000000000",
            ),
        )
        created = client.post(
            "/agent-shell/api/async-subagents",
            json=async_subagent_payload(
                "Reusable research",
                target["id"],
                name="researcher",
            ),
        )
        assert created.status_code == 200, created.text
        profile = created.json()
        fetched = client.get(
            f"/agent-shell/api/async-subagents/{profile['id']}"
        )
        copied = client.post(
            f"/agent-shell/api/async-subagents/{profile['id']}/copy",
            json={"component_name": "Reusable research copy"},
        )
        updated_payload = {
            key: value for key, value in profile.items() if key != "id"
        }
        updated_payload["description"] = "Research and compare alternatives."
        updated = client.put(
            f"/agent-shell/api/async-subagents/{profile['id']}",
            json=updated_payload,
        )
        deleted = client.delete(
            f"/agent-shell/api/async-subagents/{copied.json()['id']}"
        )
        searched = client.get(
            "/agent-shell/api/async-subagents",
            params={"view": "summary", "q": "Reusable research"},
        )

    assert invalid.status_code == 422
    assert invalid.json()["detail"]["validation"]["issues"][0]["path"] == (
        "main_agent_id"
    )
    assert fetched.json() == profile
    assert copied.status_code == 200
    assert copied.json()["main_agent_id"] == target["id"]
    assert updated.status_code == 200
    assert updated.json()["description"] == "Research and compare alternatives."
    assert deleted.json() == {"ok": True}
    assert searched.status_code == 200
    assert searched.json()["total"] == 1


def test_async_subagent_update_rejects_new_reference_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        parent = create_main_agent(client)
        targets = [
            client.post(
                f"/agent-shell/api/main-agents/{parent['id']}/copy",
                json={"name": f"Async update target {index}"},
            ).json()
            for index in range(2)
        ]
        profiles = [
            client.post(
                "/agent-shell/api/async-subagents",
                json=async_subagent_payload(
                    f"Async update profile {index}",
                    target["id"],
                    name=("researcher" if index == 0 else "reviewer"),
                ),
            ).json()
            for index, target in enumerate(targets)
        ]
        parent_payload = {
            key: value for key, value in parent.items() if key != "id"
        }
        parent_payload["async_subagents"] = [
            {"async_subagent_id": profile["id"]} for profile in profiles
        ]
        saved_parent = client.put(
            f"/agent-shell/api/main-agents/{parent['id']}",
            json=parent_payload,
        )
        assert saved_parent.status_code == 200, saved_parent.text

        conflicting = {
            key: value for key, value in profiles[0].items() if key != "id"
        }
        conflicting["main_agent_id"] = parent["id"]
        conflicting["name"] = "REVIEWER"
        updated = client.put(
            f"/agent-shell/api/async-subagents/{profiles[0]['id']}",
            json=conflicting,
        )
        persisted = client.get(
            f"/agent-shell/api/async-subagents/{profiles[0]['id']}"
        )

    assert updated.status_code == 422
    assert {
        issue["code"]
        for issue in updated.json()["detail"]["validation"]["issues"]
    } == {
        "contract.async_subagent_name_duplicate",
        "contract.async_subagent_self_reference",
    }
    assert persisted.json() == profiles[0]


def test_async_subagent_middleware_requires_explicit_component_and_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        parent = create_main_agent(client)
        target = client.post(
            f"/agent-shell/api/main-agents/{parent['id']}/copy",
            json={"name": "Async worker"},
        ).json()
        profile = client.post(
            "/agent-shell/api/async-subagents",
            json=async_subagent_payload(
                "Async worker profile",
                target["id"],
            ),
        ).json()
        component_response = client.post(
            "/agent-shell/api/blocks/async-subagent",
            json={"name": "Async delegation"},
        )
        assert component_response.status_code == 200, component_response.text
        component = component_response.json()

        candidate_payload = {
            key: value for key, value in parent.items() if key != "id"
        }
        candidate_payload["async_subagents"] = [
            {"async_subagent_id": profile["id"]}
        ]
        candidate_only = client.put(
            f"/agent-shell/api/main-agents/{parent['id']}",
            json=candidate_payload,
        )
        assert candidate_only.status_code == 200, candidate_only.text

        async def effective_references():
            snapshot = await client.app.state.agent_runtime.capture()
            return snapshot.new_runtime(
                store=InMemoryStore()
            ).resolve_main_agent(parent["id"]).async_subagents

        portal = client.portal
        assert portal is not None
        assert portal.call(effective_references) == ()

        enabled_without_reference = {
            **candidate_payload,
            "capability_refs": [
                *candidate_payload["capability_refs"],
                {"type": "async-subagent", "block_id": component["id"]},
            ],
            "async_subagents": [],
        }
        missing = client.put(
            f"/agent-shell/api/main-agents/{parent['id']}",
            json=enabled_without_reference,
        )
        assert missing.status_code == 422
        assert {
            issue["code"]
            for issue in missing.json()["detail"]["validation"]["issues"]
        } == {"assembly.async_subagent_reference_required"}

        enabled = client.put(
            f"/agent-shell/api/main-agents/{parent['id']}",
            json={
                **enabled_without_reference,
                "async_subagents": [
                    {"async_subagent_id": profile["id"]}
                ],
            },
        )
        assert enabled.status_code == 200, enabled.text
        assert [
            item.async_subagent_id
            for item in portal.call(effective_references)
        ] == [profile["id"]]
