from __future__ import annotations

import json

from .support import *


def external_agent_payload() -> dict[str, object]:
    return {
        "name": "Antigravity Reviewer",
        "description": "Reviews a diff and returns findings.",
        "provider": "antigravity-cli",
        "agent_name": "antigravity-reviewer",
        "system_prompt": "You review diffs and answer with findings only.",
        "model": None,
        "effort": "low",
        "print_timeout": "5m",
        "output_format": "stream-json",
        "conversation": "new",
        "exclude_default_components": True,
        "tools": ["view_file", "list_dir"],
        "tool_guidance": "Read files with absolute paths.",
        "tool_permission": "request-review",
        "permission_allow": ["read_file(*)"],
        "env": {"AGY_PROBE": "1"},
    }


def test_external_agent_round_trip_persists_preset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        created = client.post(
            "/agent-shell/api/external-agents",
            json=external_agent_payload(),
        ).json()
        listed = client.get(
            "/agent-shell/api/external-agents",
            params={"view": "summary"},
        ).json()
        copied = client.post(
            f"/agent-shell/api/external-agents/{created['id']}/copy",
            json={"name": "Antigravity Reviewer (copy)"},
        ).json()
        updated_payload = {
            **external_agent_payload(),
            "name": "Antigravity Reviewer",
            "effort": "high",
            "conversation": "continue-latest",
            "tools": ["run_command"],
            "permission_allow": ["command(*)"],
        }
        updated = client.put(
            f"/agent-shell/api/external-agents/{created['id']}",
            json=updated_payload,
        ).json()
        deleted = client.delete(
            f"/agent-shell/api/external-agents/{copied['id']}"
        )
        missing = client.get(
            f"/agent-shell/api/external-agents/{copied['id']}"
        )

    assert created["name"] == "Antigravity Reviewer"
    assert created["provider"] == "antigravity-cli"
    assert created["model"] is None
    assert created["print_timeout"] == "5m"
    assert [item["id"] for item in listed["items"]] == [created["id"]]
    assert updated["effort"] == "high"
    assert updated["conversation"] == "continue-latest"
    assert updated["tools"] == ["run_command"]
    assert updated["permission_allow"] == ["command(*)"]
    assert updated["exclude_default_components"] is True
    assert updated["env"] == {"AGY_PROBE": "1"}
    assert deleted.json() == {"ok": True}
    assert missing.status_code == 404
    written = list(
        tmp_path.rglob(f"agents/external/{created['id']}.yaml")
    )
    assert len(written) == 1


def test_external_agent_rejects_invalid_preset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        bad_agent_name = client.post(
            "/agent-shell/api/external-agents",
            json={**external_agent_payload(), "agent_name": "Bad Name"},
        )
        bad_provider = client.post(
            "/agent-shell/api/external-agents",
            json={**external_agent_payload(), "provider": "other-cli"},
        )
        sampling = client.post(
            "/agent-shell/api/external-agents",
            json={**external_agent_payload(), "temperature": 0.7},
        )
        unknown_tool = client.post(
            "/agent-shell/api/external-agents",
            json={**external_agent_payload(), "tools": ["definitely_not_a_tool"]},
        )
        reserved_env = client.post(
            "/agent-shell/api/external-agents",
            json={**external_agent_payload(), "env": {"HOME": "C:/tmp"}},
        )
        bad_format = client.post(
            "/agent-shell/api/external-agents",
            json={**external_agent_payload(), "output_format": "bogus"},
        )

    assert bad_agent_name.status_code == 422
    assert bad_provider.status_code == 422
    assert sampling.status_code == 422
    assert unknown_tool.status_code == 422
    assert reserved_env.status_code == 422
    assert bad_format.status_code == 422


def test_external_agent_name_conflict_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        first = client.post(
            "/agent-shell/api/external-agents",
            json=external_agent_payload(),
        )
        duplicate = client.post(
            "/agent-shell/api/external-agents",
            json={**external_agent_payload(), "agent_name": "another-agent"},
        )
        repovalid = client.get(
            "/agent-shell/api/validation/repository"
        ).json()

    assert first.status_code == 200, first.text
    assert duplicate.status_code == 409
    assert repovalid["valid"] is True


def test_external_agent_survives_a_configuration_bundle_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    with make_client(source_root, monkeypatch) as source:
        created = source.post(
            "/agent-shell/api/external-agents",
            json=external_agent_payload(),
        ).json()
        exported = source.post(
            "/agent-shell/api/configuration-bundles/export",
            json={"kind": "external_agent", "source_id": created["id"]},
        )
        assert exported.status_code == 200, exported.text
        bundle = exported.content

    target_root = tmp_path / "target"
    target_root.mkdir()
    with make_client(target_root, monkeypatch) as target:
        preview_response = target.post(
            "/agent-shell/api/configuration-bundles/preview",
            files={"bundle": ("preset.zip", bundle, "application/zip")},
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        assert preview["ready"] is True, preview
        request = {
            "bundle_sha256": preview["bundle_sha256"],
            "plan_token": preview["plan_token"],
            "resolutions": {"target_ids": preview["target_ids"]},
        }
        imported = target.post(
            "/agent-shell/api/configuration-bundles/import",
            files={"bundle": ("preset.zip", bundle, "application/zip")},
            data={"request": json.dumps(request)},
        )
        assert imported.status_code == 200, imported.text
        items = target.get("/agent-shell/api/external-agents").json()
        written = list(
            target_root.rglob("agents/external/*.yaml")
        )

    assert [item["name"] for item in items] == ["Antigravity Reviewer"]
    assert items[0]["agent_name"] == "antigravity-reviewer"
    assert items[0]["conversation"] == "new"
    assert items[0]["tools"] == ["view_file", "list_dir"]
    assert items[0]["tool_guidance"] == "Read files with absolute paths."
    assert items[0]["permission_allow"] == ["read_file(*)"]
    assert items[0]["env"] == {"AGY_PROBE": "1"}
    assert items[0]["id"] != created["id"]
    assert len(written) == 1
