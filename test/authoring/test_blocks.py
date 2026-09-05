from __future__ import annotations

import runpy
import shutil

import pytest

from agent_shell.storage.file_config import FileConfigRepository

from .app_support import *


def _write_package_template(
    tmp_path: Path,
    *,
    category: tuple[str, str],
    key: str,
    family: str,
    adapter: str,
    source: str,
) -> None:
    folder = tmp_path / "data" / "templates" / category[0] / category[1] / key
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "main.py").write_text(source, encoding="utf-8")


def test_health_catalog_and_readiness_are_small_and_current(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)

    assert client.get("/agent-shell/api/health").json() == {
        "status": "ok",
        "runtime": "model_streaming",
    }
    catalog = client.get("/agent-shell/api/catalog").json()
    assert set(catalog) == {
        "block_types",
        "resource_component_types",
        "workflow_component_types",
        "editor_defaults",
    }
    assert set(catalog["editor_defaults"]) == {
        "response_stream_scheduling",
        "filesystem",
        "filesystem_tools",
        "skill",
        "subagent",
        "todo_list",
        "agent_event_output",
        "exception_retry",
        "summarization",
        "prompt_caching",
        "workflow_event_output",
        "command",
    }
    assert [item["type"] for item in catalog["block_types"]] == list(PUBLIC_TYPES)
    assert [item["order"] for item in catalog["block_types"]] == list(range(1, 14))
    assert [item["type"] for item in catalog["resource_component_types"]] == [
        "mcp-requirement"
    ]
    assert [item["type"] for item in catalog["workflow_component_types"]] == [
        "workflow-event-output",
        "response-stream-scheduling",
        "command",
    ]
    assert catalog["editor_defaults"]["response_stream_scheduling"] == {
        "queue": {
            "strategy": "request",
            "idle_timeout_seconds": 2.0,
            "max_batch_kb": 64.0,
            "send_interval_seconds": 0.05,
        }
    }
    by_type = {item["type"]: item for item in catalog["block_types"]}
    assert set(by_type["model-requirement"]) == {
        "type",
        "terminology_key",
        "label",
        "order",
        "icon_key",
        "editor_key",
        "subagent_overrideable",
        "required",
        "subagent_policy",
        "agent_selectable",
        "tool_names",
    }
    assert by_type["model-requirement"]["required"] is True
    assert by_type["filesystem"]["required"] is True
    assert by_type["agent-event-output"]["required"] is True
    assert by_type["filesystem"]["tool_names"] == []
    assert by_type["filesystem-tools"]["tool_names"] == [
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "delete",
        "glob",
        "grep",
        "execute",
    ]
    assert by_type["todo-list"]["tool_names"] == ["write_todos"]
    assert by_type["agent-event-output"]["subagent_policy"] == "top-level-only"
    assert by_type["agent-event-output"]["subagent_overrideable"] is False
    readiness = client.get("/agent-shell/api/readiness").json()
    assert readiness["status"] == "configuration_ready"
    assert set(readiness["sections"]) == {
        "security_settings",
        "storage",
        "runtime_dependencies",
    }
    assert readiness["sections"]["storage"]["status"] == (
        "startup_permissions_confirmed"
    )
    assert readiness["sections"]["runtime_dependencies"]["status"] == "ready"
    assert readiness["sections"]["runtime_dependencies"]["code"] == "model_streaming"


