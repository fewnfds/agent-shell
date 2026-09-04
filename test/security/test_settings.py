from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from agent_shell.app import create_app
from agent_shell.settings import SettingsError, get_settings
from agent_shell.storage import permissions as storage_permissions
from agent_shell.storage.permissions import PermissionStatus
from agent_shell.storage.environment import serialize_environment


def _write_environment_file(root: Path, content: str) -> Path:
    path = root / "data" / "config" / "agent-shell.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        name: value
        for line in content.splitlines()
        if (separator := line.partition("="))[1]
        for name, value in [(separator[0], separator[2])]
    }
    path.write_text(serialize_environment(values), encoding="utf-8")
    return path


def _write_system_settings(root: Path, **values: object) -> Path:
    path = root / "data" / "config" / "system.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"settings": values}), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def clean_agent_shell_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for key in tuple(os.environ):
        if key.upper().startswith("AGENT_SHELL_"):
            monkeypatch.delenv(key, raising=False)


def test_default_settings_require_a_management_password() -> None:
    with pytest.raises(SettingsError) as captured:
        get_settings()

    assert captured.value.keys == ("AGENT_SHELL_MANAGEMENT_TOKEN",)


def test_existing_environment_file_must_have_private_permissions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_environment_file(
        tmp_path,
        "AGENT_SHELL_MANAGEMENT_TOKEN=management-secret\n",
    )
    monkeypatch.setattr(
        "agent_shell.app.secure_file",
        lambda path: PermissionStatus(
            "file",
            False,
            "test-unconfirmed",
            "The test did not confirm private permissions.",
        ),
    )

    with pytest.raises(SettingsError) as captured:
        create_app()

    assert captured.value.keys == ("data/config/agent-shell.env",)
    assert "management-secret" not in str(captured.value)


def test_local_settings_writer_secures_environment_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agent_shell import __main__ as launcher

    environment_path = tmp_path / "agent-shell.env"
    secured: list[Path] = []
    monkeypatch.setattr(
        launcher,
        "secure_file",
        lambda path: (
            secured.append(path)
            or PermissionStatus(
                "file",
                True,
                "test-private",
                "The test confirmed private permissions.",
            )
        ),
    )

    launcher._write_management_password(
        "management-secret",
        env_path=environment_path,
    )

    assert secured == [environment_path]
    assert environment_path.read_text(encoding="utf-8") == (
        "AGENT_SHELL_MANAGEMENT_TOKEN=management-secret\n"
    )


def test_local_settings_writer_fails_when_permissions_cannot_be_secured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agent_shell import __main__ as launcher

    environment_path = tmp_path / "agent-shell.env"
    monkeypatch.setattr(
        launcher,
        "secure_file",
        lambda path: PermissionStatus(
            "file",
            False,
            "test-unconfirmed",
            "The test did not confirm private permissions.",
        ),
    )

    with pytest.raises(OSError, match="permissions are not private"):
        launcher._write_management_password(
            "management-secret",
            env_path=environment_path,
        )

    assert environment_path.exists()


def test_local_management_password_does_not_require_an_api_key_at_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_environment_file(
        tmp_path, "AGENT_SHELL_MANAGEMENT_TOKEN=management-secret\n"
    )
    settings = get_settings()

    assert settings.host == "127.0.0.1"
    assert settings.port == 19100
    assert settings.langsmith_tracing_enabled is False
    assert settings.is_loopback is True
    assert settings.deployment_mode == "authenticated_local"
    assert settings.cors_origins == ()
    assert settings.trusted_proxy_cidrs == ()
    assert "management-secret" not in repr(settings)


def test_process_environment_settings_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "must-not-appear"
    monkeypatch.setenv("AGENT_SHELL_MANAGMENT_TOKEN", sentinel)

    with pytest.raises(SettingsError) as captured:
        get_settings()

    assert captured.value.keys == ("AGENT_SHELL_MANAGEMENT_TOKEN",)


def test_unknown_prefixed_file_setting_fails_but_unrelated_setting_is_ignored(
    tmp_path: Path,
) -> None:
    _write_environment_file(
        tmp_path,
        "UNRELATED_SETTING=ignored\n"
        "AGENT_SHELL_MANAGMENT_TOKEN=must-not-appear\n",
    )

    with pytest.raises(SettingsError) as captured:
        get_settings(
            application_home=tmp_path,
        )

    assert captured.value.keys == ("AGENT_SHELL_MANAGMENT_TOKEN",)
    assert "must-not-appear" not in str(captured.value)


def test_portable_settings_ignore_host_agent_shell_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_environment_file(
        tmp_path,
        "AGENT_SHELL_MANAGEMENT_TOKEN=portable-management-secret\n",
    )
    _write_system_settings(tmp_path, port=9123)
    monkeypatch.setenv("AGENT_SHELL_PORT", "not-a-port")
    monkeypatch.setenv("AGENT_SHELL_MANAGMENT_TOKEN", "host-typo-secret")

    settings = get_settings(application_home=tmp_path)

    assert settings.port == 9123
    assert settings.management_token is not None
    assert settings.management_token.get_secret_value() == "portable-management-secret"


