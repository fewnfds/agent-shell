from __future__ import annotations

import os
from pathlib import Path

import pytest
import uvicorn
import yaml
from fastapi.testclient import TestClient

from agent_shell.app import create_app
from agent_shell.settings import SettingsError, get_settings
from agent_shell.storage.api_server import ApiServerStore
from agent_shell.storage.database import SQLiteDatabase
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.environment import serialize_environment
from agent_shell.storage import permissions as storage_permissions
from agent_shell.storage.permissions import PermissionStatus


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


def test_create_app_installs_minimal_cors_and_runtime_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "runtime"
    data_root = tmp_path / "data"
    python_templates_dir = data_root / "templates"
    python_package_instances_dir = FileConfigRepository(data_root).python_package_instances_root
    _write_system_settings(tmp_path, cors_origins=["https://console.example"])
    _write_environment_file(
        tmp_path, "AGENT_SHELL_MANAGEMENT_TOKEN=management-secret\n"
    )

    with TestClient(create_app()) as client:
        allowed = client.options(
            "/api/catalog",
            headers={
                "Origin": "https://console.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization, X-Request-ID",
            },
        )
        patch_allowed = client.options(
            "/api/files/%2Frenamed.txt",
            headers={
                "Origin": "https://console.example",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        rejected = client.options(
            "/api/catalog",
            headers={
                "Origin": "https://other.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://console.example"
    assert patch_allowed.status_code == 200
    assert "PATCH" in patch_allowed.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in allowed.headers
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers
    assert (runtime_dir / "cache").is_dir()
    assert (runtime_dir / "tmp").is_dir()
    assert (runtime_dir / "home").is_dir()
    assert (data_root / "state").is_dir()
    assert (data_root / "files").is_dir()
    assert (data_root / "logs").is_dir()
    assert (python_templates_dir / "workflow" / "command").is_dir()
    assert (python_templates_dir / "workflow" / "task_dispatcher").is_dir()
    assert (python_templates_dir / "agent" / "custom_middleware").is_dir()
    assert (python_package_instances_dir / "command").is_dir()
    assert (python_package_instances_dir / "task-dispatcher").is_dir()
    assert (python_package_instances_dir / "agent-middleware").is_dir()


def test_official_launcher_uses_only_validated_settings_and_disables_proxy_headers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agent_shell import __main__ as launcher

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    _write_system_settings(tmp_path, host="127.0.0.2", port=9123)
    _write_environment_file(
        tmp_path, "AGENT_SHELL_MANAGEMENT_TOKEN=management-secret\n"
    )
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert launcher.main(serve_frontend=False) == 0
    assert len(calls) == 1
    assert calls[0][0][0].title == "agent-shell"
    assert calls[0][1] == {
        "host": "127.0.0.2",
        "port": 9123,
        "proxy_headers": False,
        "ws": "websockets-sansio",
    }


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [(False, "false"), (True, "true")],
)
def test_project_langsmith_tracing_boundary_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    enabled: bool,
    expected: str,
) -> None:
    from agent_shell import __main__ as launcher
    from agent_shell import langsmith_tracing

    _write_system_settings(tmp_path, langsmith_tracing_enabled=enabled)
    environment = "AGENT_SHELL_MANAGEMENT_TOKEN=management-secret\n"
    if enabled:
        environment += "LANGSMITH_API_KEY=langsmith-test-key\n"
    _write_environment_file(tmp_path, environment)
    monkeypatch.setenv("LANGSMITH_TRACING", "true" if not enabled else "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true" if not enabled else "false")
    monkeypatch.setenv("LANGCHAIN_TRACING", "true" if not enabled else "false")
    configured: list[dict[str, object]] = []
    monkeypatch.setattr(
        langsmith_tracing.ls,
        "configure",
        lambda **kwargs: configured.append(kwargs),
    )
    monkeypatch.setattr(uvicorn, "run", lambda *_args, **_kwargs: None)

    assert launcher.main(serve_frontend=False) == 0
    assert os.environ["LANGSMITH_TRACING"] == expected
    assert os.environ["LANGCHAIN_TRACING_V2"] == expected
    assert os.environ["LANGCHAIN_TRACING"] == expected
    assert configured[-1]["enabled"] is enabled
    assert configured[-1]["project_name"] == "agent-shell"
    assert (configured[-1]["client"] is not None) is enabled


def test_official_launcher_prints_effective_settings_for_windows_script(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from agent_shell import __main__ as launcher

    _write_system_settings(tmp_path, host="::1", port=9123)
    _write_environment_file(tmp_path, "AGENT_SHELL_MANAGEMENT_TOKEN=management-secret\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda *args, **kwargs: pytest.fail("settings query must not start uvicorn"),
    )

    assert (
        launcher.run_cli(
            ["--home", str(tmp_path), "--print-launch-settings"]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out == "::1|9123|http://[::1]:9123/admin\n"
    assert captured.err == ""


def test_windows_launcher_prepares_and_prints_settings_in_one_process(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from agent_shell import __main__ as launcher

    _write_system_settings(tmp_path, host="127.0.0.2", port=9123)
    _write_environment_file(
        tmp_path,
        "AGENT_SHELL_MANAGEMENT_TOKEN=management-secret\n",
    )
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "launch preparation must not start uvicorn"
        ),
    )

    assert (
        launcher.run_cli(
            ["--home", str(tmp_path), "--prepare-launch-settings"]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out == "127.0.0.2|9123|http://127.0.0.2:9123/admin\n"
    assert captured.err == ""


def test_official_launcher_prepares_package_dependencies_before_app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agent_shell import __main__ as launcher

    calls: list[str] = []
    _write_environment_file(
        tmp_path, "AGENT_SHELL_MANAGEMENT_TOKEN=management-secret\n"
    )
    monkeypatch.setattr(
        launcher,
        "_prepare_windows_dependencies",
        lambda **_kwargs: calls.append("dependencies"),
    )
    monkeypatch.setattr(
        launcher,
        "_activate_package_site",
        lambda _runtime_root: calls.append("activate"),
    )
    app = object()

    def tracked_create_app(**_kwargs: object) -> object:
        calls.append("app")
        return app

    monkeypatch.setattr(launcher, "_create_application", tracked_create_app)
    monkeypatch.setattr(
        launcher,
        "_run_server",
        lambda *_args, **_kwargs: calls.append("server"),
    )

    assert launcher.main(prepare_dependencies=True, serve_frontend=False) == 0
    assert calls == ["dependencies", "activate", "app", "server"]
    output = capsys.readouterr().out
    assert "Python dependency preparation started..." in output
    assert "Python dependency preparation finished." in output
    assert output.index("Python dependency preparation finished.") < output.index(
        "Starting Agent Shell..."
    )


def test_official_launcher_port_help_is_compact(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agent_shell import __main__ as launcher

    assert launcher.run_cli(["--help"]) == 0
    captured = capsys.readouterr()
    assert "--port PORT" in captured.out
    assert "--port {1,2,3" not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_official_launcher_rejects_invalid_port(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    port: str,
) -> None:
    from agent_shell import __main__ as launcher

    assert launcher.run_cli(["--home", str(tmp_path), "--port", port]) == 2
    captured = capsys.readouterr()
    assert "port must be" in captured.err


def test_official_launcher_warns_when_remote_http_backend_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from agent_shell import __main__ as launcher

    management_token = "management-secret-sentinel"
    api_key = "api-secret-sentinel"
    _write_system_settings(tmp_path, allow_remote=True)
    _write_environment_file(
        tmp_path, f"AGENT_SHELL_MANAGEMENT_TOKEN={management_token}\n"
    )
    database = SQLiteDatabase(tmp_path / "data" / "state" / "agent-shell.sqlite3")
    ApiServerStore(database, FileConfigRepository(tmp_path / "data")).update_settings(
        api_key_operation="replace",
        api_key=api_key,
    )
    monkeypatch.setattr(uvicorn, "run", lambda *_args, **_kwargs: None)

    assert launcher.main(serve_frontend=False) == 0
    captured = capsys.readouterr()
    assert "Remote HTTP backend enabled" in captured.err
    assert "TLS reverse proxy and firewall" in captured.err
    assert management_token not in captured.err
    assert api_key not in captured.err


def test_official_launcher_reports_safe_startup_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from agent_shell import __main__ as launcher

    sentinel = "launcher-inference-secret"
    _write_environment_file(
        tmp_path,
        "AGENT_SHELL_MANAGEMENT_TOKEN=management-secret\n"
        f"AGENT_SHELL_INFERENCE_TOKEN={sentinel}\n",
    )
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda *args, **kwargs: pytest.fail(
            "invalid settings must not start uvicorn"
        ),
    )

    assert launcher.main() == 2
    captured = capsys.readouterr()
    assert "AGENT_SHELL_INFERENCE_TOKEN" in captured.err
    assert sentinel not in captured.err


def test_windows_launcher_initializes_missing_local_management_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from agent_shell import __main__ as launcher

    sentinel = "local-admin-2026"
    (tmp_path / ".env.example").write_text(
        "# AGENT_SHELL_MANAGEMENT_TOKEN=<generate-a-management-token>\n",
        encoding="utf-8",
    )
    answers = iter((sentinel, sentinel))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher.getpass, "getpass", lambda _prompt: next(answers))

    result = launcher.run_cli(
        ["--home", str(tmp_path), "--initialize-local-settings"]
    )
    if result != 0:
        env_path = tmp_path / "data" / "config" / "agent-shell.env"
        permission = launcher.secure_file(env_path)
        dacl = storage_permissions._read_windows_dacl(env_path)
        pytest.fail(
            "local settings initialization failed: "
            f"env_exists={env_path.exists()}, "
            f"permission={permission.mechanism}/{permission.boundary}, "
            f"dacl={dacl or '<unreadable>'}"
        )

    env_text = (
        tmp_path / "data" / "config" / "agent-shell.env"
    ).read_text(encoding="utf-8")
    assert f"AGENT_SHELL_MANAGEMENT_TOKEN={sentinel}" in env_text
    assert "# AGENT_SHELL_MANAGEMENT_TOKEN=" not in env_text
    assert get_settings().management_token.get_secret_value() == sentinel
    captured = capsys.readouterr()
    assert "不会改变 /v1 OpenAI API 使用的 Key" in captured.out
    assert sentinel not in captured.out
    assert captured.err == ""


def test_windows_launcher_keeps_existing_management_password(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agent_shell import __main__ as launcher

    original = "AGENT_SHELL_MANAGEMENT_TOKEN=existing-admin-password\n"
    env_path = _write_environment_file(tmp_path, original)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        launcher.getpass,
        "getpass",
        lambda _prompt: pytest.fail("an existing password must not be prompted for"),
    )

    assert (
        launcher.run_cli(
            ["--home", str(tmp_path), "--initialize-local-settings"]
        )
        == 0
    )
    assert env_path.read_text(encoding="utf-8") == serialize_environment(
        {"AGENT_SHELL_MANAGEMENT_TOKEN": "existing-admin-password"}
    )


def test_windows_launcher_does_not_overwrite_invalid_existing_settings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from agent_shell import __main__ as launcher

    original = "AGENT_SHELL_MANAGEMENT_TOKEN=existing-admin-password\n"
    env_path = _write_environment_file(tmp_path, original)
    system_path = _write_system_settings(tmp_path, port="not-a-port")
    original_system = system_path.read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        launcher.getpass,
        "getpass",
        lambda _prompt: pytest.fail("invalid settings must not enter password setup"),
    )

    assert (
        launcher.run_cli(
            ["--home", str(tmp_path), "--initialize-local-settings"]
        )
        == 2
    )
    assert env_path.read_text(encoding="utf-8") == serialize_environment(
        {"AGENT_SHELL_MANAGEMENT_TOKEN": "existing-admin-password"}
    )
    assert system_path.read_text(encoding="utf-8") == original_system
    captured = capsys.readouterr()
    assert "AGENT_SHELL_PORT" in captured.err
    assert "not-a-port" not in captured.err


def test_windows_launcher_does_not_initialize_remote_deployment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from agent_shell import __main__ as launcher

    original = ""
    env_path = _write_environment_file(tmp_path, original)
    system_path = _write_system_settings(tmp_path, host="0.0.0.0", allow_remote=True)
    original_system = system_path.read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        launcher.getpass,
        "getpass",
        lambda _prompt: pytest.fail("remote deployment must be configured explicitly"),
    )

    assert (
        launcher.run_cli(
            ["--home", str(tmp_path), "--initialize-local-settings"]
        )
        == 2
    )
    assert env_path.read_text(encoding="utf-8") == original
    assert system_path.read_text(encoding="utf-8") == original_system
    captured = capsys.readouterr()
    assert "AGENT_SHELL_MANAGEMENT_TOKEN" in captured.err
