from __future__ import annotations

import hashlib
from dataclasses import replace

from agent_shell.external_agents import binary as binary_module

from .support import *


RUNTIME_STATUS_PATH = "/agent-shell/api/external-agents/runtime/status"


def test_runtime_status_reports_missing_binary_with_placement_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        missing = client.get(RUNTIME_STATUS_PATH)
        resolved = client.get(RUNTIME_STATUS_PATH)

        release = binary_module.pinned_release()
        assert release is not None
        fake = replace(
            release,
            version="9.9.9",
            executable_sha256=hashlib.sha256(b"fake-agy").hexdigest(),
        )
        monkeypatch.setattr(
            binary_module,
            "ANTIGRAVITY_CLI_RELEASES",
            (fake,),
        )
        expected = binary_module.binary_path(tmp_path / "runtime", fake)
        expected.parent.mkdir(parents=True, exist_ok=True)
        expected.write_bytes(b"fake-agy")
        available = client.get(RUNTIME_STATUS_PATH)

    body = missing.json()
    assert missing.status_code == 200
    assert body["provider"] == "antigravity-cli"
    assert body["available"] is False
    assert body["detail"]
    assert (
        body["guidance"]
        == binary_module.install_guidance(release, Path(body["expected_path"]))
    )
    assert str(Path(body["expected_path"])) == body["expected_path"]
    assert resolved.json()["expected_path"] == body["expected_path"]

    ready = available.json()
    assert ready["available"] is True
    assert ready["version"] == "9.9.9"
    assert ready["detail"] == ""
    assert ready["sha256"] == fake.executable_sha256
