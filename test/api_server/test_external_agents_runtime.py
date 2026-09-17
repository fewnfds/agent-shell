from __future__ import annotations

import hashlib
from pathlib import Path

from agent_shell.external_agents import binary as binary_module
from agent_shell.external_agents.binary import AntigravityCliRelease

from .support import *


RUNTIME_STATUS_PATH = "/agent-shell/api/external-agents/runtime/status"


def current_platform_release() -> AntigravityCliRelease:
    """Pin a fake release for the running platform.

    The shipped table carries only a windows-x64 artifact, so a probe on the
    Linux CI runner reports that no pinned release exists. Building the release
    for ``current_platform()`` keeps this API contract testable on every OS.
    """

    return AntigravityCliRelease(
        version="9.9.9",
        platform=binary_module.current_platform(),
        archive="agy_cli_windows_x64.zip",
        archive_sha256="0" * 64,
        archive_executable="antigravity.exe",
        executable="agy.exe",
        executable_sha256=hashlib.sha256(b"fake-agy").hexdigest(),
        download_url="https://example.invalid/agy_cli_windows_x64.zip",
    )


def test_runtime_status_reports_missing_binary_with_placement_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = current_platform_release()
    monkeypatch.setattr(
        binary_module,
        "ANTIGRAVITY_CLI_RELEASES",
        (release,),
    )
    expected = binary_module.binary_path(tmp_path / "runtime", release)

    with make_client(tmp_path, monkeypatch) as client:
        missing = client.get(RUNTIME_STATUS_PATH)
        resolved = client.get(RUNTIME_STATUS_PATH)

        expected.parent.mkdir(parents=True, exist_ok=True)
        expected.write_bytes(b"fake-agy")
        available = client.get(RUNTIME_STATUS_PATH)

    body = missing.json()
    assert missing.status_code == 200
    assert body["provider"] == "antigravity-cli"
    assert body["available"] is False
    assert body["version"] == "9.9.9"
    assert body["detail"]
    assert body["guidance"] == binary_module.install_guidance(
        release, expected
    )
    assert Path(body["expected_path"]) == expected
    assert str(Path(body["expected_path"])) == body["expected_path"]
    assert resolved.json()["expected_path"] == body["expected_path"]

    ready = available.json()
    assert ready["available"] is True
    assert ready["version"] == "9.9.9"
    assert ready["detail"] == ""
    assert ready["sha256"] == release.executable_sha256
