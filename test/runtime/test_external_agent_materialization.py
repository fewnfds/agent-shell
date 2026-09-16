from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from agent_shell.contracts import ExternalAgentProfile
from agent_shell.external_agents import binary as binary_module
from agent_shell.external_agents.binary import (
    AntigravityCliRelease,
    binary_path,
    file_sha256,
    install_guidance,
    probe_antigravity_cli,
    resolved_antigravity_cli,
)
from agent_shell.external_agents.layout import (
    antigravity_agent_root,
    antigravity_lifecycle_layout,
    remove_antigravity_lifecycle_state,
)
from agent_shell.external_agents.materialize import (
    definition_name,
    materialize_external_agent,
    render_definition,
)
from agent_shell.runtime.errors import AgentRuntimeError


def external_agent_profile(**overrides: object) -> ExternalAgentProfile:
    payload: dict[str, object] = {
        "name": "Antigravity Reviewer",
        "description": "Reviews a diff: findings only.",
        "provider": "antigravity-cli",
        "agent_name": "antigravity-reviewer",
        "system_prompt": "You review diffs and answer with findings only.",
        "model": "gemini-3-pro",
        "effort": "high",
        "print_timeout": "5m",
        "output_format": "stream-json",
        "conversation": "new",
        "exclude_default_components": True,
        "tools": ["view_file", "list_dir"],
        "tool_guidance": "Read files with absolute paths.",
        "tool_permission": "request-review",
        "permission_allow": ["read_file(*)"],
        "env": {"AGY_PROBE": "1"},
        **overrides,
    }
    return ExternalAgentProfile.model_validate(payload)


def test_materialized_home_holds_persona_settings_and_workspace(
    tmp_path: Path,
) -> None:
    profile = external_agent_profile()
    layout = antigravity_lifecycle_layout(tmp_path, str(uuid4()), str(uuid4()))

    materialized = materialize_external_agent(
        profile,
        layout,
        host_environment={"PATH": "C:/tools", "HOME": "C:/Users/example"},
    )

    name = definition_name(profile)
    assert materialized.definition_name == name
    assert materialized.home == layout.home
    assert materialized.workspace == layout.workspace
    assert layout.home.is_dir()
    assert layout.workspace.is_dir()
    assert list(layout.workspace.iterdir()) == []
    definition = materialized.definition_file
    assert definition == layout.home / ".gemini" / "config" / "agents" / f"{name}.md"
    assert name.startswith("antigravity-reviewer-")
    assert len(name.rsplit("-", 1)[1]) == 8

    text = definition.read_text(encoding="utf-8")
    assert f"name: {name}\n" in text
    assert '"Reviews a diff: findings only."' in text
    assert "subagent: false" in text
    assert "mainAgent: true" in text
    assert 'model: "gemini-3-pro"' in text
    assert "excludeDefaultComponents: true" in text
    assert "tools: [view_file, list_dir]" in text
    assert text.endswith(
        "# System Prompt\n\n"
        "You review diffs and answer with findings only.\n\n"
        "Read files with absolute paths.\n"
    )

    settings = json.loads(materialized.settings_file.read_text(encoding="utf-8"))
    assert settings == {
        "toolPermission": "request-review",
        "permissions": {"allow": ["read_file(*)"]},
    }

    environment = dict(materialized.environment)
    assert environment["PATH"] == "C:/tools"
    assert environment["AGY_PROBE"] == "1"
    assert environment["HOME"] == str(layout.home)
    assert environment["USERPROFILE"] == str(layout.home)
    assert environment["XDG_CONFIG_HOME"] == str(layout.home / ".config")
    assert "HOME" not in profile.env


def test_definition_revision_tracks_prompt_and_keeps_cli_settings(
    tmp_path: Path,
) -> None:
    profile = external_agent_profile()
    layout = antigravity_lifecycle_layout(tmp_path, str(uuid4()), str(uuid4()))
    layout.create()
    settings_file = layout.home / ".gemini" / "antigravity-cli" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(
        json.dumps(
            {
                "toolPermission": "strict",
                "enableTelemetry": False,
                "permissions": {"allow": ["stale(*)"], "deny": ["command(rm)"]},
            }
        ),
        encoding="utf-8",
    )

    materialize_external_agent(
        profile,
        layout,
        host_environment={},
    )
    materialize_external_agent(
        profile,
        layout,
        host_environment={},
    )
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    assert settings == {
        "toolPermission": "request-review",
        "enableTelemetry": False,
        "permissions": {"allow": ["read_file(*)"], "deny": ["command(rm)"]},
    }

    revised = materialize_external_agent(
        external_agent_profile(system_prompt="Second persona."),
        layout,
        host_environment={},
    )
    agents = layout.home / ".gemini" / "config" / "agents"
    assert revised.definition_name != definition_name(profile)
    assert sorted(path.name for path in agents.iterdir()) == sorted(
        [f"{definition_name(profile)}.md", f"{revised.definition_name}.md"]
    )


