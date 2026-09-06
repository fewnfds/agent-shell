from __future__ import annotations

from contextlib import closing
import os
import asyncio
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import (
    FakeListChatModel,
)
from langgraph.store.memory import InMemoryStore
from starlette.requests import Request

from agent_shell.app import create_app
from agent_shell.api.api_server import ApiServerEventHub
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.lifecycle_store import (
    LIFECYCLE_INPUT_KEY,
    lifecycle_input_namespace,
)
from support import API_KEY, ScopedAuthTestClient, configure_scope_tokens


EVENT_FEED_TEST_WINDOW = {
    "started_at": "2000-01-01T00:00:00+00:00",
    "ended_at": "2100-01-01T00:00:00+00:00",
}


def event_feed_params(**filters: object) -> dict[str, object]:
    return {**EVENT_FEED_TEST_WINDOW, **filters}


def event_feed_query_pairs(*filters: tuple[str, object]) -> list[tuple[str, object]]:
    return [*EVENT_FEED_TEST_WINDOW.items(), *filters]


class ToolCompatibleFakeListChatModel(FakeListChatModel):
    def _get_ls_params(self, stop=None, **kwargs):
        params = super()._get_ls_params(stop=stop, **kwargs)
        params["ls_provider"] = "openai"
        return params

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools=tools, **kwargs)


@pytest.fixture(autouse=True)
def clean_agent_shell_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.upper().startswith("AGENT_SHELL_"):
            monkeypatch.delenv(key, raising=False)


def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_shell.runtime.agent_builder._build_chat_model",
        lambda _block, _credential, _http_clients: ToolCompatibleFakeListChatModel(
            responses=["runtime reply"]
        ),
    )

    graph_store = InMemoryStore()

    async def direct_test_run(coordinator, workflow, raw_messages, **kwargs):
        """Stand in for the external dev server in API unit tests.

        The SDK/Agent Server boundary has its own direct tests and isolated
        process smoke. API unit tests execute the same frozen Graph locally so
        they do not depend on a second listening process.
        """

        document = coordinator._snapshot.workflow_document(str(workflow["id"]))
        if document is None:
            raise AgentRuntimeError(
                "workflow_graph_not_found",
                "The selected Workflow graph does not exist.",
                status_code=422,
            )
        lifecycle_id = str(uuid4())
        coordinator._lifecycle_id = lifecycle_id
        await graph_store.aput(
            lifecycle_input_namespace(lifecycle_id),
            LIFECYCLE_INPUT_KEY,
            {"messages": raw_messages},
            index=False,
        )
        runtime = coordinator._snapshot.new_runtime(
            store=graph_store
        )
        return await runtime.start_workflow(
            document,
            raw_messages,
            workflow_snapshot=workflow,
            request_id=str(kwargs.get("request_id", "")),
            public_model=str(kwargs.get("public_model", workflow["name"])),
            lifecycle_id=lifecycle_id,
        )

    monkeypatch.setattr(
        "agent_shell.runtime.request_snapshot.LifecycleRunCoordinator.start_workflow",
        direct_test_run,
    )

    async def direct_test_agent(coordinator, main_agent, raw_messages, **kwargs):
        """Execute the frozen Main Agent graph locally for API unit tests."""

        lifecycle_id = str(uuid4())
        coordinator._lifecycle_id = lifecycle_id
        runtime = coordinator._snapshot.new_runtime(store=graph_store)
        return await runtime.start_main_agent(
            str(main_agent["id"]),
            raw_messages,
            request_id=str(kwargs.get("request_id", "")),
            lifecycle_id=lifecycle_id,
            run_id=str(uuid4()),
            thread_id=str(uuid4()),
            assistant_id=str(uuid4()),
            public_model=str(kwargs.get("public_model", main_agent["name"])),
        )

    monkeypatch.setattr(
        "agent_shell.runtime.request_snapshot.LifecycleRunCoordinator.start_agent",
        direct_test_agent,
    )

    async def skip_external_retention(_self) -> None:
        return None

    monkeypatch.setattr(
        "agent_shell.runtime.request_snapshot.RequestSnapshotRuntime.enforce_lifecycle_retention",
        skip_external_retention,
    )
    return ScopedAuthTestClient(create_app())


def write_middleware_template(
    tmp_path: Path,
    template_key: str,
    source: str,
    *,
    requirements: tuple[str, ...] = (),
) -> None:
    package_dir = (
        tmp_path
        / "data"
        / "templates"
        / "agent"
        / "custom_middleware"
        / template_key
    )
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "main.py").write_text(source, encoding="utf-8")
    if requirements:
        (package_dir / "requirements.txt").write_text(
            "\n".join(requirements) + "\n",
            encoding="utf-8",
        )


