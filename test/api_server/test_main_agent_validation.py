from __future__ import annotations

from .support import *


def _draft_validation(client, payload: dict) -> dict:
    response = client.post(
        "/agent-shell/api/validation/draft",
        json={"target": {"kind": "main_agent"}, "payload": payload},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_main_agent_draft_publish_and_copy_state_machine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        draft = create_main_agent(client, is_model_entry=True, publish=False)
        assert draft["enabled"] is False
        assert draft["name"] not in {
            item["id"] for item in client.get("/compat/openai/v1/models").json()["data"]
        }

        published = publish_main_agent(client, draft)
        assert published["enabled"] is True
        assert published["name"] in {
            item["id"] for item in client.get("/compat/openai/v1/models").json()["data"]
        }

        copied = client.post(
            f"/agent-shell/api/main-agents/{published['id']}/copy",
            json={"name": "Copied draft"},
        )
        assert copied.status_code == 200, copied.text
        assert copied.json()["enabled"] is False

        invalid_payload = main_agent_payload(published)
        invalid_payload["capability_refs"] = [
            reference
            for reference in published["capability_refs"]
            if reference["type"] != "filesystem"
        ]
        rejected = client.put(
            f"/agent-shell/api/main-agents/{published['id']}/publish",
            json=invalid_payload,
        )
        after_rejection = client.get(
            f"/agent-shell/api/main-agents/{published['id']}"
        ).json()
        saved_draft = client.put(
            f"/agent-shell/api/main-agents/{published['id']}",
            json=invalid_payload,
        )

    assert rejected.status_code == 422
    assert after_rejection == published
    assert saved_draft.status_code == 200, saved_draft.text
    assert saved_draft.json()["enabled"] is False
    assert saved_draft.json()["capability_refs"] == invalid_payload["capability_refs"]


def test_main_agent_capability_linkage_reports_stable_errors_and_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        base = create_main_agent(client)
        required_refs = [
            reference
            for reference in base["capability_refs"]
            if reference["type"] in {"model-requirement", "agent-event-output"}
        ]
        filesystem_ref = next(
            reference
            for reference in base["capability_refs"]
            if reference["type"] == "filesystem"
        )
        tools_ref = next(
            reference
            for reference in base["capability_refs"]
            if reference["type"] == "filesystem-tools"
        )

        tools_without_backend = _draft_validation(
            client,
            {
                "name": "Tools without backend",
                "capability_refs": [*required_refs, tools_ref],
            },
        )
        backend_without_tools = _draft_validation(
            client,
            {
                "name": "Backend without tools",
                "capability_refs": [*required_refs, filesystem_ref],
            },
        )

        prompt_filesystem = client.post(
            "/agent-shell/api/blocks/filesystem",
            json={
                "name": "Prompt-only workspace",
                "system_prompt_override": "Use the configured workspace.",
            },
        ).json()
        prompt_without_tools = _draft_validation(
            client,
            {
                "name": "Prompt without tools",
                "capability_refs": [
                    *required_refs,
                    {"type": "filesystem", "block_id": prompt_filesystem["id"]},
                ],
            },
        )

        skill_template = tmp_path / "data" / "skills-template" / "outline"
        skill_template.mkdir(parents=True)
        (skill_template / "SKILL.md").write_text(
            "---\nname: outline\ndescription: Build an outline.\n---\n",
            encoding="utf-8",
        )
        skill_response = client.post(
            "/agent-shell/api/blocks/skill",
            json={"name": "Writing skills", "skill_template_paths": ["outline"]},
        )
        assert skill_response.status_code == 200, skill_response.text
        filesystem = client.get(
            f"/agent-shell/api/blocks/filesystem/{filesystem_ref['block_id']}"
        ).json()
        filesystem_update = client.put(
            f"/agent-shell/api/blocks/filesystem/{filesystem['id']}",
            json={
                **{key: value for key, value in filesystem.items() if key != "id"},
                "skill_package_id": skill_response.json()["id"],
            },
        )
        assert filesystem_update.status_code == 200, filesystem_update.text
        skill_without_tools = _draft_validation(
            client,
            {
                "name": "Skill without tools",
                "capability_refs": [*required_refs, filesystem_ref],
            },
        )

        execute_tools_response = client.post(
            "/agent-shell/api/blocks/filesystem-tools",
            json={
                "name": "Composite execute tools",
                "tool_configs": {"execute": {"visible": True}},
            },
        )
        assert execute_tools_response.status_code == 200, execute_tools_response.text
        execute_without_backend = _draft_validation(
            client,
            {
                "name": "Execute without backend",
                "capability_refs": [
                    *required_refs,
                    {
                        "type": "filesystem-tools",
                        "block_id": execute_tools_response.json()["id"],
                    },
                ],
            },
        )
        composite_execute = _draft_validation(
            client,
            {
                "name": "Composite execute",
                "capability_refs": [
                    *required_refs,
                    filesystem_ref,
                    {
                        "type": "filesystem-tools",
                        "block_id": execute_tools_response.json()["id"],
                    },
                ],
            },
        )

        summarization_response = client.post(
            "/agent-shell/api/blocks/summarization",
            json={"name": "Summary"},
        )
        assert summarization_response.status_code == 200, summarization_response.text
        summarization = _draft_validation(
            client,
            {
                "name": "Summary without tools",
                "capability_refs": [
                    *required_refs,
                    {
                        "type": "summarization",
                        "block_id": summarization_response.json()["id"],
                    },
                ],
            },
        )
        summary_payload = {
            "name": "Published summary without tools",
            "capability_refs": [
                *required_refs,
                {
                    "type": "summarization",
                    "block_id": summarization_response.json()["id"],
                },
            ],
        }
        summary_draft = client.post(
            "/agent-shell/api/main-agents",
            json=summary_payload,
        ).json()
        summary_published = client.put(
            f"/agent-shell/api/main-agents/{summary_draft['id']}/publish",
            json=summary_payload,
        )

        worker = client.post(
            "/agent-shell/api/subagents",
            json=subagent_payload("Worker", name="worker"),
        ).json()
        subagent_without_capability = _draft_validation(
            client,
            {
                "name": "References without delegation",
                "capability_refs": required_refs,
                "subagents": [{"subagent_id": worker["id"]}],
            },
        )

    assert {
        issue["code"] for issue in tools_without_backend["issues"]
    } == {"assembly.filesystem_backend_required"}
    assert backend_without_tools["valid"] is True
    assert backend_without_tools["issues"] == []
    assert {
        issue["code"] for issue in prompt_without_tools["issues"]
    } == {"assembly.filesystem_prompt_tools_required"}
    assert {
        issue["code"] for issue in skill_without_tools["issues"]
    } == {"assembly.skill_filesystem_tools_required"}
    assert {
        issue["code"] for issue in execute_without_backend["issues"]
    } == {"assembly.filesystem_backend_required"}
    assert {
        issue["code"] for issue in composite_execute["issues"]
    } == {"assembly.execute_local_shell_required"}
    assert summarization["valid"] is True
    assert [(issue["code"], issue["severity"]) for issue in summarization["issues"]] == [
        ("assembly.summarization_archive_unreadable", "warning")
    ]
    assert summary_published.status_code == 200, summary_published.text
    assert summary_published.json()["enabled"] is True
    assert {
        issue["code"] for issue in subagent_without_capability["issues"]
    } == {"assembly.subagent_capability_required"}


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
        delegation = client.post(
            "/agent-shell/api/blocks/subagent",
            json={"name": "Delegation"},
        ).json()
        payload = {
            "name": main_agent["name"],
            "capability_refs": [
                *main_agent["capability_refs"],
                {"type": "subagent", "block_id": delegation["id"]},
            ],
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
        published = client.put(
            f"/agent-shell/api/main-agents/{main_agent['id']}/publish",
            json=payload,
        )

    expected = {
        ("contract.subagent_reference_duplicate", "subagents[1].subagent_id"),
        ("contract.subagent_name_duplicate", "subagents[2].subagent_id"),
        ("configuration.reference_not_found", "subagents[3].subagent_id"),
    }
    assert draft.status_code == 200
    assert {
        (issue["code"], issue["path"]) for issue in draft.json()["issues"]
    } == expected
    assert saved.status_code == 200
    assert saved.json()["enabled"] is False
    assert published.status_code == 422
    assert {
        (issue["code"], issue["path"])
        for issue in published.json()["detail"]["validation"]["issues"]
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
