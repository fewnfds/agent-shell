from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Any
from uuid import UUID

import httpx
import yaml

from agent_shell.capability_manifest import CAPABILITY_MANIFESTS
from agent_shell.storage.api_server import ApiServerStore
from agent_shell.storage.configuration_mutations import ConfigurationMutationCoordinator
from agent_shell.storage.database import SQLiteDatabase
from agent_shell.storage.environment import (
    InstanceEnvironmentStore,
    SYSTEM_SETTINGS_ENVIRONMENT_OWNER,
    parse_environment_text,
)
from agent_shell.storage.file_config import FileConfigRepository


CAPABILITY_TYPES = tuple(manifest.type for manifest in CAPABILITY_MANIFESTS)
CRUD_CAPABILITY_TYPES = tuple(
    capability_type
    for capability_type in CAPABILITY_TYPES
    if capability_type != "custom-middleware"
)
MODEL_PARAMETER_NAMES = (
    "temperature",
    "max_completion_tokens",
    "top_p",
    "stop_sequences",
    "presence_penalty",
    "frequency_penalty",
    "seed",
    "timeout",
    "max_retries",
    "stream_usage",
    "streaming",
    "reasoning_effort",
    "service_tier",
    "logprobs",
    "top_logprobs",
)


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _model_connection_payload(
    name: str,
    secret: str | None,
    *,
    update: bool,
) -> dict:
    model_parameters = dict.fromkeys(MODEL_PARAMETER_NAMES)
    if update:
        model_parameters.update(
            {
                "temperature": 0,
                "max_completion_tokens": 2048,
                "top_p": 0.9,
                "stop_sequences": ["END", "STOP"],
                "presence_penalty": 0,
                "frequency_penalty": 0,
                "seed": 42,
                "timeout": 30,
                "max_retries": 2,
                "stream_usage": True,
                "streaming": True,
                "reasoning_effort": "medium",
                "service_tier": "auto",
                "logprobs": False,
                "top_logprobs": 5,
            }
        )
    return {
        "name": name,
        "provider": "openai",
        "base_url": "https://provider.example.invalid/v1",
        "credential": secret,
        "model": "smoke-model",
        "provider_settings": model_parameters,
        "tool_choice": None,
        "response_format": None,
        "model_settings": {},
    }


def _payload(
    capability_type: str,
    name: str,
    *,
    template: dict[str, str] | None = None,
) -> dict:
    payloads = {
        "model-requirement": {
            "name": name,
            "description": "Use the model connection selected for this instance.",
        },
        "filesystem": {"name": name},
        "filesystem-tools": {"name": name},
        "skill": {
            "name": name,
            "skill_template_paths": ["fixture-skill"],
        },
        "system-prompt": {"name": name, "system_prompt": "Smoke prompt."},
        "subagent": {"name": name},
        "summarization": {"name": name},
        "prompt-caching": {"name": name},
        "todo-list": {"name": name},
        "exception-retry": {
            "name": name,
            "strategy": "provider_native",
            "force_non_streaming": False,
            "max_retries": 2,
            "retry_on": ["transport_error", "timeout", "rate_limit", "server_error"],
        },
    }
    if capability_type in {"custom-tool", "agent-event-output"}:
        if template is None:
            raise AssertionError(f"missing Python template for {capability_type}")
        return {
            "name": name,
            "python_package": {"folder": ""},
            "python_package_template": template,
        }
    return payloads[capability_type]


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    expected: int = 200,
) -> httpx.Response:
    response = client.request(method, path, headers=headers, json=json_body)
    if response.status_code != expected:
        raise AssertionError(
            f"{method} {path}: expected {expected}, got {response.status_code}: {response.text}"
        )
    return response


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        process.kill()
    process.wait(timeout=8)


