from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from uuid import UUID, uuid4

from agent_shell.external_agents.contracts import ExternalAgentRunResult
from agent_shell.external_agents.runtime import AntigravityRunner

from .support import *


COMMAND_KEY = "external-agent-command"
COMMAND_SOURCE = '''\
from langgraph.types import Command


def create_command():
    async def command(state, runtime):
        facade = getattr(runtime.context, "external_agent", None)
        if facade is None:
            raise RuntimeError("runtime.context.external_agent is not configured")
        result = await facade.run("ping from command")
        return Command(
            update={
                "external_agent": {
                    "name": facade.name,
                    "agent_name": facade.agent_name,
                    "status": result.status,
                    "response": result.response,
                }
            }
        )

    return command
'''


def external_agent_payload() -> dict[str, object]:
    return {
        "name": "Antigravity Reviewer",
        "description": "Reviews a diff and returns findings.",
        "provider": "antigravity-cli",
        "agent_name": "antigravity-reviewer",
        "system_prompt": "You review diffs and answer with findings only.",
        "model": None,
        "effort": "low",
        "print_timeout": "5m",
        "output_format": "stream-json",
        "conversation": "new",
        "exclude_default_components": True,
        "tools": ["view_file"],
        "tool_guidance": "Read files with absolute paths.",
        "tool_permission": "request-review",
        "permission_allow": ["read_file(*)"],
        "env": {},
    }


def stub_result() -> ExternalAgentRunResult:
    session = f"sessions/{uuid4()}"
    return ExternalAgentRunResult(
        status="success",
        response="stub reply",
        conversation_id=str(uuid4()),
        conversation_requested="new",
        conversation_reused=False,
        exit_code=0,
        duration_ms=5,
        usage={"total_tokens": 3},
        denied_actions=(),
        error_code=None,
        error_message=None,
        session_directory=session,
        event_log=f"{session}/events.ndjson",
        stderr_log=f"{session}/stderr.log",
        result_file=f"{session}/result.json",
    )


def write_command_template(tmp_path: Path) -> None:
    package_dir = (
        tmp_path / "data" / "templates" / "workflow" / "command" / COMMAND_KEY
    )
    package_dir.mkdir(parents=True)
    (package_dir / "main.py").write_text(COMMAND_SOURCE, encoding="utf-8")


