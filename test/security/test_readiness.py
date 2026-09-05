from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_shell.app import create_app
from agent_shell.storage.api_server import ApiServerStore
from agent_shell.storage.database import SQLiteDatabase
from agent_shell.storage.file_config import FileConfigRepository


MANAGEMENT_TOKEN = "readiness-management-token"
API_KEY = "readiness-api-key"


@pytest.fixture(autouse=True)
def clean_agent_shell_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.upper().startswith("AGENT_SHELL_"):
            monkeypatch.delenv(key, raising=False)


def _paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)


def _auth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _paths(monkeypatch, tmp_path)
    database = SQLiteDatabase(tmp_path / "data" / "state" / "agent-shell.sqlite3")
    repository = FileConfigRepository(tmp_path / "data")
    repository.set_secret("AGENT_SHELL_MANAGEMENT_TOKEN", MANAGEMENT_TOKEN)
    ApiServerStore(database, repository).update_settings(
        api_key_operation="replace",
        api_key=API_KEY,
    )


def _bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def test_readiness_is_partitioned_while_health_remains_minimal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth(monkeypatch, tmp_path)
    real_find_spec = __import__("agent_shell.readiness", fromlist=["find_spec"]).find_spec

    def selective_find_spec(module: str):
        if module in {"langchain_openai", "deepagents"}:
            return None
        return real_find_spec(module)

    monkeypatch.setattr("agent_shell.readiness.find_spec", selective_find_spec)

    with TestClient(create_app()) as client:
        health = client.get("/agent-shell/api/health")
        readiness = client.get(
            "/agent-shell/api/readiness", headers=_bearer(MANAGEMENT_TOKEN)
        )

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "runtime": "model_streaming"}
    assert readiness.status_code == 200
    report = readiness.json()
    assert report["status"] == "configuration_ready"
    assert set(report["sections"]) == {
        "security_settings",
        "storage",
        "runtime_dependencies",
    }
    assert report["sections"]["storage"]["status"] == (
        "startup_permissions_confirmed"
    )
    assert all(
        item["enforced"]
        for item in report["sections"]["storage"]["permissions"]
    )
    dependencies = report["sections"]["runtime_dependencies"]["dependencies"]
    assert report["sections"]["runtime_dependencies"]["status"] == "unavailable"
    assert report["sections"]["runtime_dependencies"]["code"] == "runtime_dependency_missing"
    assert dependencies["langchain"]["status"] == "available"
    assert dependencies["openai_provider"]["status"] == "unavailable"
    assert dependencies["deepagents"]["status"] == "unavailable"
    assert str(tmp_path) not in json.dumps(report)


def test_readiness_requires_deepagents_for_the_mandatory_filesystem_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth(monkeypatch, tmp_path)
    real_find_spec = __import__("agent_shell.readiness", fromlist=["find_spec"]).find_spec
    monkeypatch.setattr(
        "agent_shell.readiness.find_spec",
        lambda module: None if module == "deepagents" else real_find_spec(module),
    )

    with TestClient(create_app()) as client:
        report = client.get(
            "/agent-shell/api/readiness", headers=_bearer(MANAGEMENT_TOKEN)
        ).json()

    runtime = report["sections"]["runtime_dependencies"]
    assert runtime["status"] == "unavailable"
    assert runtime["code"] == "runtime_dependency_missing"
    assert runtime["dependencies"]["langchain"]["status"] == "available"
    assert runtime["dependencies"]["openai_provider"]["status"] == "available"
    assert runtime["dependencies"]["deepagents"]["status"] == "unavailable"


def test_readiness_and_runtime_diagnostics_require_management_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        health = client.get("/agent-shell/api/health")
        missing = client.get("/agent-shell/api/readiness")
        wrong = client.get("/agent-shell/api/readiness", headers=_bearer(API_KEY))
        ready = client.get("/agent-shell/api/readiness", headers=_bearer(MANAGEMENT_TOKEN))
        diagnostic_wrong = client.get(
            "/agent-shell/api/runtime-diagnostics", headers=_bearer(API_KEY)
        )
        diagnostic = client.get(
            "/agent-shell/api/runtime-diagnostics", headers=_bearer(MANAGEMENT_TOKEN)
        )

    assert health.status_code == 200
    assert missing.status_code == 401
    assert wrong.status_code == 403
    assert ready.status_code == 200
    assert diagnostic_wrong.status_code == 403
    assert diagnostic.status_code == 200
    payload = diagnostic.json()
    serialized = json.dumps(payload).lower()
    assert payload == {
        "retention_limit": 20,
    }
    assert str(tmp_path).lower() not in serialized