def test_builtin_event_output_examples_are_loadable(
    tmp_path: Path, monkeypatch
) -> None:
    source_root = Path(__file__).resolve().parents[2] / "examples"
    for component_type, source_path in (
        (
            "agent-event-output",
            source_root / "agent-components" / "agent-event-output",
        ),
        (
            "workflow-event-output",
            source_root / "workflow-components" / "workflow-event-output",
        ),
    ):
        target = tmp_path / "examples" / source_path.relative_to(source_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_path, target)

    client = make_client(tmp_path, monkeypatch)
    for component_type, endpoint, expected_keys in (
        (
            "agent-event-output",
            "agent-event-output",
            {
                "内置示例-all-events",
                "内置示例-assistant-text-only",
                "内置示例-default",
            },
        ),
        (
            "workflow-event-output",
            "workflow-event-output",
            {
                "内置示例-all-events",
                "内置示例-default",
                "内置示例-lifecycle-progress",
            },
        ),
    ):
        catalog = client.get(
            f"/agent-shell/api/python-package-templates/{endpoint}"
        ).json()["catalog"]
        assert {item["key"] for item in catalog} == expected_keys
        for index, example in enumerate(catalog):
            response = client.post(
                f"/agent-shell/api/blocks/{component_type}",
                json={
                    "name": f"{component_type} example {index}",
                    "python_package": {"folder": ""},
                    "python_package_template": {
                        "key": example["key"],
                        "revision": example["revision"],
                    },
                },
            )
            assert response.status_code == 200, response.text
            created = response.json()
            inspection = client.get(
                f"/agent-shell/api/blocks/{component_type}/{created['id']}/python-package"
            )
            assert inspection.status_code == 200, inspection.text
            assert {item["path"] for item in inspection.json()["files"]} >= {
                "main.py",
                "package.json",
            }


def test_all_events_examples_render_streamed_and_atomic_event_families() -> None:
    source_root = Path(__file__).resolve().parents[2] / "examples"
    origin = {
        "lifecycle_id": "lifecycle-1",
        "run_id": "workflow-run-1",
        "thread_id": "thread-1",
        "assistant_id": "assistant-1",
        "workflow_id": "workflow-1",
        "workflow_node_id": "agent-node",
        "node_invocation_id": "invoke-1",
        "agent_profile_id": "agent-1",
    }

    def envelope(method: str, data: object, *, seq: int = 1) -> dict[str, object]:
        return {
            "method": method,
            "seq": seq,
            "params": {
                "namespace": ["agent-node:invoke-1"],
                "timestamp": 123,
                "data": data,
            },
        }

    def message(payload: dict[str, object], *, seq: int = 1) -> dict[str, object]:
        return envelope(
            "messages",
            [payload, {"run_id": "model-run-1", "langgraph_node": "model"}],
            seq=seq,
        )

    def assert_atomic(value: str) -> None:
        assert value.startswith("<details open>")
        assert value.endswith("</details>\n")
        assert "font-size:0.78em" in value
        assert "run_id=workflow-run-1" in value
        assert " | " in value
        assert "request_id=" not in value

    def assert_stream_end(value: str) -> None:
        assert value.startswith("</div>\n")
        assert value.endswith("</details>\n")
        assert "font-size:0.78em" in value
        assert "run_id=workflow-run-1" in value
        assert " | " in value

    for relative_path in (
        Path("agent-components/agent-event-output/all-events/main.py"),
        Path("workflow-components/workflow-event-output/all-events/main.py"),
    ):
        namespace = runpy.run_path(str(source_root / relative_path))
        output = namespace["output"]
        segment_end = namespace["segment_end"]

        assert_atomic(output(message({"event": "message-start", "id": "msg-1"}), origin))

        text_start = message({
            "event": "content-block-start",
            "index": 0,
            "content": {"type": "text", "text": ""},
        })
        assert output(text_start, origin).startswith("<details open>")
        assert not output(text_start, origin).endswith("</details>\n")
        assert_stream_end(segment_end(text_start, origin))
        text_delta = message({
            "event": "content-block-delta",
            "index": 0,
            "delta": {"type": "text-delta", "text": "<answer>"},
        })
        assert output(text_delta, origin) == "&lt;answer&gt;"
        assert_stream_end(output(message({
            "event": "content-block-finish",
            "index": 0,
            "content": {"type": "text", "text": "<answer>"},
        }), origin))

        reasoning_start = message({
            "event": "content-block-start",
            "index": 1,
            "content": {"type": "reasoning", "reasoning": ""},
        })
        assert output(reasoning_start, origin).startswith("<details open>")
        assert_stream_end(segment_end(reasoning_start, origin))
        assert output(message({
            "event": "content-block-delta",
            "index": 1,
            "delta": {"type": "reasoning-delta", "reasoning": "think"},
        }), origin) == "think"
        assert_stream_end(output(message({
            "event": "content-block-finish",
            "index": 1,
            "content": {"type": "reasoning", "reasoning": "think"},
        }), origin))

        tool_start = message({
            "event": "content-block-start",
            "index": 2,
            "content": {"type": "tool_call_chunk", "id": "call-1"},
        })
        assert output(tool_start, origin) == ""
        assert_atomic(output(message({
            "event": "content-block-finish",
            "index": 2,
            "content": {
                "type": "tool_call",
                "id": "call-1",
                "name": "lookup",
                "args": {"query": "value"},
            },
        }), origin))
        assert_atomic(output(message({
            "event": "content-block-finish",
            "index": 3,
            "content": {"type": "image", "url": "https://example.invalid/a.png"},
        }), origin))
        assert_atomic(output(message({"event": "message-finish", "usage": {}}), origin))
        assert_atomic(output(message({"event": "error", "error": "failed"}), origin))

        for tool_event in (
            {"event": "tool-started", "tool_call_id": "call-1", "name": "lookup"},
            {"event": "tool-output-delta", "tool_call_id": "call-1", "delta": "half"},
            {"event": "tool-finished", "tool_call_id": "call-1", "output": "done"},
            {"event": "tool-error", "tool_call_id": "call-1", "error": "failed"},
        ):
            assert_atomic(output(envelope("tools", tool_event), origin))
        for lifecycle_event in (
            {"event": "started", "graph_name": "worker"},
            {"event": "completed", "graph_name": "worker"},
            {"event": "failed", "graph_name": "worker"},
        ):
            assert_atomic(output(envelope("lifecycle", lifecycle_event), origin))
        assert_atomic(output(envelope("values", {"answer": 42}), origin))
        assert_atomic(output(envelope("custom", {"progress": "working"}), origin))
        assert_atomic(output(envelope("future-channel", {"future": True}), origin))

        if "run_output" in namespace:
            for phase in ("start", "end", "error"):
                assert_atomic(namespace["run_output"]({
                    "type": "agent_shell.workflow_run",
                    "phase": phase,
                    "status": "failed" if phase == "error" else "completed",
                    "finish_reason": "error" if phase == "error" else "stop",
                    "error_code": "failure" if phase == "error" else "",
                }, origin))


