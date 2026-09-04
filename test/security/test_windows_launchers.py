from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

import pytest

from agent_shell.storage.environment import serialize_environment


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_POWERSHELL = (
    Path(os.environ.get("SystemRoot", r"C:\Windows"))
    / "System32"
    / "WindowsPowerShell"
    / "v1.0"
    / "powershell.exe"
)


def test_source_launcher_refreshes_runtime_and_prepares_production_frontend() -> None:
    launcher = (REPOSITORY_ROOT / "start_server.bat").read_text(encoding="utf-8")

    source_runtime_refresh = (
        'if exist "%SOURCE_APP_DIR%\\agent_shell\\__main__.py" (\n'
        "  call :prepare_runtime\n"
        ") else if not exist \"%PYTHON_HOME_FILE%\" ("
    )
    assert source_runtime_refresh in launcher
    assert launcher.index(source_runtime_refresh) < launcher.index(
        'set /p PYTHON_HOME=<"%PYTHON_HOME_FILE%"'
    )
    assert "prepare_source_frontend.ps1" in launcher
    assert "--probe-listen-settings" in launcher
    assert "start_dev.ps1" not in launcher
    assert "npm run dev" not in launcher


def test_source_launcher_confirms_initialization_only_without_data_config() -> None:
    launcher = (REPOSITORY_ROOT / "start_server.bat").read_text(encoding="utf-8")

    config_guard = 'if not exist "%SCRIPT_DIR%data\\config\\" ('
    confirmation = (
        'set /p "INITIALIZE_CONFIRMATION='
        'Continue with initialization? [y/n]: "'
    )
    assert launcher.index('set "SCRIPT_DIR=%~dp0"') < launcher.index(config_guard)
    assert launcher.index(config_guard) < launcher.index(confirmation)


def test_windows_launcher_prepares_dependencies_in_server_process() -> None:
    launcher = (REPOSITORY_ROOT / "start_server.bat").read_text(encoding="utf-8")

    assert launcher.count("--prepare-launch-settings") == 1
    assert "--initialize-local-settings" not in launcher
    assert "--print-launch-settings" not in launcher
    assert launcher.count("-m agent_shell --home") == 3
    assert "--port !EFFECTIVE_PORT! --prepare-dependencies" in launcher
    assert "-m agent_shell.python_packages.dependencies" not in launcher


def test_frontend_build_output_stays_outside_python_source() -> None:
    python_source_output = (
        REPOSITORY_ROOT / "server" / "src" / "agent_shell" / "frontend_dist"
    )
    vite_config = (REPOSITORY_ROOT / "frontend" / "vite.config.ts").read_text(
        encoding="utf-8"
    )
    preparer = (
        REPOSITORY_ROOT
        / "packaging"
        / "development"
        / "prepare_source_frontend.ps1"
    ).read_text(encoding="utf-8")

    assert not python_source_output.exists()
    assert "../runtime/frontend_dist" in vite_config
    assert 'Join-Path $project "runtime\\frontend_dist"' in preparer
    assert "server\\src\\agent_shell\\frontend_dist" not in preparer


def test_windows_runtime_removes_uv_python_aliases_after_pip_install() -> None:
    bootstrap = (
        REPOSITORY_ROOT / "packaging" / "windows" / "bootstrap_runtime.ps1"
    ).read_text(encoding="utf-8")

    cleanup = (
        "Remove-UvPythonInstallArtifacts $pythonInstallRoot "
        "$pythonExe.Directory.FullName"
    )
    pip_install = '"pip", "install", "--target", $installTarget'

    assert bootstrap.count(cleanup) == 2
    assert bootstrap.index(cleanup) < bootstrap.index(pip_install)
    assert bootstrap.rindex(cleanup) > bootstrap.index(pip_install)


def test_windows_runtime_allows_source_builds_and_limits_path_files() -> None:
    bootstrap = (
        REPOSITORY_ROOT / "packaging" / "windows" / "bootstrap_runtime.ps1"
    ).read_text(encoding="utf-8")

    path_file_filter = (
        '$_.Name -notlike "*-nspkg.pth" -and $_.Name -ne "pywin32.pth" '
        '-and $_.Name -ne "distutils-precedence.pth"'
    )
    assert "--only-binary" not in bootstrap
    assert bootstrap.count(path_file_filter) == 2


def test_windows_runtime_unwraps_powershell_file_system_exceptions_for_retry() -> None:
    bootstrap = (
        REPOSITORY_ROOT / "packaging" / "windows" / "bootstrap_runtime.ps1"
    ).read_text(encoding="utf-8")

    assert "function Test-IsRetryableFileSystemException" in bootstrap
    assert "$current = $current.InnerException" in bootstrap
    assert bootstrap.count("Test-IsRetryableFileSystemException $_.Exception") == 2
    assert "catch [System.IO.IOException]" not in bootstrap
    assert "$maxAttempts = 120" in bootstrap
    assert "remained in use for 30 seconds" in bootstrap


def test_windows_runtime_manifest_is_written_as_utf8_without_bom() -> None:
    bootstrap = (
        REPOSITORY_ROOT / "packaging" / "windows" / "bootstrap_runtime.ps1"
    ).read_text(encoding="utf-8")

    assert "[System.Text.UTF8Encoding]::new($false)" in bootstrap
    assert "runtime-manifest.json\") -Encoding utf8" not in bootstrap