def create_main_agent(
    client: TestClient,
    *,
    provider_settings: dict[str, object] | None = None,
    model_request_settings: dict[str, object] | None = None,
    filesystem_id: str | None = None,
    is_model_entry: bool = False,
) -> dict:
    model_payload = {
        "name": "Published model",
        "provider": "openai",
        "base_url": "https://provider.example/v1",
        "credential": "provider-test-secret",
        "model": "provider-model",
        "provider_settings": provider_settings or {},
        "tool_choice": None,
        "response_format": None,
        "model_settings": {},
        **(model_request_settings or {}),
    }
    connection_response = client.post(
        "/agent-shell/api/model-connections",
        json=model_payload,
    )
    assert connection_response.status_code == 200, connection_response.text
    connection = connection_response.json()
    requirement_response = client.post(
        "/agent-shell/api/blocks/model-requirement",
        json={
            "name": "Published model requirement",
            "description": "A model capable of the published workflow task.",
        },
    )
    assert requirement_response.status_code == 200, requirement_response.text
    requirement = requirement_response.json()
    binding_response = client.put(
        f"/agent-shell/api/model-requirements/{requirement['id']}/binding",
        json={"connection_id": connection["id"]},
    )
    assert binding_response.status_code == 200, binding_response.text
    output_response = client.post(
        "/agent-shell/api/blocks/agent-event-output",
        json=agent_event_output_payload(
            client,
            "Published output",
        ),
    )
    assert output_response.status_code == 200, output_response.text
    event_output = output_response.json()
    if filesystem_id is None:
        filesystem = client.post(
            "/agent-shell/api/blocks/filesystem",
            json={"name": "Published Agent filesystem"},
        )
        assert filesystem.status_code == 200, filesystem.text
        filesystem_id = filesystem.json()["id"]
    filesystem_tools = client.post(
        "/agent-shell/api/blocks/filesystem-tools",
        json={"name": "Published Agent filesystem tools"},
    )
    assert filesystem_tools.status_code == 200, filesystem_tools.text
    capability_refs = [{"type": "model-requirement", "block_id": requirement["id"]}]
    capability_refs.append(
        {"type": "agent-event-output", "block_id": event_output["id"]}
    )
    capability_refs.append(
        {"type": "filesystem", "block_id": filesystem_id}
    )
    capability_refs.append(
        {
            "type": "filesystem-tools",
            "block_id": filesystem_tools.json()["id"],
        }
    )
    response = client.post(
        "/agent-shell/api/main-agents",
        json={
            "name": "Published Main Agent",
            "is_model_entry": is_model_entry,
            "capability_refs": capability_refs,
            "subagents": [],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_workflow(
    client: TestClient,
    *,
    name: str | None = None,
    is_model_entry: bool = False,
) -> dict:
    workflow_name = name or "Test Workflow"
    response = client.post(
        "/agent-shell/api/workflows",
        json={
            "name": workflow_name,
            "description": "Test Workflow.",
            "is_model_entry": is_model_entry,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def save_linear_workflow_graph(
    client: TestClient,
    workflow: dict,
    main_agent: dict,
) -> dict:
    document = {
        "definition": {
            "schema_version": 1,
            "state_contract": "agent-shell.workflow.agent-invocations.v1",
            "nodes": [
                {"id": "start", "type": "start", "type_version": 1, "config": {}},
                {
                    "id": "agent",
                    "type": "agent",
                    "type_version": 1,
                    "config": {"main_agent_id": main_agent["id"]},
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
        "layout": {
            "nodes": {
                "start": {"x": 80, "y": 160},
                "agent": {"x": 360, "y": 160},
                "end": {"x": 640, "y": 160},
            },
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    }
    response = client.put(
        f"/agent-shell/api/workflows/{workflow['id']}/graph",
        json=document,
    )
    assert response.status_code == 200, response.text
    return response.json()


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
        },
    }


def _python_output_payload(
    client: TestClient,
    component_type: str,
    name: str,
    source: str,
) -> dict[str, object]:
    category = (
        ("agent", "agent_event_output")
        if component_type == "agent-event-output"
        else ("workflow", "workflow_event_output")
    )
    template_key = "test-output-" + str(abs(hash(source)))
    package_dir = Path.cwd().joinpath(
        "data",
        "templates",
        *category,
        template_key,
    )
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "main.py").write_text(source, encoding="utf-8")
    selected = next(
        item
        for item in client.get(
            f"/agent-shell/api/python-package-templates/{component_type}"
        ).json()["catalog"]
        if item["key"] == template_key
    )
    return {
        "name": name,
        "python_package": {"folder": ""},
        "python_package_template": {
            "key": selected["key"],
            "revision": selected["revision"],
        },
    }


def agent_event_output_payload(
    client: TestClient,
    name: str = "Visible timeline",
) -> dict[str, object]:
    return _python_output_payload(
        client,
        "agent-event-output",
        name,
        'def output(event, origin):\n'
        '    if event.get("method") != "messages":\n'
        '        return ""\n'
        '    data = event.get("params", {}).get("data", ())\n'
        '    if not isinstance(data, (list, tuple)) or len(data) != 2:\n'
        '        return ""\n'
        '    payload = data[0]\n'
        '    if not isinstance(payload, dict):\n'
        '        return str(getattr(payload, "text", "") or "")\n'
        '    if payload.get("event") == "content-block-delta":\n'
        '        delta = payload.get("delta", {})\n'
        '        return str(delta.get("text", "")) if isinstance(delta, dict) else ""\n'
        '    return ""\n',
    )


def workflow_event_output_payload(
    client: TestClient,
    name: str = "Visible workflow events",
    *,
    source: str = 'def output(event, origin):\n    return ""\n',
) -> dict[str, object]:
    return _python_output_payload(
        client,
        "workflow-event-output",
        name,
        source,
    )


def capability_reference_id(main_agent: dict, capability_type: str) -> str:
    return next(
        item["block_id"]
        for item in main_agent["capability_refs"]
        if item["type"] == capability_type
    )
