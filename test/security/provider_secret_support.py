from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import yaml

from agent_shell.app import create_app
from agent_shell.storage.environment import parse_environment_text
from support import ScopedAuthTestClient, configure_scope_tokens

LOCAL_SECRET = "local-provider-secret-sentinel"
REPLACEMENT_SECRET = "replacement-provider-secret-sentinel"

@pytest.fixture(autouse=True)
def clean_agent_shell_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.upper().startswith("AGENT_SHELL_") or key == "TEST_PROVIDER_KEY":
            monkeypatch.delenv(key, raising=False)


def make_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, Path]:
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    data_root = tmp_path / "data"
    return ScopedAuthTestClient(create_app()), data_root


def model_payload(
    name: str = "Secret model",
    credential: str | None = LOCAL_SECRET,
) -> dict:
    return {
        "name": name,
        "provider": "openai",
        "base_url": "https://provider.example/v1",
        "credential": credential,
        "model": "provider-model",
        "provider_settings": {
            "temperature": 0.7,
            "max_completion_tokens": 4096,
        },
        "tool_choice": None,
        "response_format": None,
        "model_settings": {},
    }


def connection_storage_payload(
    data_root: Path,
    connection_id: str,
) -> tuple[dict, list[dict[str, str]]]:
    document = yaml.safe_load(
        (
            data_root
            / "config"
            / "model-connections"
            / f"{connection_id}.yaml"
        ).read_text(encoding="utf-8")
    )
    payload = {
        "id": document["id"],
        "name": document["name"],
        **document["payload"],
    }
    environment: dict[str, str] = {}
    env_path = data_root / "config" / "agent-shell.env"
    if env_path.exists():
        environment = {
            key: value
            for key, value in parse_environment_text(
                env_path.read_text(encoding="utf-8")
            ).items()
            if key.startswith("AGENT_SHELL_MODEL_")
        }
    secrets = [
        {"id": key, "secret_value": value}
        for key, value in sorted(environment.items())
    ]
    return payload, secrets


__all__ = [
    "LOCAL_SECRET",
    "REPLACEMENT_SECRET",
    "clean_agent_shell_environment",
    "connection_storage_payload",
    "make_client",
    "model_payload",
]