def test_command_uses_component_crud_storage_and_repository_validation(
    tmp_path: Path, monkeypatch
) -> None:
    source = (
        "def create_command():\n"
        "    async def route(state, runtime):\n"
        "        return {'activate': ['review'], 'update': {}}\n"
        "    return route\n"
    )
    _write_package_template(
        tmp_path,
        category=("workflow", "command"),
        key="risk-router",
        family="workflow-node",
        adapter="command",
        source=source,
    )
    client = make_client(tmp_path, monkeypatch)
    selected = client.get(
        "/agent-shell/api/python-package-templates/command"
    ).json()["catalog"][0]
    payload = {
        "name": "Risk routing",
        "python_package": {"folder": ""},
        "python_package_template": {
            "key": selected["key"],
            "revision": selected["revision"],
        },
    }

    created_response = client.post("/agent-shell/api/blocks/command", json=payload)
    assert created_response.status_code == 200
    created = created_response.json()
    assert client.get(
        f"/agent-shell/api/blocks/command/{created['id']}"
    ).json() == created
    assert (
        FileConfigRepository(tmp_path / "data").config_root
        / "components"
        / "command"
        / f"{created['id']}.yaml"
    ).is_file()
    assert client.get("/agent-shell/api/validation/repository").json()["valid"] is True

    invalid = {
        "name": payload["name"],
        "python_package": {"folder": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
    }
    rejected = client.put(
        f"/agent-shell/api/blocks/command/{created['id']}",
        json=invalid,
    )
    assert rejected.status_code == 409

    assert client.delete(
        f"/agent-shell/api/blocks/command/{created['id']}"
    ).json() == {"ok": True}


def test_block_crud_round_trips_every_form_payload(tmp_path: Path, monkeypatch) -> None:
    _write_package_template(
        tmp_path,
        category=("agent", "custom_tool"),
        key="word-count",
        family="tool",
        adapter="agent-tool",
        source=(
            "from langchain.tools import tool\n"
            "@tool\n"
            "def word_count(text: str) -> int:\n"
            "    \"\"\"Count words.\"\"\"\n"
            "    return len(text.split())\n"
            "def create_tool():\n"
            "    return word_count\n"
        ),
    )
    _write_package_template(
        tmp_path,
        category=("agent", "custom_middleware"),
        key="basic-middleware",
        family="middleware",
        adapter="agent-middleware",
        source=(
            "from langchain.agents.middleware import AgentMiddleware\n"
            "def create_middleware(agent):\n"
            "    return AgentMiddleware()\n"
        ),
    )
    _write_package_template(
        tmp_path,
        category=("agent", "agent_event_output"),
        key="timeline-output",
        family="event-output",
        adapter="agent-event-output",
            source='def output(event, origin):\n    return ""\n',
    )
    client = make_client(tmp_path, monkeypatch)

    for block_type, payload in block_cases(client, tmp_path):
        created_response = client.post(f"/agent-shell/api/blocks/{block_type}", json=payload)
        assert created_response.status_code == 200, created_response.text
        created = created_response.json()
        assert created["id"]
        assert created["name"] == payload["name"]
        if block_type == "filesystem":
            assert created["system_prompt_override"] == payload["system_prompt_override"]
            assert created["mapped_directories"][0]["permission"] == "read-only"
        if block_type == "filesystem-tools":
            assert created["tool_token_limit_before_evict"] == 4096
            assert all(
                config["description_override"] is None
                for config in created["tool_configs"].values()
            )
        if block_type == "skill":
            assert created["instruction_override"] is None
        if block_type == "subagent":
            assert created["instruction_override"] is None
            assert created["task_description_override"] is None
        if block_type in {"custom-tool", "custom-middleware", "agent-event-output"}:
            assert created["python_package"]["folder"] == created["name"]
        if block_type == "todo-list":
            assert created["system_prompt_override"] == payload[
                "system_prompt_override"
            ]
            assert created["tool_description_override"] == payload[
                "tool_description_override"
            ]
        listed = client.get(f"/agent-shell/api/blocks/{block_type}")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [created["id"]]
        assert client.get(f"/agent-shell/api/blocks/{block_type}/{created['id']}").json() == created
        update_payload = {**payload, "name": f"{payload['name']} updated"}
        if block_type in {"custom-tool", "custom-middleware", "agent-event-output"}:
            update_payload = {
                "name": f"{payload['name']} updated",
                "python_package": created["python_package"],
            }
        if block_type == "skill":
            update_payload = {
                "name": f"{payload['name']} updated",
                "skill_package": created["skill_package"],
            }
        updated = client.put(
            f"/agent-shell/api/blocks/{block_type}/{created['id']}", json=update_payload
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == update_payload["name"]

        copied = client.post(
            f"/agent-shell/api/blocks/{block_type}/{created['id']}/copy",
            json={"name": f"{payload['name']} copy"},
        )
        assert copied.status_code == 200, copied.text
        assert copied.json()["id"] != created["id"]

        assert client.delete(f"/agent-shell/api/blocks/{block_type}/{created['id']}").json() == {
            "ok": True
        }
        assert client.get(f"/agent-shell/api/blocks/{block_type}/{created['id']}").status_code == 404


@pytest.mark.parametrize(
    "namespace",
    (
        "/large_tool_results/",
        "/conversation_history/",
        "/skills/",
        "/memory/",
        "/memories/",
    ),
)
def test_filesystem_rejects_framework_reserved_virtual_namespaces(
    tmp_path: Path, monkeypatch, namespace: str
) -> None:
    client = make_client(tmp_path, monkeypatch)
    source_dir = tmp_path / "filesystem-source"
    source_dir.mkdir()
    source_file = source_dir / "note.txt"
    source_file.write_text("ordinary user file", encoding="utf-8")
    cases = (
        (
            "mapped_directories",
            {"virtual_path": namespace, "local_path": str(source_dir)},
        ),
        (
            "virtual_directories",
            {"virtual_path": namespace, "source_path": str(source_dir)},
        ),
        (
            "virtual_files",
            {
                "virtual_path": f"{namespace}note.txt",
                "source_path": str(source_file),
            },
        ),
    )

    for index, (field, item) in enumerate(cases):
        response = client.post(
            "/agent-shell/api/blocks/filesystem",
            json={"name": f"Reserved namespace {index}", field: [item]},
        )
        assert response.status_code == 422, (field, namespace, response.text)
        assert namespace.rstrip("/") in response.text


def test_filesystem_mapped_directory_modes_are_explicit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    relative = client.post(
        "/agent-shell/api/blocks/filesystem",
        json={
            "name": "Lifecycle mapping",
            "mapped_directories": [
                {
                    "virtual_path": "/workspace/",
                    "local_path": "files/workspaces",
                    "path_origin": "data-root-relative",
                    "lifecycle_mode": "dynamic",
                }
            ],
        },
    )
    assert relative.status_code == 200, relative.text
    assert relative.json()["mapped_directories"] == [
        {
            "virtual_path": "/workspace/",
            "local_path": "files/workspaces",
            "path_origin": "data-root-relative",
            "lifecycle_mode": "dynamic",
            "permission": "read-write",
        }
    ]

    for path_origin, local_path in (
        ("absolute", "relative/path"),
        ("data-root-relative", str(tmp_path.resolve())),
        ("data-root-relative", "C:relative"),
    ):
        response = client.post(
            "/agent-shell/api/blocks/filesystem",
            json={
                "name": f"Invalid {path_origin}",
                "mapped_directories": [
                    {
                        "virtual_path": "/workspace/",
                        "local_path": local_path,
                        "path_origin": path_origin,
                    }
                ],
            },
        )
        assert response.status_code == 422, response.text


def test_basic_payload_shape_errors_are_rejected(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    assert (
        client.post(
            "/agent-shell/api/blocks/model-requirement",
            json={"name": "only-name"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/agent-shell/api/blocks/system-prompt",
            json={"name": "empty", "system_prompt": ""},
        ).status_code
        == 422
    )

    empty_skill = client.post(
        "/agent-shell/api/blocks/skill",
        json={"name": "Empty Skill selection", "skill_template_paths": []},
    )
    removed_skill_switch = client.post(
        "/agent-shell/api/blocks/skill",
        json={"name": "Old Skill switch", "enabled": True, "skills": ["demo"]},
    )
    removed_subagent_switch = client.post(
        "/agent-shell/api/blocks/subagent",
        json={"name": "Old Subagent switch", "enabled": True},
    )

    assert empty_skill.status_code == 422, empty_skill.text
    assert removed_skill_switch.status_code == 422, removed_skill_switch.text
    assert removed_subagent_switch.status_code == 422, removed_subagent_switch.text


def test_filesystem_backend_types_reject_incompatible_fields(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    workspace = tmp_path / "local-shell-workspace"
    workspace.mkdir()

    for payload in (
        {
            "name": "Invalid permission",
            "mapped_directories": [
                {
                    "virtual_path": "/workspace/",
                    "local_path": str(workspace),
                    "permission": "execute-only",
                }
            ],
        },
        {
            "name": "LocalShell with Composite source",
            "backend_type": "local-shell",
            "workspace": {"local_path": str(workspace)},
            "mapped_directories": [
                {"virtual_path": "/workspace/", "local_path": str(workspace)}
            ],
        },
        {
            "name": "LocalShell with Skill package",
            "backend_type": "local-shell",
            "workspace": {"local_path": str(workspace)},
            "skill_package_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        },
        {
            "name": "Composite with LocalShell workspace",
            "backend_type": "composite",
            "workspace": {"local_path": str(workspace)},
        },
    ):
        response = client.post(
            "/agent-shell/api/blocks/filesystem",
            json=payload,
        )
        assert response.status_code == 422, response.text


def test_event_output_components_reject_invalid_package_entrypoints(
    tmp_path: Path, monkeypatch
) -> None:
    for category in (
        ("agent", "agent_event_output"),
        ("workflow", "workflow_event_output"),
    ):
        _write_package_template(
            tmp_path,
            category=category,
            key="invalid-entrypoint",
            family="event-output",
            adapter="event-output",
            source="def output(event, extra):\n    return ''\n",
        )
    client = make_client(tmp_path, monkeypatch)

    for endpoint in ("agent-event-output", "workflow-event-output"):
        catalog = client.get(f"/agent-shell/api/python-package-templates/{endpoint}").json()
        assert catalog["catalog"] == []
        assert set(catalog["errors"]) == {"invalid-entrypoint"}
