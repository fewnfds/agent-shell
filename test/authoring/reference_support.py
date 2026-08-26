from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from agent_shell.app import create_app
from agent_shell.capability_manifest import CAPABILITY_MANIFESTS
from support import ScopedAuthTestClient, configure_scope_tokens


PUBLIC_TYPES = tuple(manifest.type for manifest in CAPABILITY_MANIFESTS)
MAIN_AGENT_TYPES = tuple(
    manifest.type
    for manifest in CAPABILITY_MANIFESTS
    if manifest.agent_selectable
    and manifest.type not in {"custom-tool", "custom-middleware"}
)
OVERRIDEABLE_TYPES = tuple(
    manifest.type
    for manifest in CAPABILITY_MANIFESTS
    if manifest.agent_selectable and manifest.subagent_overrideable
)
REQUIRED_TYPES = tuple(
    manifest.type for manifest in CAPABILITY_MANIFESTS if manifest.required
)


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
    template = (
        tmp_path
        / "data"
        / "templates"
        / "agent"
        / "custom_middleware"
        / "reference-middleware"
    )
    template.mkdir(parents=True, exist_ok=True)
    (template / "main.py").write_text(
        "from langchain.agents.middleware import AgentMiddleware\n"
        "def create_middleware(agent):\n"
        "    return AgentMiddleware()\n",
        encoding="utf-8",
    )
    output_template = (
        tmp_path
        / "data"
        / "templates"
        / "agent"
        / "agent_event_output"
        / "reference-output"
    )
    output_template.mkdir(parents=True, exist_ok=True)
    (output_template / "main.py").write_text(
        'def output(event):\n    return event["message"]\n',
        encoding="utf-8",
    )
    tool_template = (
        tmp_path
        / "data"
        / "templates"
        / "agent"
        / "custom_tool"
        / "reference-tool"
    )
    tool_template.mkdir(parents=True, exist_ok=True)
    (tool_template / "main.py").write_text(
        "from langchain.tools import tool\n"
        "@tool\n"
        "def reference_tool(value: str) -> str:\n"
        "    \"\"\"Return the supplied value.\"\"\"\n"
        "    return value\n"
        "def create_tool():\n"
        "    return reference_tool\n",
        encoding="utf-8",
    )
    skill = tmp_path / "data" / "skills-template" / "fixture-skill"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "---\nname: fixture-skill\ndescription: Exercise Skill references.\n---\n",
        encoding="utf-8",
    )
    return ScopedAuthTestClient(create_app())


def block_payload(capability_type: str, name: str) -> dict:
    payloads = {
        "model-requirement": {
            "name": name,
            "description": "Use a model suitable for the reference test.",
        },
        "custom-tool": {"name": name},
        "custom-middleware": {"name": name},
        "agent-event-output": {"name": name},
        "filesystem": {"name": name},
        "filesystem-tools": {"name": name},
        "skill": {
            "name": name,
            "skill_template_paths": ["fixture-skill"],
        },
        "system-prompt": {"name": name, "system_prompt": "Fixture prompt."},
        "subagent": {"name": name},
        "todo-list": {"name": name},
        "exception-retry": {
            "name": name,
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
        "summarization": {"name": name},
        "prompt-caching": {"name": name},
    }
    return payloads[capability_type]


def create_blocks(client: TestClient, suffix: str, types=PUBLIC_TYPES) -> dict[str, dict]:
    blocks = {}
    for capability_type in types:
        payload = block_payload(capability_type, f"{capability_type}-{suffix}")
        if capability_type in {"custom-tool", "custom-middleware", "agent-event-output"}:
            endpoint = {
                "custom-tool": "custom-tool",
                "custom-middleware": "middleware",
                "agent-event-output": "agent-event-output",
            }[capability_type]
            selected = client.get(
                f"/api/python-package-templates/{endpoint}"
            ).json()["catalog"][0]
            payload = {
                **payload,
                "python_package": {"folder": ""},
                "python_package_template": {
                    "key": selected["key"],
                    "revision": selected["revision"],
                },
            }
        response = client.post(
            f"/api/blocks/{capability_type}",
            json=payload,
        )
        assert response.status_code == 200, response.text
        blocks[capability_type] = response.json()
    return blocks


def references(blocks: dict[str, dict], types=PUBLIC_TYPES) -> list[dict]:
    return [
        {"type": capability_type, "block_id": blocks[capability_type]["id"]}
        for capability_type in types
    ]