def test_relative_paths_are_bound_to_explicit_application_home(tmp_path: Path) -> None:
    first_home = tmp_path / "first"
    second_home = tmp_path / "second"
    first_home.mkdir()
    second_home.mkdir()
    for home in (first_home, second_home):
        _write_environment_file(
            home,
            "AGENT_SHELL_MANAGEMENT_TOKEN=portable-management-secret\n",
        )

    first = get_settings(application_home=first_home)
    second = get_settings(application_home=second_home)

    assert first.resolved_application_database_path() == (
        first_home / "data" / "state" / "agent-shell.sqlite3"
    ).resolve()
    assert first.resolved_runtime_dir() == (first_home / "runtime").resolve()
    assert first.resolved_logs_dir() == (first_home / "data" / "logs").resolve()
    assert first.resolved_files_dir() == (first_home / "data" / "files").resolve()
    assert first.resolved_skill_templates_dir() == (
        first_home / "data" / "skills-template"
    ).resolve()
    assert second.resolved_application_database_path() == (
        second_home / "data" / "state" / "agent-shell.sqlite3"
    ).resolve()
    assert first.resolved_application_database_path() != (
        second.resolved_application_database_path()
    )


@pytest.mark.parametrize("host", ["127.99.1.2", "::1"])
def test_all_contract_loopback_addresses_allow_authenticated_local_mode(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
    tmp_path: Path,
) -> None:
    _write_system_settings(tmp_path, host=host)
    _write_environment_file(
        tmp_path, "AGENT_SHELL_MANAGEMENT_TOKEN=management-secret\n"
    )
    assert get_settings(application_home=tmp_path).deployment_mode == "authenticated_local"


def test_non_loopback_requires_explicit_remote_and_management_password(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_system_settings(tmp_path, host="0.0.0.0")

    with pytest.raises(SettingsError) as captured:
        get_settings(application_home=tmp_path)

    assert "AGENT_SHELL_ALLOW_REMOTE" in str(captured.value)
    assert "AGENT_SHELL_MANAGEMENT_TOKEN" in str(captured.value)


def test_remote_settings_accept_a_user_chosen_management_password(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_system_settings(tmp_path, host="0.0.0.0", allow_remote=True)
    _write_environment_file(tmp_path, "AGENT_SHELL_MANAGEMENT_TOKEN=m\n")

    settings = get_settings(application_home=tmp_path)

    assert settings.deployment_mode == "authenticated_remote"
    assert settings.management_token is not None
    assert settings.management_token.get_secret_value() == "m"


def test_local_mode_keeps_a_user_chosen_management_password(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_environment_file(tmp_path, "AGENT_SHELL_MANAGEMENT_TOKEN=m\n")

    settings = get_settings()

    assert settings.deployment_mode == "authenticated_local"


def test_project_langsmith_tracing_setting_is_explicit_and_portable(
    tmp_path: Path,
) -> None:
    _write_environment_file(
        tmp_path,
        "AGENT_SHELL_MANAGEMENT_TOKEN=portable-management-secret\n"
        "LANGSMITH_API_KEY=portable-langsmith-key\n",
    )
    _write_system_settings(tmp_path, langsmith_tracing_enabled=True)

    settings = get_settings(
        application_home=tmp_path,
    )

    assert settings.langsmith_tracing_enabled is True
    assert settings.langsmith_api_key is not None
    assert settings.langsmith_api_key.get_secret_value() == "portable-langsmith-key"


def test_management_password_has_no_application_length_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    chosen_password = "m" * 5000
    _write_environment_file(
        tmp_path, f"AGENT_SHELL_MANAGEMENT_TOKEN={chosen_password}\n"
    )

    settings = get_settings()

    assert settings.management_token is not None
    assert settings.management_token.get_secret_value() == chosen_password


def test_bearer_tokens_reject_non_ascii_values_without_echo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token = "management-secrét"
    _write_environment_file(tmp_path, f"AGENT_SHELL_MANAGEMENT_TOKEN={token}\n")

    with pytest.raises(SettingsError) as captured:
        get_settings()

    assert captured.value.keys == ("AGENT_SHELL_MANAGEMENT_TOKEN",)
    assert token not in str(captured.value)


def test_cors_and_proxy_lists_are_strict_and_normalized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_system_settings(
        tmp_path,
        cors_origins=["https://EXAMPLE.com:8443", "http://127.0.0.1:3000"],
        trusted_proxy_cidrs=["10.0.0.0/8", "::1/128"],
        allow_remote=True,
    )
    _write_environment_file(tmp_path, "AGENT_SHELL_MANAGEMENT_TOKEN=m\n")

    settings = get_settings(application_home=tmp_path)

    assert settings.cors_origins == (
        "https://example.com:8443",
        "http://127.0.0.1:3000",
    )
    assert settings.trusted_proxy_cidrs == ("10.0.0.0/8", "::1/128")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AGENT_SHELL_HOST", "localhost"),
        ("AGENT_SHELL_PORT", "0"),
        ("AGENT_SHELL_CORS_ORIGINS", "*"),
        ("AGENT_SHELL_CORS_ORIGINS", "https://example.com/path"),
        ("AGENT_SHELL_TRUSTED_PROXY_CIDRS", "10.0.0.1/8"),
    ],
)
def test_invalid_network_settings_report_only_the_setting_key(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: str,
    tmp_path: Path,
) -> None:
    _write_environment_file(
        tmp_path, "AGENT_SHELL_MANAGEMENT_TOKEN=management-secret\n"
    )
    field = key.removeprefix("AGENT_SHELL_").lower()
    _write_system_settings(tmp_path, **{field: value})

    with pytest.raises(SettingsError) as captured:
        get_settings(application_home=tmp_path)

    assert key in str(captured.value)
    assert value not in str(captured.value)