def create_command_block(client: TestClient) -> dict:
    selected = next(
        item
        for item in client.get(
            "/agent-shell/api/python-package-templates/command"
        ).json()["catalog"]
        if item["key"] == COMMAND_KEY
    )
    response = client.post(
        "/agent-shell/api/blocks/command",
        json={
            "name": "External Agent command",
            "python_package": {"folder": ""},
            "python_package_template": {
                "key": selected["key"],
                "revision": selected["revision"],
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def bound_workflow_document(
    command_id: str,
    external_agent_id: str | None,
) -> dict:
    config: dict[str, object] = {"command_id": command_id}
    if external_agent_id is not None:
        config["external_agent_id"] = external_agent_id
    return {
        "definition": {
            "schema_version": 1,
            "state_contract": "agent-shell.workflow.control.v1",
            "nodes": [
                {"id": "start", "type": "start", "type_version": 1, "config": {}},
                {
                    "id": "agent",
                    "type": "command",
                    "type_version": 1,
                    "config": config,
                },
                {"id": "end", "type": "end", "type_version": 1, "config": {}},
            ],
            "edges": [
                {
                    "id": "start-agent",
                    "source": "start",
                    "source_handle": "next",
                    "target": "agent",
                    "target_handle": "in",
                },
                {
                    "id": "agent-end",
                    "source": "agent",
                    "source_handle": "next",
                    "target": "end",
                    "target_handle": "in",
                },
            ],
        },
        "layout": {"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
    }


def test_deleting_a_bound_external_agent_demotes_the_published_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_command_template(tmp_path)

    with make_client(tmp_path, monkeypatch) as client:
        command = create_command_block(client)
        preset = client.post(
            "/agent-shell/api/external-agents",
            json=external_agent_payload(),
        ).json()
        workflow = create_workflow(client, name="Bound Workflow")
        published = client.put(
            f"/agent-shell/api/workflows/{workflow['id']}/graph",
            json=bound_workflow_document(command["id"], preset["id"]),
        )
        assert published.status_code == 200, published.text
        deleted = client.delete(
            f"/agent-shell/api/external-agents/{preset['id']}"
        )
        stored = client.get(
            f"/agent-shell/api/workflows/{workflow['id']}"
        ).json()
        graph = client.get(
            f"/agent-shell/api/workflows/{workflow['id']}/graph"
        ).json()
        issues = client.get(
            "/agent-shell/api/validation/repository"
        ).json()["issues"]

    assert deleted.status_code == 200, deleted.text
    assert stored["enabled"] is False
    assert graph["definition"]["nodes"][1]["config"]["external_agent_id"] == (
        preset["id"]
    )
    assert any(
        issue["code"] == "configuration.reference_not_found"
        and issue["path"] == "definition.nodes[1].config.external_agent_id"
        and issue["owner_id"] == workflow["id"]
        for issue in issues
    )


def test_workflow_bundle_closes_over_its_bound_external_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_command_template(tmp_path)

    with make_client(tmp_path, monkeypatch) as client:
        command = create_command_block(client)
        preset = client.post(
            "/agent-shell/api/external-agents",
            json=external_agent_payload(),
        ).json()
        workflow = create_workflow(client, name="Bound Workflow")
        client.put(
            f"/agent-shell/api/workflows/{workflow['id']}/graph",
            json=bound_workflow_document(command["id"], preset["id"]),
        )
        exported = client.post(
            "/agent-shell/api/configuration-bundles/export",
            json={"kind": "workflow", "source_id": workflow["id"]},
        )

    assert exported.status_code == 200, exported.text
    manifest = json.loads(
        zipfile.ZipFile(io.BytesIO(exported.content))
        .read("manifest.json")
    )
    kinds = {(record["kind"], record.get("type")) for record in manifest["records"]}
    assert ("external_agent", None) in kinds
    assert ("component", "command") in kinds


def test_command_node_reaches_its_bound_external_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_command_template(tmp_path)
    calls: list[dict[str, object]] = []

    async def fake_run(
        self,
        profile,
        *,
        external_agent_id,
        lifecycle_id,
        prompt,
        conversation=None,
        on_event=None,
    ):
        calls.append(
            {
                "preset_id": external_agent_id,
                "lifecycle_id": lifecycle_id,
                "prompt": prompt,
                "conversation": conversation,
                "profile_name": profile.name,
                "agent_name": profile.agent_name,
                "on_event": on_event,
            }
        )
        return stub_result()

    monkeypatch.setattr(AntigravityRunner, "run", fake_run)

    with make_client(tmp_path, monkeypatch) as client:
        preset = client.post(
            "/agent-shell/api/external-agents",
            json=external_agent_payload(),
        ).json()
        command = create_command_block(client)
        workflow = create_workflow(
            client,
            name="External Agent Workflow",
            is_model_entry=True,
        )
        graph = client.put(
            f"/agent-shell/api/workflows/{workflow['id']}/graph",
            json=bound_workflow_document(command["id"], preset["id"]),
        )
        response = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )

    assert graph.status_code == 200, graph.text
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert calls[0]["preset_id"] == preset["id"]
    assert calls[0]["prompt"] == "ping from command"
    assert calls[0]["conversation"] is None
    assert calls[0]["profile_name"] == "Antigravity Reviewer"
    assert calls[0]["agent_name"] == "antigravity-reviewer"
    assert calls[0]["on_event"] is None
    assert UUID(str(calls[0]["lifecycle_id"]))


def test_command_node_without_a_binding_reports_no_facade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_command_template(tmp_path)

    with make_client(tmp_path, monkeypatch) as client:
        command = create_command_block(client)
        workflow = create_workflow(
            client,
            name="Unbound External Agent Workflow",
            is_model_entry=True,
        )
        graph = client.put(
            f"/agent-shell/api/workflows/{workflow['id']}/graph",
            json=bound_workflow_document(command["id"], None),
        )
        response = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )

    assert graph.status_code == 200, graph.text
    assert response.status_code == 422
    # Public errors stay classified; the script's internal message is not
    # disclosed on the compat wire (docs/security-and-deployment.md).
    assert "external_agent is not configured" not in response.text


def test_unknown_external_agent_reference_is_rejected_at_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_command_template(tmp_path)

    with make_client(tmp_path, monkeypatch) as client:
        command = create_command_block(client)
        workflow = create_workflow(client, name="Broken Workflow")
        graph = client.put(
            f"/agent-shell/api/workflows/{workflow['id']}/graph",
            json=bound_workflow_document(command["id"], str(uuid4())),
        )

    assert graph.status_code == 422
    issues = graph.json()["detail"]["validation"]["issues"]
    assert any(
        issue["code"] == "configuration.reference_not_found"
        and issue["path"] == "definition.nodes[1].config.external_agent_id"
        for issue in issues
    )