def test_corrupt_cli_settings_stop_materialization(tmp_path: Path) -> None:
    layout = antigravity_lifecycle_layout(tmp_path, str(uuid4()), str(uuid4()))
    layout.create()
    settings_file = layout.home / ".gemini" / "antigravity-cli" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text("{not json", encoding="utf-8")

    with pytest.raises(AgentRuntimeError) as raised:
        materialize_external_agent(
            external_agent_profile(),
            layout,
            host_environment={},
        )

    assert raised.value.code == "external_agent_materialization_failed"


def test_definition_omits_tool_allow_list_without_tools() -> None:
    text = render_definition(
        external_agent_profile(tools=[], tool_guidance="")
    )
    assert "excludeDefaultComponents: true" in text
    assert "tools:" not in text
    assert text.endswith(
        "\n# System Prompt\n\n"
        "You review diffs and answer with findings only.\n"
    )


def test_remove_state_keeps_workspace(tmp_path: Path) -> None:
    layout = antigravity_lifecycle_layout(tmp_path, str(uuid4()), str(uuid4()))
    materialized = materialize_external_agent(
        external_agent_profile(),
        layout,
        host_environment={},
    )
    (layout.workspace / "deliverable.txt").write_text("keep", encoding="utf-8")
    session = layout.session(str(uuid4()))
    session.create()

    layout.remove_state()

    assert not materialized.home.exists()
    assert not layout.sessions.exists()
    assert (layout.workspace / "deliverable.txt").read_text(encoding="utf-8") == "keep"


def test_layout_rejects_non_uuid_identity(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        antigravity_agent_root(tmp_path, "../../escape")
    with pytest.raises(ValueError):
        antigravity_lifecycle_layout(tmp_path, str(uuid4()), "not-a-uuid")


def test_lifecycle_cleanup_spans_presets_and_keeps_workspaces(
    tmp_path: Path,
) -> None:
    lifecycle_id = str(uuid4())
    other_lifecycle_id = str(uuid4())
    for agent_id in (str(uuid4()), str(uuid4())):
        layout = antigravity_lifecycle_layout(tmp_path, agent_id, lifecycle_id)
        materialize_external_agent(
            external_agent_profile(),
            layout,
            host_environment={},
        )
        (layout.workspace / "deliverable.txt").write_text("keep", encoding="utf-8")
    untouched = antigravity_lifecycle_layout(
        tmp_path, str(uuid4()), other_lifecycle_id
    )
    materialize_external_agent(
        external_agent_profile(),
        untouched,
        host_environment={},
    )

    remove_antigravity_lifecycle_state(tmp_path, lifecycle_id)
    remove_antigravity_lifecycle_state(tmp_path, lifecycle_id)
    remove_antigravity_lifecycle_state(tmp_path, "not-a-uuid")
    assert untouched.home.is_dir()

    cleaned = list(
        (tmp_path / "antigravity").glob(f"*/lifecycles/{lifecycle_id}")
    )
    assert len(cleaned) == 2
    for root in cleaned:
        assert [path.name for path in root.iterdir()] == ["workspace"]
    kept = list((tmp_path / "antigravity").glob("*/lifecycles/*/workspace/*.txt"))
    assert len(kept) == 2


def test_binary_probe_reports_missing_and_mismatched_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_file = tmp_path / "agy.exe"
    fake_file.write_bytes(b"not the pinned build")
    release = AntigravityCliRelease(
        version="9.9.9",
        platform=binary_module.current_platform(),
        archive="agy_cli_windows_x64.zip",
        archive_sha256="0" * 64,
        archive_executable="antigravity.exe",
        executable="agy.exe",
        executable_sha256="1" * 64,
        download_url="https://example.invalid/agy_cli_windows_x64.zip",
    )
    monkeypatch.setattr(
        binary_module,
        "ANTIGRAVITY_CLI_RELEASES",
        (release,),
    )

    missing = probe_antigravity_cli(tmp_path)
    assert missing.available is False
    assert missing.expected_path == binary_path(tmp_path, release)
    assert missing.version == "9.9.9"
    assert "missing" in missing.detail
    assert install_guidance(release, missing.expected_path) == missing.guidance
    with pytest.raises(AgentRuntimeError) as raised:
        resolved_antigravity_cli(tmp_path)
    assert raised.value.code == "external_agent_binary_unavailable"

    expected = binary_path(tmp_path, release)
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"not the pinned build")
    mismatched = probe_antigravity_cli(tmp_path)
    assert mismatched.available is False
    assert file_sha256(expected) in mismatched.detail
    assert "antigravity.exe" in mismatched.guidance

    monkeypatch.setattr(
        binary_module,
        "ANTIGRAVITY_CLI_RELEASES",
        (
            AntigravityCliRelease(
                **{
                    **release.__dict__,
                    "executable_sha256": file_sha256(expected),
                }
            ),
        ),
    )
    resolved = resolved_antigravity_cli(tmp_path)
    assert resolved.path == expected
    assert resolved.version == "9.9.9"
    assert resolved.sha256 == file_sha256(expected)