def test_listen_probe_reports_an_occupied_port_without_starting_the_app(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from agent_shell import __main__ as launcher

    environment_path = tmp_path / "data" / "config" / "agent-shell.env"
    environment_path.parent.mkdir(parents=True, exist_ok=True)
    environment_path.write_text(
        serialize_environment(
            {"AGENT_SHELL_MANAGEMENT_TOKEN": "management-secret"}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        launcher,
        "_run_server",
        lambda *_args, **_kwargs: pytest.fail("a listen probe must not start the server"),
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = launcher.run_cli(
            [
                "--home",
                str(tmp_path),
                "--port",
                str(port),
                "--probe-listen-settings",
            ]
        )

    assert result == 3
    captured = capsys.readouterr()
    assert "occupied or reserved" in captured.err
    assert launcher.listen_address_is_available("127.0.0.1", port) is True


@pytest.mark.skipif(os.name != "nt", reason="source launcher is Windows-only")
def test_source_frontend_preparer_builds_only_when_inputs_change(
    tmp_path: Path,
) -> None:
    project = tmp_path / "source clone"
    frontend = project / "frontend"
    output = project / "runtime" / "frontend_dist"
    fake_bin = tmp_path / "fake-bin"
    invocation_log = tmp_path / "npm-invocations.txt"
    frontend.mkdir(parents=True)
    (frontend / "src").mkdir()
    (frontend / "public").mkdir()
    fake_bin.mkdir()
    for name in (
        "package.json",
        "package-lock.json",
        "index.html",
        "vite.config.ts",
        "tsconfig.json",
        "tsconfig.app.json",
        "tsconfig.node.json",
    ):
        (frontend / name).write_text(f"{name}\n", encoding="utf-8")
    source_file = frontend / "src" / "main.ts"
    source_file.write_text("export const value = 1\n", encoding="utf-8")
    (frontend / "public" / "favicon.ico").write_bytes(b"icon")

    fake_npm = fake_bin / "npm.cmd"
    fake_npm.write_text(
        "@echo off\n"
        "echo %*>>\"%FAKE_NPM_LOG%\"\n"
        "if \"%3\"==\"ci\" (\n"
        "  if not exist \"%~2\\node_modules\\.bin\" mkdir \"%~2\\node_modules\\.bin\"\n"
        "  echo @exit /b 0>\"%~2\\node_modules\\.bin\\vite.cmd\"\n"
        ")\n"
        "if \"%3\"==\"run\" (\n"
        "  if not exist \"%FAKE_FRONTEND_OUTPUT%\\assets\" mkdir \"%FAKE_FRONTEND_OUTPUT%\\assets\"\n"
        "  echo ^<html^>ready^</html^>>\"%FAKE_FRONTEND_OUTPUT%\\index.html\"\n"
        "  echo ready>\"%FAKE_FRONTEND_OUTPUT%\\assets\\app.js\"\n"
        ")\n"
        "exit /b 0\n",
        encoding="ascii",
    )
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    environment["FAKE_NPM_LOG"] = str(invocation_log)
    environment["FAKE_FRONTEND_OUTPUT"] = str(output)
    script = (
        REPOSITORY_ROOT
        / "packaging"
        / "development"
        / "prepare_source_frontend.ps1"
    )

    def run_preparer() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                str(WINDOWS_POWERSHELL),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-ProjectRoot",
                str(project),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        )

    first = run_preparer()
    assert first.returncode == 0, first.stderr
    invocations = invocation_log.read_text(encoding="utf-8").splitlines()
    assert len(invocations) == 2
    assert invocations[0].endswith('frontend" ci')
    assert invocations[1].endswith('frontend" run build')
    assert (project / "runtime" / "source-frontend-manifest.json").is_file()

    second = run_preparer()
    assert second.returncode == 0, second.stderr
    assert "already current" in second.stdout
    assert len(invocation_log.read_text(encoding="utf-8").splitlines()) == 2

    source_file.write_text("export const value = 2\n", encoding="utf-8")
    third = run_preparer()
    assert third.returncode == 0, third.stderr
    invocations = invocation_log.read_text(encoding="utf-8").splitlines()
    assert invocations[-1].endswith('frontend" run build')
    assert len(invocations) == 3


def test_explicit_debug_uses_temporary_data_and_dynamic_ports() -> None:
    debug_script = (
        REPOSITORY_ROOT / "packaging" / "development" / "start_dev.ps1"
    ).read_text(encoding="utf-8")

    assert "Get-FreeLoopbackPort" in debug_script
    assert "GetTempPath" in debug_script
    assert '[string]$CredentialFile = ""' in debug_script
    assert "Debug credentials must be stored outside the source tree." in debug_script
    assert "loaded from the external credential file" in debug_script
    assert '"--data-dir"' in debug_script
    assert "Remove-Item -LiteralPath $dataRoot -Recurse -Force" in debug_script
    assert "9100" not in debug_script
    assert "19101" not in debug_script


def test_explicit_debug_writes_standard_dotenv_as_utf8_without_bom() -> None:
    debug_script = (
        REPOSITORY_ROOT / "packaging" / "development" / "start_dev.ps1"
    ).read_text(encoding="utf-8")

    assert "$managementTokenValue = $temporaryManagementPassword" in debug_script
    assert '"AGENT_SHELL_MANAGEMENT_TOKEN={0}`n" -f $managementTokenValue' in debug_script
    assert "[System.Text.UTF8Encoding]::new($false)" in debug_script
    assert (
        'Set-Content -LiteralPath (Join-Path $configRoot "agent-shell.env")'
        not in debug_script
    )