def _run_mode(repo_root: Path, scratch_root: Path) -> dict:
    mode = "authenticated"
    work = scratch_root / mode
    work.mkdir(parents=True, exist_ok=True)
    data_dir = work / "data"
    database_path = data_dir / "state" / "agent-shell.sqlite3"
    port = _port()
    management_token = secrets.token_urlsafe(32)
    api_key = secrets.token_urlsafe(32)
    provider_secret = "smoke-provider-" + secrets.token_urlsafe(24)
    process_environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("AGENT_SHELL_")
    }
    mutations = ConfigurationMutationCoordinator()
    instance_environment = InstanceEnvironmentStore(
        data_dir / "config" / "agent-shell.env",
        mutations=mutations,
    )
    configuration = FileConfigRepository(
        data_dir,
        mutations=mutations,
        environment=instance_environment,
    )
    skill_template = data_dir / "skills-template" / "fixture-skill"
    skill_template.mkdir(parents=True, exist_ok=True)
    (skill_template / "SKILL.md").write_text(
        "---\nname: fixture-skill\ndescription: Exercise the process smoke.\n---\n",
        encoding="utf-8",
    )
    tool_template = (
        data_dir / "templates" / "agent" / "custom_tool" / "smoke-tool"
    )
    tool_template.mkdir(parents=True, exist_ok=True)
    (tool_template / "main.py").write_text(
        "from langchain.tools import tool\n"
        "@tool\n"
        "def smoke_tool(value: str) -> str:\n"
        "    \"\"\"Return the supplied value.\"\"\"\n"
        "    return value\n"
        "def create_tool():\n"
        "    return smoke_tool\n",
        encoding="utf-8",
    )
    output_template = (
        data_dir
        / "templates"
        / "agent"
        / "agent_event_output"
        / "smoke-output"
    )
    output_template.mkdir(parents=True, exist_ok=True)
    (output_template / "main.py").write_text(
        'def output(event, origin):\n'
        '    if event.get("method") != "messages":\n'
        '        return ""\n'
        '    data = event.get("params", {}).get("data", ())\n'
        '    if not isinstance(data, (list, tuple)) or len(data) != 2:\n'
        '        return ""\n'
        '    payload = data[0]\n'
        '    if isinstance(payload, dict) and payload.get("event") == "content-block-delta":\n'
        '        delta = payload.get("delta", {})\n'
        '        return str(delta.get("text", "")) if isinstance(delta, dict) else ""\n'
        '    return str(getattr(payload, "text", "") or "")\n',
        encoding="utf-8",
    )
    workflow_output_template = (
        data_dir
        / "templates"
        / "workflow"
        / "workflow_event_output"
        / "smoke-workflow-output"
    )
    workflow_output_template.mkdir(parents=True, exist_ok=True)
    (workflow_output_template / "main.py").write_text(
        'def output(event, origin):\n'
        '    if event.get("method") != "values":\n'
        '        return ""\n'
        '    params = event.get("params")\n'
        '    data = params.get("data") if isinstance(params, dict) else None\n'
        '    if not isinstance(data, dict) or "shared_vars" not in data:\n'
        '        return ""\n'
        '    return "workflow values\\n"\n'
        'def run_output(event, origin):\n'
        '    if event.get("type") != "agent_shell.workflow_run":\n'
        '        return ""\n'
        '    return f"workflow {event.get(\'status\', \'\')}\\n"\n',
        encoding="utf-8",
    )
    command_template = (
        data_dir
        / "templates"
        / "workflow"
        / "command"
        / "smoke-workflow-run"
    )
    command_template.mkdir(parents=True, exist_ok=True)
    (command_template / "main.py").write_text(
        'from pathlib import Path\n'
        'from langgraph.types import Command\n'
        '\n'
        'def create_command():\n'
        '    target_workflow_id = Path(__file__).with_name("target.txt").read_text(encoding="utf-8").strip()\n'
        '    async def command(state, runtime):\n'
        '        runs = runtime.context.workflow_runs\n'
        '        if runs is None:\n'
        '            raise RuntimeError("Workflow Run commands are unavailable")\n'
        '        handle = await runs.start_workflow(\n'
        '            target_workflow_id,\n'
        '            operation_id="smoke-spawn",\n'
        '        )\n'
        '        joined = await runs.join([handle.run_id])\n'
        '        return Command(goto="end", update={"shared_vars": {\n'
        '            "spawned_run_id": handle.run_id,\n'
        '            "spawned_status": joined[0].status,\n'
        '            "spawned_output": joined[0].output,\n'
        '        }})\n'
        '    return command\n',
        encoding="utf-8",
    )
    instance_environment.patch(
        SYSTEM_SETTINGS_ENVIRONMENT_OWNER,
        set_values={"AGENT_SHELL_MANAGEMENT_TOKEN": management_token},
    )
    configuration.update_system(
        lambda system: system["settings"].update(
            {
                "host": "127.0.0.1",
                "port": port,
                "cors_origins": ["https://console.example.invalid"],
            }
        )
    )
    ApiServerStore(
        SQLiteDatabase(database_path),
        configuration,
        instance_environment,
        mutations,
    ).update_settings(
        api_key_operation="replace",
        api_key=api_key,
    )
    output_path = work / "server-output.txt"
    output = output_path.open("wb")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "agent_shell",
            "--home",
            str(work),
            "--data-dir",
            str(data_dir),
        ],
        cwd=repo_root / "server",
        env=process_environment,
        stdout=output,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    base_url = f"http://127.0.0.1:{port}"
    management = {"Authorization": f"Bearer {management_token}"}
    inference = {"Authorization": f"Bearer {api_key}"}
    client = httpx.Client(base_url=base_url, timeout=3, trust_env=False)
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                if client.get("/agent-shell/api/health").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if process.poll() is not None:
                output.flush()
                startup_output = output_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
                raise AssertionError(
                    "server exited before health became available:\n"
                    + startup_output
                )
            if time.monotonic() >= deadline:
                raise AssertionError("server did not become healthy")
            time.sleep(0.1)

        admin = _request(client, "GET", "/admin")
        admin_assets = set(
            re.findall(r'(?:src|href)="(/admin/assets/[^"]+)"', admin.text)
        )
        assert admin_assets
        assert not any(
            path.endswith(("/icons.js", "/api.js")) or "/vendor/" in path
            for path in admin_assets
        )
        for path in admin_assets:
            _request(client, "GET", path)
        health = _request(client, "GET", "/agent-shell/api/health").json()
        assert health == {"status": "ok", "runtime": "model_streaming"}
        docs = _request(client, "GET", "/docs")
        assert "agent server api reference" in docs.text.lower()
        openapi = _request(client, "GET", "/openapi.json").json()
        assert openapi["components"]["securitySchemes"]["ManagementBearer"] == {
            "type": "http",
            "scheme": "bearer",
        }
        assert openapi["components"]["securitySchemes"]["ApiKeyBearer"] == {
            "type": "http",
            "scheme": "bearer",
        }
        assert openapi["security"] == [{"ManagementBearer": []}]
        assert openapi["paths"]["/agent-shell/api/health"]["get"]["security"] == []
        assert openapi["paths"]["/compat/openai/v1/models"]["get"][
            "security"
        ] == [{"ApiKeyBearer": []}]
        assert openapi["paths"]["/compat/openai/v1/chat/completions"]["post"][
            "security"
        ] == [{"ApiKeyBearer": []}]
        for public_path in ("/ok", "/info", "/metrics"):
            assert _request(client, "GET", public_path).status_code == 200
            assert openapi["paths"][public_path]["get"]["security"] == []
        assert "/api/health" not in openapi["paths"]
        assert "/v1/models" not in openapi["paths"]
        openapi_paths = tuple(openapi["paths"])
        for route_prefix in (
            "/assistants",
            "/threads",
            "/runs",
            "/store",
            "/mcp",
            "/a2a/",
        ):
            assert any(path.startswith(route_prefix) for path in openapi_paths)
        _request(client, "GET", "/api/health", headers=management, expected=404)
        _request(client, "GET", "/v1/models", headers=management, expected=404)
        _request(client, "POST", "/threads/search", json_body={}, expected=401)
        _request(client, "GET", "/agent-shell/api/catalog", expected=401)
        _request(client, "GET", "/agent-shell/api/catalog", headers=inference, expected=403)
        _request(client, "GET", "/compat/openai/v1/unknown", headers=management, expected=403)
        _request(client, "GET", "/compat/openai/v1/unknown", headers=inference, expected=401)
        catalog = _request(client, "GET", "/agent-shell/api/catalog", headers=management).json()
        assert tuple(item["type"] for item in catalog["block_types"]) == CAPABILITY_TYPES
        tool_templates = _request(
            client,
            "GET",
            "/agent-shell/api/python-package-templates/custom-tool",
            headers=management,
        ).json()
        _request(client, "GET", "/agent-shell/api/python-package-templates/middleware", headers=management)
        output_templates = _request(
            client,
            "GET",
            "/agent-shell/api/python-package-templates/agent-event-output",
            headers=management,
        ).json()
        workflow_output_templates = _request(
            client,
            "GET",
            "/agent-shell/api/python-package-templates/workflow-event-output",
            headers=management,
        ).json()
        command_templates = _request(
            client,
            "GET",
            "/agent-shell/api/python-package-templates/command",
            headers=management,
        ).json()
        _request(client, "GET", "/agent-shell/api/skills", headers=management)
        readiness = _request(
            client, "GET", "/agent-shell/api/readiness", headers=management
        ).json()
        assert set(readiness["sections"]) == {
            "security_settings",
            "storage",
            "runtime_dependencies",
        }
        assert readiness["sections"]["storage"]["status"] == (
            "startup_permissions_confirmed"
        )
        preflight = _request(
            client,
            "OPTIONS",
            "/agent-shell/api/catalog",
            headers={
                "Origin": "https://console.example.invalid",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization, X-Request-ID",
            },
        )
        assert preflight.headers["access-control-allow-origin"] == (
            "https://console.example.invalid"
        )

        template_by_type = {
            "custom-tool": {
                "key": tool_templates["catalog"][0]["key"],
                "revision": tool_templates["catalog"][0]["revision"],
            },
            "agent-event-output": {
                "key": output_templates["catalog"][0]["key"],
                "revision": output_templates["catalog"][0]["revision"],
            },
        }
        workflow_output_template_reference = {
            "key": workflow_output_templates["catalog"][0]["key"],
            "revision": workflow_output_templates["catalog"][0]["revision"],
        }
        workflow_output = _request(
            client,
            "POST",
            "/agent-shell/api/blocks/workflow-event-output",
            headers=management,
            json_body={
                "name": f"{mode}-workflow-output",
                "python_package": {"folder": ""},
                "python_package_template": workflow_output_template_reference,
            },
        ).json()
        target_workflow = _request(
            client,
            "POST",
            "/agent-shell/api/workflows",
            headers=management,
            json_body={
                "name": f"{mode}-spawned-workflow",
                "description": "A normal Workflow started by another Run.",
                "workflow_event_output_id": workflow_output["id"],
            },
        ).json()
        _request(
            client,
            "PUT",
            f"/agent-shell/api/workflows/{target_workflow['id']}/graph",
            headers=management,
            json_body={
                "definition": {
                    "schema_version": 1,
                    "state_contract": "agent-shell.workflow.control.v1",
                    "nodes": [
                        {"id": "start", "type": "start", "type_version": 1, "config": {}},
                        {"id": "end", "type": "end", "type_version": 1, "config": {}},
                    ],
                    "edges": [
                        {
                            "id": "start-end",
                            "source": "start",
                            "source_handle": "next",
                            "target": "end",
                            "target_handle": "in",
                        }
                    ],
                },
                "layout": {
                    "nodes": {"start": {"x": 0, "y": 0}, "end": {"x": 240, "y": 0}},
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            },
        )
        (command_template / "target.txt").write_text(
            target_workflow["id"],
            encoding="utf-8",
        )
        command_templates = _request(
            client,
            "GET",
            "/agent-shell/api/python-package-templates/command",
            headers=management,
        ).json()
        command_template_reference = {
            "key": command_templates["catalog"][0]["key"],
            "revision": command_templates["catalog"][0]["revision"],
        }
        workflow_command = _request(
            client,
            "POST",
            "/agent-shell/api/blocks/command",
            headers=management,
            json_body={
                "name": f"{mode}-workflow-run-command",
                "python_package": {"folder": ""},
                "python_package_template": command_template_reference,
                "mcp_refs": [],
            },
        ).json()
        workflow = _request(
            client,
            "POST",
            "/agent-shell/api/workflows",
            headers=management,
            json_body={
                "name": f"{mode}-official-workflow",
                "description": "Exercise request and spawned official Runs.",
                "is_model_entry": True,
                "workflow_event_output_id": workflow_output["id"],
            },
        ).json()
        _request(
            client,
            "PUT",
            f"/agent-shell/api/workflows/{workflow['id']}/graph",
            headers=management,
            json_body={
                "definition": {
                    "schema_version": 1,
                    "state_contract": "agent-shell.workflow.control.v1",
                    "nodes": [
                        {
                            "id": "start",
                            "type": "start",
                            "type_version": 1,
                            "config": {},
                        },
                        {
                            "id": "command",
                            "type": "command",
                            "type_version": 1,
                            "config": {"command_id": workflow_command["id"]},
                        },
                        {
                            "id": "end",
                            "type": "end",
                            "type_version": 1,
                            "config": {},
                        },
                    ],
                    "edges": [
                        {
                            "id": "start-command",
                            "source": "start",
                            "source_handle": "next",
                            "target": "command",
                            "target_handle": "in",
                        },
                        {
                            "id": "command-end",
                            "source": "command",
                            "source_handle": "next",
                            "target": "end",
                            "target_handle": "in",
                        }
                    ],
                },
                "layout": {
                    "nodes": {
                        "start": {"x": 0, "y": 0},
                        "command": {"x": 240, "y": 0},
                        "end": {"x": 480, "y": 0},
                    },
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            },
        )
        completion = _request(
            client,
            "POST",
            "/compat/openai/v1/chat/completions",
            headers=inference,
            json_body={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        ).json()
        completion_text = completion["choices"][0]["message"]["content"]
        output.flush()
        smoke_runtime_output = output_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        assert completion_text.count("workflow completed\n") >= 2, (
            completion,
            smoke_runtime_output,
        )
        assert completion_text.count("workflow values\n") >= 2, completion
        assert completion["choices"][0]["finish_reason"] == "stop"
        lifecycle_page = _request(
            client,
            "GET",
            "/agent-shell/api/workflow-lifecycles?page=1&page_size=10",
            headers=management,
        ).json()
        lifecycle = next(
            item
            for item in lifecycle_page["items"]
            if any(
                subject["graph_kind"] == "workflow"
                and subject["id"] == workflow["id"]
                and subject["name"] == workflow["name"]
                for subject in item["subjects"]
            )
        )
        assert lifecycle["run_count"] >= 2
        assert lifecycle["active_run_count"] == 0
        lifecycle_id = lifecycle["lifecycle_id"]
        snapshot = _request(
            client,
            "GET",
            f"/agent-shell/api/workflow-lifecycles/{lifecycle_id}/monitoring/snapshot",
            headers=management,
        ).json()
        assert len(snapshot["runs"]) >= 2
        inspected_run = snapshot["runs"][0]
        run_id = inspected_run["run_id"]
        graph = _request(
            client,
            "GET",
            f"/agent-shell/api/workflow-lifecycles/{lifecycle_id}/monitoring/runs/{run_id}/graph",
            headers=management,
        ).json()
        assert graph["run_id"] == run_id
        state = _request(
            client,
            "GET",
            f"/agent-shell/api/workflow-lifecycles/{lifecycle_id}/monitoring/runs/{run_id}/state",
            headers=management,
        ).json()
        assert state["thread_id"] == inspected_run["thread_id"]
        history = _request(
            client,
            "GET",
            f"/agent-shell/api/workflow-lifecycles/{lifecycle_id}/monitoring/runs/{run_id}/history?limit=10",
            headers=management,
        ).json()
        assert history["thread_id"] == inspected_run["thread_id"]
        model_connection = _request(
            client,
            "POST",
            "/agent-shell/api/model-connections",
            headers={**management, "X-Request-ID": f"smoke-{mode}"},
            json_body=_model_connection_payload(
                f"{mode}-model-connection",
                provider_secret,
                update=False,
            ),
        ).json()
        UUID(model_connection["id"])
        assert model_connection["credential"] == {"status": "masked"}
        assert provider_secret not in json.dumps(model_connection)

        blocks: dict[str, dict] = {}
        for capability_type in CRUD_CAPABILITY_TYPES:
            created = _request(
                client,
                "POST",
                f"/agent-shell/api/blocks/{capability_type}",
                headers={**management, "X-Request-ID": f"smoke-{mode}"},
                json_body=_payload(
                    capability_type,
                    f"{mode}-{capability_type}",
                    template=template_by_type.get(capability_type),
                ),
            ).json()
            UUID(created["id"])
            assert provider_secret not in json.dumps(created)
            blocks[capability_type] = created
            listed = _request(
                client, "GET", f"/agent-shell/api/blocks/{capability_type}", headers=management
            ).json()
            assert any(item["id"] == created["id"] for item in listed)
            fetched = _request(
                client,
                "GET",
                f"/agent-shell/api/blocks/{capability_type}/{created['id']}",
                headers=management,
            ).json()
            assert fetched["id"] == created["id"]
            if capability_type in {"custom-tool", "agent-event-output"}:
                update_payload = {
                    "name": f"{mode}-{capability_type}-updated",
                    "python_package": created["python_package"],
                }
            elif capability_type == "skill":
                update_payload = {
                    "name": f"{mode}-{capability_type}-updated",
                    "skill_package": created["skill_package"],
                }
            else:
                update_payload = _payload(
                    capability_type,
                    f"{mode}-{capability_type}-updated",
                )
            updated = _request(
                client,
                "PUT",
                f"/agent-shell/api/blocks/{capability_type}/{created['id']}",
                headers=management,
                json_body=update_payload,
            ).json()
            assert updated["id"] == created["id"]

        updated_model_payload = _model_connection_payload(
            f"{mode}-model-connection-updated",
            None,
            update=True,
        )
        updated_model = _request(
            client,
            "PUT",
            f"/agent-shell/api/model-connections/{model_connection['id']}",
            headers=management,
            json_body=updated_model_payload,
        ).json()
        assert updated_model["provider_settings"]["stop_sequences"] == [
            "END",
            "STOP",
        ]
        assert updated_model["provider_settings"]["streaming"] is True
        assert updated_model["provider_settings"]["stream_usage"] is True
        _request(
            client,
            "PUT",
            (
                "/agent-shell/api/model-requirements/"
                f"{blocks['model-requirement']['id']}/binding"
            ),
            headers=management,
            json_body={"connection_id": model_connection["id"]},
        )

        main_agent = _request(
            client,
            "POST",
            "/agent-shell/api/main-agents",
            headers=management,
            json_body={
                "name": f"{mode}-main-agent",
                "capability_refs": [
                    {
                        "type": "filesystem",
                        "block_id": blocks["filesystem"]["id"],
                    },
                    {
                        "type": "filesystem-tools",
                        "block_id": blocks["filesystem-tools"]["id"],
                    },
                    {
                        "type": "model-requirement",
                        "block_id": blocks["model-requirement"]["id"],
                    },
                    {
                        "type": "agent-event-output",
                        "block_id": blocks["agent-event-output"]["id"],
                    },
                ],
                "subagents": [],
            },
        ).json()
        subagent = _request(
            client,
            "POST",
            "/agent-shell/api/subagents",
            headers=management,
            json_body={
                "component_name": f"{mode}-subagent",
                "name": "smoke_worker",
                "description": "Handles smoke-test delegated work.",
                "settings": {
                    "capability_overrides": [],
                },
            },
        ).json()
        for path, item in (
            ("main-agents", main_agent),
            ("subagents", subagent),
        ):
            UUID(item["id"])
            _request(client, "GET", f"/agent-shell/api/{path}", headers=management)
            fetched = _request(
                client, "GET", f"/agent-shell/api/{path}/{item['id']}", headers=management
            ).json()
            assert fetched["id"] == item["id"]
        updated_main_agent = dict(main_agent)
        updated_main_agent.pop("id")
        updated_main_agent["name"] += "-updated"
        _request(
            client,
            "PUT",
            f"/agent-shell/api/main-agents/{main_agent['id']}",
            headers=management,
            json_body=updated_main_agent,
        )
        updated_subagent = dict(subagent)
        updated_subagent.pop("id")
        updated_subagent["component_name"] += "-updated"
        _request(
            client,
            "PUT",
            f"/agent-shell/api/subagents/{subagent['id']}",
            headers=management,
            json_body=updated_subagent,
        )

        model_id = model_connection["id"]
        model_path = (
            data_dir / "config" / "model-connections" / f"{model_id}.yaml"
        )
        model_text = model_path.read_text(encoding="utf-8")
        assert provider_secret not in model_text
        model_document = yaml.safe_load(model_text)
        model_secret_name = model_document["payload"]["credential"]["reference"]
        environment_path = data_dir / "config" / "agent-shell.env"
        environment_values = parse_environment_text(
            environment_path.read_text(encoding="utf-8")
        )
        assert environment_values[model_secret_name] == provider_secret
        with closing(sqlite3.connect(database_path)) as connection, connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            assert not ({"blocks", "provider_secrets", "workflows"} & tables)
            assert "checkpoints" not in tables
            assert "store" not in tables
        assert not (data_dir / "state" / "workflow-checkpoints.sqlite3").exists()
        assert not (data_dir / "state" / "workflow-store.sqlite3").exists()
        assert (data_dir / "state" / "langgraph-dev").is_dir()
        event_path = data_dir / "logs" / "security-events.jsonl"
        event_text = event_path.read_text(encoding="utf-8")
        assert provider_secret not in event_text
        assert management_token not in event_text
        assert api_key not in event_text

        _request(
            client,
            "DELETE",
            f"/agent-shell/api/workflow-lifecycles/{lifecycle_id}",
            headers=management,
        )

        _request(
            client,
            "DELETE",
            f"/agent-shell/api/workflows/{workflow['id']}",
            headers=management,
        )
        _request(
            client,
            "DELETE",
            f"/agent-shell/api/workflows/{target_workflow['id']}",
            headers=management,
        )
        _request(
            client,
            "DELETE",
            f"/agent-shell/api/blocks/command/{workflow_command['id']}",
            headers=management,
        )
        _request(
            client,
            "DELETE",
            f"/agent-shell/api/blocks/workflow-event-output/{workflow_output['id']}",
            headers=management,
        )
        _request(
            client,
            "DELETE",
            f"/agent-shell/api/main-agents/{main_agent['id']}",
            headers=management,
        )
        _request(
            client,
            "DELETE",
            f"/agent-shell/api/subagents/{subagent['id']}",
            headers=management,
        )
        _request(
            client,
            "DELETE",
            f"/agent-shell/api/model-connections/{model_id}",
            headers=management,
        )
        for capability_type, block in blocks.items():
            _request(
                client,
                "DELETE",
                f"/agent-shell/api/blocks/{capability_type}/{block['id']}",
                headers=management,
            )
        final_environment = parse_environment_text(
            environment_path.read_text(encoding="utf-8")
        )
        assert provider_secret not in final_environment.values()
        assert model_secret_name not in final_environment
        return {
            "mode": mode,
            "capability_count": len(blocks),
            "readiness_sections": len(readiness["sections"]),
            "authenticated": True,
        }
    finally:
        client.close()
        _stop_process(process)
        output.close()
        if process.returncode not in {0, 1, -15}:
            raise AssertionError(f"server shutdown failed in {mode} mode")
        if output_path.exists():
            output_text = output_path.read_text(encoding="utf-8", errors="replace")
            for sentinel in (management_token, api_key, provider_secret):
                if sentinel in output_text:
                    raise AssertionError("server output contained a secret sentinel")
            if "You've set --allow-blocking" in output_text:
                raise AssertionError("server enabled the global blocking-I/O override")
            if "identified a synchronous blocking call" in output_text:
                raise AssertionError("normal smoke path blocked the server event loop")
        # Windows can briefly retain a delete-denying handle after the child
        # process exits even though wait() has completed. Give the OS a small
        # release window before TemporaryDirectory removes the isolated run.
        if os.name == "nt":
            time.sleep(0.25)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    scratch_parent = repo_root / "runtime" / "tmp"
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="security-http-smoke-", dir=scratch_parent
    ) as scratch:
        root = Path(scratch)
        reports = [_run_mode(repo_root, root)]
    leftovers = list(scratch_parent.glob("security-http-smoke-*"))
    if leftovers:
        raise AssertionError("security smoke left temporary artifacts")
    print(json.dumps({"status": "passed", "modes": reports}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
