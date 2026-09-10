from __future__ import annotations

from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
import threading
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


class _StreamingProviderHandler(BaseHTTPRequestHandler):
    """Minimal DeepSeek-compatible SSE provider for the event smoke."""

    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *args: object) -> None:
        del args

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        messages = payload.get("messages")
        has_tool_result = isinstance(messages, list) and any(
            isinstance(message, dict) and message.get("role") == "tool"
            for message in messages
        )
        is_persistence_child = isinstance(messages, list) and any(
            isinstance(message, dict)
            and message.get("role") == "user"
            and message.get("content") == "exercise persistence child"
            for message in messages
        )
        if self.path != "/v1/chat/completions" or not payload.get("stream"):
            self.send_error(404)
            return

        if is_persistence_child:
            chunks = [{"role": "assistant", "content": "persisted child"}]
            finish_reason = "stop"
        elif not has_tool_result:
            chunks = [
                {"role": "assistant", "reasoning_content": "think"},
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "smoke-call-1",
                            "type": "function",
                            "function": {
                                "name": "smoke_tool",
                                "arguments": '{"value":"observed"}',
                            },
                        }
                    ]
                },
            ]
            finish_reason = "tool_calls"
        else:
            chunks = [
                {"role": "assistant", "content": "runtime "},
                {"content": "reply"},
            ]
            finish_reason = "stop"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for delta in chunks:
            self._write_event(delta, None)
        self._write_event({}, finish_reason)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def _write_event(self, delta: dict[str, object], finish_reason: str | None) -> None:
        chunk = {
            "id": "chatcmpl-smoke",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "deepseek-reasoner",
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": finish_reason,
                }
            ],
        }
        body = "data: " + json.dumps(chunk, separators=(",", ":")) + "\n\n"
        self.wfile.write(body.encode("utf-8"))
        self.wfile.flush()


def _start_streaming_provider() -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StreamingProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stream_completion_text(
    client: httpx.Client,
    *,
    headers: dict[str, str],
    model: str,
) -> list[str]:
    fragments: list[str] = []
    with client.stream(
        "POST",
        "/compat/openai/v1/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": [{"role": "user", "content": "exercise events"}],
            "stream": True,
        },
    ) as response:
        if response.status_code != 200:
            raise AssertionError(
                f"stream completion failed: {response.status_code}: {response.read()!r}"
            )
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            value = line.removeprefix("data: ")
            if value == "[DONE]":
                break
            event = json.loads(value)
            choices = event.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            delta = choices[0].get("delta")
            content = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(content, str) and content:
                fragments.append(content)
    return fragments


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
        "model-call-limit": {"name": name, "run_limit": 20},
        "tool-call-limit": {"name": name, "run_limit": 20},
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
    timeout: float | None = None,
) -> httpx.Response:
    request_options = {}
    if timeout is not None:
        request_options["timeout"] = timeout
    response = client.request(
        method,
        path,
        headers=headers,
        json=json_body,
        **request_options,
    )
    if response.status_code != expected:
        raise AssertionError(
            f"{method} {path}: expected {expected}, got {response.status_code}: {response.text}"
        )
    return response


