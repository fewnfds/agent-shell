from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from agent_shell.app import create_app
from agent_shell.settings import get_settings
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.system_log_settings import SystemLogSettingsStore
from agent_shell.storage.validation_settings import ConfigurationValidationSettingsStore
from agent_shell.storage.workflow_lifecycle_settings import WorkflowLifecycleSettingsStore
from support import API_KEY, MANAGEMENT_TOKEN, ScopedAuthTestClient, configure_scope_tokens


@pytest.fixture(autouse=True)
def clean_agent_shell_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.upper().startswith("AGENT_SHELL_"):
            monkeypatch.delenv(key, raising=False)


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    async def skip_external_retention(_self) -> None:
        return None

    monkeypatch.setattr(
        "agent_shell.runtime.langgraph_lifecycle.LangGraphLifecycleService.enforce_retention",
        skip_external_retention,
    )
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    app = create_app()
    return app, ScopedAuthTestClient(app)


def _payload(**overrides) -> dict:
    payload = {
        "host": "127.0.0.1",
        "port": 19100,
        "n_jobs_per_worker": 20,
        "recursion_limit": 100_000,
        "max_concurrency": 20,
        "debug_port": None,
        "allow_remote": False,
        "langsmith_tracing_enabled": False,
        "langsmith_endpoint": "https://api.smith.langchain.com",
        "langsmith_project": "agent-shell",
        "langsmith_workspace_id": None,
        "langsmith_api_key": {"operation": "keep"},
        "management_token": {"operation": "preserve"},
        "cors_origins": [],
        "trusted_proxy_cidrs": [],
    }
    payload.update(overrides)
    return payload


def test_system_settings_get_reports_secret_status_without_secret_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client = _client(tmp_path, monkeypatch)
    response = client.get("/agent-shell/api/system/settings")

    assert response.status_code == 200
    assert response.json() == {
        "host": "127.0.0.1",
        "port": 19100,
        "n_jobs_per_worker": 20,
        "recursion_limit": 100_000,
        "max_concurrency": 20,
        "debug_port": None,
        "allow_remote": False,
        "langsmith_tracing_enabled": False,
        "langsmith_endpoint": "https://api.smith.langchain.com",
        "langsmith_project": "agent-shell",
        "langsmith_workspace_id": None,
        "langsmith_api_key": {"configured": False},
        "cors_origins": [],
        "trusted_proxy_cidrs": [],
        "management_token": {"configured": True},
        "restart_required": False,
        "active_management_url": "http://testserver/admin#/",
        "active_api_docs_url": "http://testserver/docs",
        "active_studio_url": (
            "https://smith.langchain.com/studio/"
            "?baseUrl=http%3A%2F%2Ftestserver"
        ),
    }
    assert MANAGEMENT_TOKEN not in response.text


