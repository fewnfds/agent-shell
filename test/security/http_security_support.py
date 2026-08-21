from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from agent_shell.storage.api_server import ApiServerStore
from agent_shell.storage.database import SQLiteDatabase
from agent_shell.storage.file_config import FileConfigRepository

MANAGEMENT_TOKEN = "management-test-secret-000000000000"
API_KEY = "api-test-secret-111111111111"

@pytest.fixture(autouse=True)
def clean_agent_shell_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.upper().startswith("AGENT_SHELL_"):
            monkeypatch.delenv(key, raising=False)


def _configure_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    FileConfigRepository(tmp_path / "data").set_secret(
        "AGENT_SHELL_MANAGEMENT_TOKEN", MANAGEMENT_TOKEN
    )


def _write_system_settings(root: Path, **values: object) -> None:
    path = root / "data" / "config" / "system.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"settings": values}), encoding="utf-8")


def _configure_auth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_paths(monkeypatch, tmp_path)
    database = SQLiteDatabase(tmp_path / "data" / "state" / "agent-shell.sqlite3")
    ApiServerStore(database, FileConfigRepository(tmp_path / "data")).update_settings(
        api_key_operation="replace",
        api_key=API_KEY,
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


__all__ = [
    "API_KEY",
    "MANAGEMENT_TOKEN",
    "_bearer",
    "_configure_auth",
    "_configure_paths",
    "_write_system_settings",
    "clean_agent_shell_environment",
]