def _assert_lifecycle_persistence(
    client: httpx.Client,
    *,
    lifecycle_id: str,
    headers: dict[str, str],
    expected_graph_kinds: set[str],
    minimum_run_count: int,
) -> set[tuple[str, str, str]]:
    snapshot = _request(
        client,
        "GET",
        f"/agent-shell/api/workflow-lifecycles/{lifecycle_id}/monitoring/snapshot",
        headers=headers,
    ).json()
    assert snapshot["run_count"] >= minimum_run_count
    observed_runs = [
        (thread["thread_id"], observation)
        for thread in snapshot["threads"]
        for observation in thread["runs"]
        if observation["run"] is not None
    ]
    assert len(observed_runs) >= minimum_run_count
    identities: set[tuple[str, str, str]] = set()
    for thread_id, observation in observed_runs:
        relation = observation["relation"]
        assert relation is not None
        graph_kind = relation["graph_kind"]
        run_id = observation["run_id"]
        identities.add((graph_kind, thread_id, run_id))
        graph = _request(
            client,
            "GET",
            f"/agent-shell/api/workflow-lifecycles/{lifecycle_id}/monitoring/runs/{run_id}/graph",
            headers=headers,
        ).json()
        assert graph["run_id"] == run_id
        assert graph["error"] is None
        if graph_kind == "workflow":
            assert graph["graph"] is None
            assert graph["workflow_document"] is not None
        else:
            assert graph["graph"] is not None
            assert graph["workflow_document"] is None
        state = _request(
            client,
            "GET",
            f"/agent-shell/api/workflow-lifecycles/{lifecycle_id}/monitoring/runs/{run_id}/state",
            headers=headers,
        ).json()
        assert state["thread_id"] == thread_id
        assert state["state"]["checkpoint"] is not None
        history = _request(
            client,
            "GET",
            f"/agent-shell/api/workflow-lifecycles/{lifecycle_id}/monitoring/runs/{run_id}/history?limit=10",
            headers=headers,
        ).json()
        assert history["thread_id"] == thread_id
        assert history["history"]
        official_state = _request(
            client,
            "GET",
            f"/threads/{thread_id}/state",
            headers=headers,
        ).json()
        assert official_state["checkpoint"] is not None
    assert expected_graph_kinds <= {identity[0] for identity in identities}

    lifecycle_store = _request(
        client,
        "GET",
        f"/agent-shell/api/workflow-lifecycles/{lifecycle_id}/monitoring/store",
        headers=headers,
    ).json()
    namespace_leaves = {
        namespace["namespace"][-1]
        for namespace in lifecycle_store["namespaces"]
    }
    assert {"input", "runs"} <= namespace_leaves
    return identities


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
    provider_server, provider_thread = _start_streaming_provider()
    provider_port = int(provider_server.server_address[1])
    provider_base_url = f"http://127.0.0.1:{provider_port}/v1"
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
        'import json\n'
        'def output(event, origin):\n'
        '    method = event.get("method")\n'
        '    seq = str(event.get("seq") or "")\n'
        '    data = event.get("params", {}).get("data", ())\n'
        '    if method == "messages":\n'
        '        payload = data[0] if isinstance(data, (list, tuple)) and len(data) == 2 else data\n'
        '        if not isinstance(payload, dict):\n'
        '            return ""\n'
        '        event_name = str(payload.get("event") or "")\n'
        '        block = payload.get("content") or payload.get("delta") or {}\n'
        '        block_type = str(block.get("type") or "") if isinstance(block, dict) else ""\n'
        '        if event_name == "content-block-delta" and block_type == "reasoning-delta":\n'
        '            return "reasoning-delta:" + str(block.get("reasoning") or "") + "|seq=" + seq + "\\n"\n'
        '        if event_name == "content-block-delta" and block_type == "text-delta":\n'
        '            return "assistant-text-delta:" + str(block.get("text") or "") + "|seq=" + seq + "\\n"\n'
        '        if event_name == "content-block-finish" and block_type == "tool_call":\n'
        '            return "tool-call:" + json.dumps(block.get("args"), sort_keys=True) + "\\n"\n'
        '        return ""\n'
        '    if method == "tools" and isinstance(data, dict):\n'
        '        return "tool-execution:" + str(data.get("event") or "") + "\\n"\n'
        '    if method == "lifecycle" and isinstance(data, dict):\n'
        '        return "lifecycle:" + str(data.get("event") or "") + "|seq=" + seq + "\\n"\n'
        '    return ""\n',
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
        '    method = event.get("method")\n'
        '    params = event.get("params")\n'
        '    data = params.get("data") if isinstance(params, dict) else None\n'
        '    if method == "custom" and data == {"kind": "smoke-command-progress"}:\n'
        '        return "workflow custom progress\\n"\n'
        '    if method != "values":\n'
        '        return ""\n'
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
        'from langgraph.config import get_stream_writer\n'
        'from langgraph.types import Command\n'
        '\n'
        'def create_command():\n'
        '    target_workflow_id = Path(__file__).with_name("target-workflow.txt").read_text(encoding="utf-8").strip()\n'
        '    target_agent_id = Path(__file__).with_name("target-agent.txt").read_text(encoding="utf-8").strip()\n'
        '    async def command(state, runtime):\n'
        '        get_stream_writer()({"kind": "smoke-command-progress"})\n'
        '        workflow_runs = runtime.context.workflow_runs\n'
        '        agent_runs = runtime.context.agent_runs\n'
        '        if workflow_runs is None or agent_runs is None:\n'
        '            raise RuntimeError("Graph Run commands are unavailable")\n'
        '        workflow_handle = await workflow_runs.start_workflow(\n'
        '            target_workflow_id,\n'
        '            operation_id="smoke-workflow-spawn",\n'
        '        )\n'
        '        agent_handle = await agent_runs.start(\n'
        '            target_agent_id,\n'
        '            [{"role": "user", "content": "exercise persistence child"}],\n'
        '            operation_id="smoke-agent-spawn",\n'
        '        )\n'
        '        joined = await workflow_runs.join([workflow_handle.run_id])\n'
        '        joined_agent = await agent_runs.join(agent_handle.thread_id, agent_handle.run_id)\n'
        '        return Command(goto="end", update={"shared_vars": {\n'
        '            "spawned_run_id": workflow_handle.run_id,\n'
        '            "spawned_status": joined[0].status,\n'
        '            "spawned_output": joined[0].output,\n'
        '            "spawned_agent_run_id": agent_handle.run_id,\n'
        '            "spawned_agent_status": joined_agent.status,\n'
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
    server_arguments = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "agent_shell",
        "--home",
        str(work),
        "--data-dir",
        str(data_dir),
    ]
    process = subprocess.Popen(
        server_arguments,
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
        persistence_blocks: dict[str, dict] = {}
        for capability_type in (
            "filesystem",
            "filesystem-tools",
            "model-requirement",
            "agent-event-output",
        ):
            persistence_blocks[capability_type] = _request(
                client,
                "POST",
                f"/agent-shell/api/blocks/{capability_type}",
                headers=management,
                json_body=_payload(
                    capability_type,
                    f"{mode}-persistence-{capability_type}",
                    template=template_by_type.get(capability_type),
                ),
            ).json()
        persistence_model_connection = _request(
            client,
            "POST",
            "/agent-shell/api/model-connections",
            headers=management,
            json_body={
                "name": f"{mode}-persistence-model",
                "provider": "deepseek",
                "base_url": provider_base_url,
                "credential": provider_secret,
                "model": "deepseek-reasoner",
                "provider_settings": {"streaming": True},
                "tool_choice": None,
                "response_format": None,
                "model_settings": {},
            },
        ).json()
        _request(
            client,
            "PUT",
            (
                "/agent-shell/api/model-requirements/"
                f"{persistence_blocks['model-requirement']['id']}/binding"
            ),
            headers=management,
            json_body={"connection_id": persistence_model_connection["id"]},
        )
        persistence_main_agent = _request(
            client,
            "POST",
            "/agent-shell/api/main-agents",
            headers=management,
            json_body={
                "name": f"{mode}-persistence-agent",
                "capability_refs": [
                    {
                        "type": capability_type,
                        "block_id": persistence_blocks[capability_type]["id"],
                    }
                    for capability_type in (
                        "filesystem",
                        "filesystem-tools",
                        "model-requirement",
                        "agent-event-output",
                    )
                ],
                "tool_refs": [],
                "subagents": [],
            },
        ).json()
        persistence_main_agent = _request(
            client,
            "PUT",
            (
                "/agent-shell/api/main-agents/"
                f"{persistence_main_agent['id']}/publish"
            ),
            headers=management,
            json_body={
                key: value
                for key, value in persistence_main_agent.items()
                if key not in {"id", "enabled"}
            },
        ).json()
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
        (command_template / "target-workflow.txt").write_text(
            target_workflow["id"],
            encoding="utf-8",
        )
        (command_template / "target-agent.txt").write_text(
            persistence_main_agent["id"],
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
            timeout=20,
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
        assert "workflow custom progress\n" in completion_text, completion
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
        assert lifecycle["run_count"] >= 3
        assert lifecycle["active_run_count"] == 0
        assert {"agent", "workflow"} <= {
            subject["graph_kind"] for subject in lifecycle["subjects"]
        }
        lifecycle_id = lifecycle["lifecycle_id"]
        persisted_run_identities = _assert_lifecycle_persistence(
            client,
            lifecycle_id=lifecycle_id,
            headers=management,
            expected_graph_kinds={"agent", "workflow"},
            minimum_run_count=3,
        )
        persistence_dir = data_dir / "state" / "langgraph-dev" / ".langgraph_api"
        operations_path = persistence_dir / ".langgraph_ops.pckl"
        operations_mtime = (
            operations_path.stat().st_mtime_ns if operations_path.exists() else 0
        )
        persistence_deadline = time.monotonic() + 12
        while (
            not operations_path.exists()
            or operations_path.stat().st_mtime_ns <= operations_mtime
        ):
            if time.monotonic() >= persistence_deadline:
                raise AssertionError("LangGraph core resources were not persisted")
            time.sleep(0.1)
        client.close()
        _stop_process(process)
        process = subprocess.Popen(
            server_arguments,
            cwd=repo_root / "server",
            env=process_environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        client = httpx.Client(base_url=base_url, timeout=3, trust_env=False)
        deadline = time.monotonic() + 20
        while True:
            try:
                if client.get("/agent-shell/api/health").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if process.poll() is not None:
                output.flush()
                restart_output = output_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
                raise AssertionError(
                    "server exited before restart health became available:\n"
                    + restart_output
                )
            if time.monotonic() >= deadline:
                raise AssertionError("server did not become healthy after restart")
            time.sleep(0.1)
        restarted_run_identities = _assert_lifecycle_persistence(
            client,
            lifecycle_id=lifecycle_id,
            headers=management,
            expected_graph_kinds={"agent", "workflow"},
            minimum_run_count=3,
        )
        assert restarted_run_identities == persisted_run_identities
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
        runtime_model_connection = _request(
            client,
            "POST",
            "/agent-shell/api/model-connections",
            headers=management,
            json_body={
                "name": f"{mode}-event-stream-model",
                "provider": "deepseek",
                "base_url": provider_base_url,
                "credential": provider_secret,
                "model": "deepseek-reasoner",
                "provider_settings": {"streaming": True},
                "tool_choice": None,
                "response_format": None,
                "model_settings": {},
            },
        ).json()
        _request(
            client,
            "PUT",
            (
                "/agent-shell/api/model-requirements/"
                f"{blocks['model-requirement']['id']}/binding"
            ),
            headers=management,
            json_body={"connection_id": runtime_model_connection["id"]},
        )

        main_agent = _request(
            client,
            "POST",
            "/agent-shell/api/main-agents",
            headers=management,
            json_body={
                "name": f"{mode}-main-agent",
                "is_model_entry": True,
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
                "tool_refs": [{"tool_id": blocks["custom-tool"]["id"]}],
                "subagents": [],
            },
        ).json()
        main_agent = _request(
            client,
            "PUT",
            f"/agent-shell/api/main-agents/{main_agent['id']}/publish",
            headers=management,
            json_body={
                key: value
                for key, value in main_agent.items()
                if key not in {"id", "enabled"}
            },
        ).json()
        stream_fragments = _stream_completion_text(
            client,
            headers=inference,
            model=main_agent["name"],
        )
        streamed_output = "".join(stream_fragments)
        expected_event_text = (
            "reasoning-delta:think",
            'tool-call:{"value": "observed"}',
            "tool-execution:tool-started",
            "tool-execution:tool-finished",
            "assistant-text-delta:runtime ",
            "assistant-text-delta:reply",
            "lifecycle:running",
            "lifecycle:completed",
        )
        for expected in expected_event_text:
            assert expected in streamed_output, (expected, stream_fragments)
        text_chunk = next(
            index
            for index in range(len(stream_fragments))
            if "assistant-text-delta:" in stream_fragments[index]
        )
        terminal_chunk = next(
            index
            for index in range(len(stream_fragments))
            if "lifecycle:completed" in stream_fragments[index]
        )
        assert text_chunk < terminal_chunk, stream_fragments
        text_seq_match = re.search(
            r"assistant-text-delta:[^\n]*\|seq=(\d+)",
            streamed_output,
        )
        terminal_seq_match = re.search(
            r"lifecycle:completed\|seq=(\d+)",
            streamed_output,
        )
        assert text_seq_match is not None and terminal_seq_match is not None
        assert int(text_seq_match.group(1)) < int(terminal_seq_match.group(1))
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
        updated_main_agent.pop("enabled")
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
        langgraph_state_dir = data_dir / "state" / "langgraph-dev"
        checkpoint_database_path = langgraph_state_dir / "checkpoints.sqlite3"
        store_database_path = langgraph_state_dir / "store.sqlite3"
        assert checkpoint_database_path.is_file()
        assert store_database_path.is_file()
        with closing(sqlite3.connect(checkpoint_database_path)) as connection:
            checkpoint_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            assert {"checkpoints", "writes"} <= checkpoint_tables
        with closing(sqlite3.connect(store_database_path)) as connection:
            store_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            assert "store" in store_tables
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
            "GET",
            f"/agent-shell/api/workflow-lifecycles/{lifecycle_id}/monitoring/snapshot",
            headers=management,
            expected=404,
        )
        _request(
            client,
            "GET",
            f"/agent-shell/api/workflow-lifecycles/{lifecycle_id}/monitoring/store",
            headers=management,
            expected=404,
        )
        for _graph_kind, thread_id, _run_id in persisted_run_identities:
            _request(
                client,
                "GET",
                f"/threads/{thread_id}",
                headers=management,
                expected=404,
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
            f"/agent-shell/api/main-agents/{persistence_main_agent['id']}",
            headers=management,
        )
        _request(
            client,
            "DELETE",
            (
                "/agent-shell/api/model-connections/"
                f"{persistence_model_connection['id']}"
            ),
            headers=management,
        )
        for capability_type, block in persistence_blocks.items():
            _request(
                client,
                "DELETE",
                f"/agent-shell/api/blocks/{capability_type}/{block['id']}",
                headers=management,
            )
        _request(
            client,
            "DELETE",
            f"/agent-shell/api/model-connections/{model_id}",
            headers=management,
        )
        _request(
            client,
            "DELETE",
            (
                "/agent-shell/api/model-connections/"
                f"{runtime_model_connection['id']}"
            ),
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
        provider_server.shutdown()
        provider_server.server_close()
        provider_thread.join(timeout=5)
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