def test_valid_system_settings_are_atomic_and_take_effect_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client = _client(tmp_path, monkeypatch)
    settings_path = tmp_path / "data" / "config" / "system.yaml"
    monkeypatch.setattr(
        "agent_shell.system_settings.validate_langsmith_connection",
        lambda _settings: None,
    )

    response = client.put(
        "/agent-shell/api/system/settings",
        json=_payload(
            port=9123,
            n_jobs_per_worker=12,
            recursion_limit=321,
            max_concurrency=7,
            debug_port=9124,
            langsmith_tracing_enabled=True,
            langsmith_project="workflow-debug",
            langsmith_api_key={
                "operation": "replace",
                "value": "langsmith-test-key",
            },
            cors_origins=["https://CONSOLE.example:8443"],
        ),
    )

    assert response.status_code == 200, response.text
    assert response.json()["restart_required"] is True
    assert response.json()["port"] == 9123
    assert response.json()["n_jobs_per_worker"] == 12
    assert response.json()["recursion_limit"] == 321
    assert response.json()["max_concurrency"] == 7
    assert response.json()["debug_port"] == 9124
    assert response.json()["langsmith_tracing_enabled"] is True
    assert response.json()["langsmith_api_key"] == {"configured": True}
    assert "langsmith-test-key" not in response.text
    assert response.json()["cors_origins"] == ["https://console.example:8443"]
    assert app.state.settings.port == 19100
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    assert document["settings"]["port"] == 9123
    assert document["settings"]["n_jobs_per_worker"] == 12
    assert document["settings"]["recursion_limit"] == 321
    assert document["settings"]["max_concurrency"] == 7
    assert document["settings"]["debug_port"] == 9124
    assert document["settings"]["langsmith_tracing_enabled"] is True
    assert document["settings"]["langsmith_project"] == "workflow-debug"
    assert "langsmith_api_key" not in document["settings"]
    assert document["settings"]["cors_origins"] == ["https://console.example:8443"]
    restarted = get_settings(application_home=tmp_path)
    assert restarted.port == 9123
    assert restarted.n_jobs_per_worker == 12
    assert restarted.recursion_limit == 321
    assert restarted.max_concurrency == 7
    assert restarted.debug_port == 9124
    assert restarted.langsmith_tracing_enabled is True
    assert restarted.langsmith_api_key is not None
    assert restarted.langsmith_api_key.get_secret_value() == "langsmith-test-key"
    assert restarted.cors_origins == ("https://console.example:8443",)
    reloaded_repository = FileConfigRepository(tmp_path / "data")
    reloaded_repository.set_secret("AGENT_SHELL_API_KEY", "another-shell-key")
    env_text = (tmp_path / "data" / "config" / "agent-shell.env").read_text(
        encoding="utf-8"
    )
    assert "LANGSMITH_API_KEY=langsmith-test-key" in env_text


