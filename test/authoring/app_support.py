from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from agent_shell.app import create_app
from agent_shell.capability_manifest import CAPABILITY_MANIFESTS
from support import ScopedAuthTestClient, configure_scope_tokens


PUBLIC_TYPES = tuple(manifest.type for manifest in CAPABILITY_MANIFESTS)


def subagent_payload(
    component_name: str,
    *,
    name: str = "worker",
    description: str = "Handles delegated work.",
    capability_overrides: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "component_name": component_name,
        "name": name,
        "description": description,
        "settings": {
            "capability_overrides": capability_overrides or [],
            "tool_refs": [],
            "middleware_refs": [],
        },
    }

def make_client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    return ScopedAuthTestClient(create_app())


def write_skill_template(
    tmp_path: Path,
    name: str = "outline",
    description: str = "Build a clear document outline.",
) -> Path:
    skill = tmp_path / "data" / "skills-template" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n",
        encoding="utf-8",
    )
    return skill


def model_payload(name: str = "Local model") -> dict:
    return {
        "name": name,
        "provider": "openai",
        "base_url": "http://127.0.0.1:8000/v1",
        "credential": "test-secret",
        "model": "test-model",
        "provider_settings": {
            "temperature": 0,
            "max_completion_tokens": 4096,
            "stream_usage": False,
            "streaming": True,
            "stop_sequences": ["END"],
        },
        "tool_choice": "auto",
        "response_format": {
            "title": "Answer",
            "description": "Structured answer returned by the model.",
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
        "model_settings": {"parallel_tool_calls": False},
    }


def python_component_payload(
    client: TestClient,
    component_type: str,
    name: str,
) -> dict:
    endpoint = {
        "custom-tool": "custom-tool",
        "custom-middleware": "middleware",
        "agent-event-output": "agent-event-output",
    }[component_type]
    selected = client.get(
        f"/api/python-package-templates/{endpoint}"
    ).json()["catalog"][0]
    return {
        "name": name,
        "python_package": {"folder": ""},
        "python_package_template": {
            "key": selected["key"],
            "revision": selected["revision"],
        },
    }


def block_cases(client: TestClient, tmp_path: Path) -> list[tuple[str, dict]]:
    mapped = tmp_path / "mapped"
    mapped.mkdir()
    write_skill_template(tmp_path)
    return [
        (
            "model-requirement",
            {
                "name": "Local model requirement",
                "description": "Use a local model suitable for general agent work.",
            },
        ),
        (
            "custom-tool",
            python_component_payload(client, "custom-tool", "Word count"),
        ),
        (
            "custom-middleware",
            python_component_payload(
                client,
                "custom-middleware",
                "Reliability middleware",
            ),
        ),
        (
            "agent-event-output",
            python_component_payload(
                client,
                "agent-event-output",
                "Development timeline",
            ),
        ),
        (
            "exception-retry",
            {
                "name": "Reliable completion",
                "strategy": "provider_native",
                "force_non_streaming": False,
                "max_retries": 2,
                "retry_on": [
                    "transport_error",
                    "timeout",
                    "rate_limit",
                    "server_error",
                ],
            },
        ),
        (
            "filesystem",
            {
                "name": "Workspace",
                "backend_type": "composite",
                "mapped_directories": [
                    {
                        "virtual_path": "/workspace/",
                        "local_path": str(mapped),
                        "permission": "read-only",
                    }
                ],
                "system_prompt_override": "Use only the configured workspace.",
            },
        ),
        (
            "filesystem-tools",
            {
                "name": "Workspace tools",
                "tool_token_limit_before_evict": 4096,
                "tool_configs": {
                    "read_file": {"visible": True},
                    "write_file": {"visible": True},
                },
            },
        ),
        (
            "skill",
            {"name": "Writing skills", "skill_template_paths": ["outline"]},
        ),
        (
            "system-prompt",
            {"name": "Concise", "system_prompt": "Be concise."},
        ),
        ("subagent", {"name": "Delegation"}),
        (
            "summarization",
            {
                "name": "Long-context summarization",
                "trigger": {"type": "tokens", "value": 120000},
                "keep": {"type": "messages", "value": 8},
            },
        ),
        (
            "prompt-caching",
            {
                "name": "One-hour prompt cache",
                "ttl": "1h",
                "min_messages_to_cache": 4,
            },
        ),
        (
            "todo-list",
            {
                "name": "Complex task planning",
                "system_prompt_override": "Track complex work and update each completed step.",
                "tool_description_override": None,
            },
        ),
    ]