def test_system_and_model_secret_updates_preserve_each_other(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, client = _client(tmp_path, monkeypatch)
    connection_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    model_payload = {
        "name": "Local model",
        "provider": "openai",
        "base_url": "https://api.example.com/v1",
        "credential": "model-secret",
        "model": "local-model",
        "provider_settings": {},
        "tool_choice": None,
        "response_format": None,
        "model_settings": {},
    }
    app.state.model_resources.save_connection(connection_id, model_payload)

    updated = client.put(
        "/agent-shell/api/system/settings",
        json=_payload(port=9125),
    )

    assert updated.status_code == 200, updated.text
    assert (
        app.state.model_resources.resolve_connection(connection_id)["credential"]
        == "model-secret"
    )

    client.put(
        "/agent-shell/api/system/settings",
        json=_payload(
            management_token={
                "operation": "replace",
                "value": "changed-management-token",
            }
        ),
    )
    app.state.model_resources.save_connection(
        connection_id,
        {**model_payload, "credential": "rotated-model-secret"},
    )

    restarted = get_settings(application_home=tmp_path)
    assert restarted.management_token is not None
    assert (
        restarted.management_token.get_secret_value()
        == "changed-management-token"
    )


def test_unreachable_langsmith_connection_does_not_save_settings_or_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_shell.langsmith_tracing import LangSmithConnectionError

    _, client = _client(tmp_path, monkeypatch)
    settings_path = tmp_path / "data" / "config" / "system.yaml"
    environment_path = tmp_path / "data" / "config" / "agent-shell.env"
    original_settings = settings_path.read_text(encoding="utf-8")
    original_environment = environment_path.read_text(encoding="utf-8")
    replacement = "langsmith-replacement-secret"
    monkeypatch.setattr(
        "agent_shell.system_settings.validate_langsmith_connection",
        lambda _settings: (_ for _ in ()).throw(LangSmithConnectionError()),
    )

    response = client.put(
        "/agent-shell/api/system/settings",
        json=_payload(
            langsmith_tracing_enabled=True,
            langsmith_api_key={"operation": "replace", "value": replacement},
        ),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "langsmith_connection_failed"
    assert response.json()["detail"]["message_key"] == "errors.langsmithConnectionFailed"
    assert replacement not in response.text
    assert settings_path.read_text(encoding="utf-8") == original_settings
    assert environment_path.read_text(encoding="utf-8") == original_environment


def test_invalid_candidate_does_not_write_or_reveal_replacement_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client = _client(tmp_path, monkeypatch)
    replacement = "replacement-management-secret-000000"
    settings_path = tmp_path / "data" / "config" / "system.yaml"
    original = settings_path.read_text(encoding="utf-8")

    response = client.put(
        "/agent-shell/api/system/settings",
        json=_payload(
            host="0.0.0.0",
            management_token={"operation": "replace", "value": replacement},
        ),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "system_settings_invalid"
    assert replacement not in response.text
    assert settings_path.read_text(encoding="utf-8") == original


def test_management_password_replacement_is_write_only_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client = _client(tmp_path, monkeypatch)
    replacement = "new-management-password"

    response = client.put(
        "/agent-shell/api/system/settings",
        json=_payload(
            management_token={"operation": "replace", "value": replacement},
        ),
    )

    assert response.status_code == 200
    assert replacement not in response.text
    assert MANAGEMENT_TOKEN not in response.text
    restarted = get_settings(application_home=tmp_path)
    assert restarted.management_token is not None
    assert restarted.management_token.get_secret_value() == replacement
    env_text = (tmp_path / "data" / "config" / "agent-shell.env").read_text(
        encoding="utf-8"
    )
    assert replacement in env_text
    assert "AGENT_SHELL_HOST" not in env_text


def test_management_password_can_equal_the_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client = _client(tmp_path, monkeypatch)

    response = client.put(
        "/agent-shell/api/system/settings",
        json=_payload(
            management_token={"operation": "replace", "value": API_KEY},
        ),
    )

    assert response.status_code == 200
    restarted = get_settings(application_home=tmp_path)
    assert restarted.management_token is not None
    assert restarted.management_token.get_secret_value() == API_KEY


def test_permission_failure_leaves_existing_settings_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client = _client(tmp_path, monkeypatch)
    system_path = tmp_path / "data" / "config" / "system.yaml"
    original = system_path.read_text(encoding="utf-8")
    environment_path = tmp_path / "data" / "config" / "agent-shell.env"
    original_environment = environment_path.read_text(encoding="utf-8")
    monkeypatch.setattr(
        FileConfigRepository,
        "update_system",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("write failed")),
    )

    response = client.put(
        "/agent-shell/api/system/settings",
        json=_payload(
            port=9124,
            management_token={
                "operation": "replace",
                "value": "must-be-rolled-back",
            },
        ),
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "system_settings_write_failed"
    assert system_path.read_text(encoding="utf-8") == original
    assert environment_path.read_text(encoding="utf-8") == original_environment


def test_workflow_lifecycle_settings_are_owned_by_runtime_monitoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client = _client(tmp_path, monkeypatch)

    current = client.get("/agent-shell/api/workflow-lifecycles/settings")
    saved = client.put(
        "/agent-shell/api/workflow-lifecycles/settings",
        json={"retained_lifecycles": 0},
    )

    assert current.status_code == 200
    assert current.json()["retained_lifecycles"] == 20
    assert current.json()["minimums"] == {"retained_lifecycles": 0}
    assert saved.status_code == 200
    assert saved.json()["retained_lifecycles"] == 0
    document = yaml.safe_load(
        (tmp_path / "data" / "config" / "system.yaml").read_text(encoding="utf-8")
    )
    assert document["workflow_lifecycles"]["retained_lifecycles"] == 0
    assert client.put(
        "/agent-shell/api/workflow-lifecycles/settings",
        json={"retained_lifecycles": -1},
    ).status_code == 422
    assert client.put(
        "/agent-shell/api/workflow-lifecycles/settings",
        json={"retained_lifecycles": True},
    ).status_code == 422


def test_numeric_system_setting_snapshots_reject_booleans(tmp_path: Path) -> None:
    repository = FileConfigRepository.empty(tmp_path)
    repository.update_system(
        lambda system: system["configuration_validation"].__setitem__(
            "debounce_ms", True
        )
    )
    repository.update_system(
        lambda system: system["system_log"].__setitem__("max_size_mib", True)
    )
    repository.update_system(
        lambda system: system["workflow_lifecycles"].__setitem__(
            "retained_lifecycles", True
        )
    )

    with pytest.raises(ValueError, match="validation debounce"):
        ConfigurationValidationSettingsStore(repository).snapshot()
    with pytest.raises(ValueError, match="system log maximum size"):
        SystemLogSettingsStore(repository).snapshot()
    with pytest.raises(ValueError, match="retained_lifecycles"):
        WorkflowLifecycleSettingsStore(repository).snapshot()
