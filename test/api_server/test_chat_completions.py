from __future__ import annotations

import asyncio
import json
from typing import ClassVar

from agent_shell.api import api_server
from agent_shell.storage.file_config import FileConfigRepository

from .support import *


class InspectingFakeChatModel(ToolCompatibleFakeListChatModel):
    seen_messages: ClassVar[list[list[object]]] = []

    def _call(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen_messages.append(list(messages))
        return super()._call(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen_messages.append(list(messages))
        async for chunk in super()._astream(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        ):
            yield chunk


@pytest.mark.parametrize("on_disconnect", ("cancel", "continue"))
def test_completion_stream_applies_workflow_disconnect_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_disconnect: str,
) -> None:
    class Execution:
        identity = None
        context = None
        finish_reason = "stop"
        usage: dict[str, int] = {}

        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.cancelled = asyncio.Event()
            self.completed = asyncio.Event()

        async def stream_text(self):
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
            self.completed.set()
            yield "unobserved output"

    with make_client(tmp_path, monkeypatch) as client:
        portal = client.portal
        assert portal is not None

        async def scenario() -> tuple[bool, bool]:
            execution = Execution()
            lifecycle_cancelled = asyncio.Event()

            async def cancel_lifecycle() -> None:
                lifecycle_cancelled.set()

            stream = api_server._completion_stream(
                execution,
                "Workflow",
                detached_tasks=client.app.state.detached_tasks,
                on_disconnect=on_disconnect,
                cancel_lifecycle=cancel_lifecycle,
            )
            first = await anext(stream)
            assert '"role":"assistant"' in first
            pending = asyncio.create_task(anext(stream))
            await execution.started.wait()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            if on_disconnect == "cancel":
                await asyncio.wait_for(execution.cancelled.wait(), timeout=1)
                await asyncio.wait_for(lifecycle_cancelled.wait(), timeout=1)
            else:
                execution.release.set()
                await asyncio.wait_for(execution.completed.wait(), timeout=1)
            return execution.cancelled.is_set(), execution.completed.is_set()

        cancelled, completed = portal.call(scenario)

    assert cancelled is (on_disconnect == "cancel")
    assert completed is (on_disconnect == "continue")


def test_completion_stream_does_not_wait_for_graph_cancellation_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Execution:
        identity = None
        context = None
        finish_reason = "stop"
        usage: dict[str, int] = {}

        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cleanup_started = asyncio.Event()
            self.cleanup_release = asyncio.Event()
            self.cancel_started = asyncio.Event()
            self.cancel_release = asyncio.Event()
            self.cancel_recorded = asyncio.Event()

        async def cancel_lifecycle(self) -> None:
            self.cancel_started.set()
            await self.cancel_release.wait()
            self.cancel_recorded.set()

        async def stream_text(self):
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cleanup_started.set()
                await self.cleanup_release.wait()
                raise
            yield "unreachable"

    with make_client(tmp_path, monkeypatch) as client:
        portal = client.portal
        assert portal is not None

        async def scenario() -> tuple[bool, bool]:
            execution = Execution()
            stream = api_server._completion_stream(
                execution,
                "Workflow",
                detached_tasks=client.app.state.detached_tasks,
                on_disconnect="cancel",
                cancel_lifecycle=execution.cancel_lifecycle,
            )
            await anext(stream)
            pending = asyncio.create_task(anext(stream))
            await execution.started.wait()
            pending.cancel()
            await execution.cleanup_started.wait()
            await execution.cancel_started.wait()
            for _ in range(3):
                await asyncio.sleep(0)
            response_closed = pending.done()
            execution.cancel_release.set()
            execution.cleanup_release.set()
            await asyncio.wait_for(execution.cancel_recorded.wait(), timeout=1)
            await asyncio.gather(pending, return_exceptions=True)
            return response_closed, execution.cancel_recorded.is_set()

        response_closed, cancellation_recorded = portal.call(scenario)

    assert response_closed is True
    assert cancellation_recorded is True

def test_models_and_chat_require_published_model_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client, is_model_entry=True)
        workflow = create_workflow(
            client,
            name="Published Workflow",
            is_model_entry=True,
        )
        save_linear_workflow_graph(client, workflow, main_agent)
        another = create_workflow(client, name="Another Workflow")
        save_linear_workflow_graph(client, another, main_agent)
        disabled = create_workflow(
            client,
            name="Disabled Workflow",
            is_model_entry=True,
        )

        models = client.get("/compat/openai/v1/models")
        workflow_reply = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )
        another_reply = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": another["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )
        disabled_reply = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": disabled["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )
        main_agent_name_reply = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": main_agent["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )
        main_agent_id_reply = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": main_agent["id"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )

    assert models.status_code == 200
    assert [item["id"] for item in models.json()["data"]] == [
        workflow["name"],
        main_agent["name"],
    ]
    assert workflow_reply.status_code == 200, workflow_reply.text
    message = workflow_reply.json()["choices"][0]["message"]
    assert message["role"] == "assistant"
    assert message["content"] == ""
    assert main_agent_name_reply.status_code == 200, main_agent_name_reply.text
    assert main_agent_name_reply.json()["choices"][0]["message"]["content"] == (
        "runtime reply"
    )
    for response in (another_reply, disabled_reply, main_agent_id_reply):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "model_not_found"


def test_system_graph_limits_reach_the_graph_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_shell.runtime.agent_runtime import AgentRuntime

    captured: dict[str, object] = {}
    original_execution = AgentRuntime._workflow_execution

    def observe_execution(self, *args, **kwargs):
        captured["run_config"] = kwargs.get("run_config")
        captured["context"] = kwargs.get("context")
        captured["identity"] = kwargs.get("identity")
        execution = original_execution(self, *args, **kwargs)
        return execution

    monkeypatch.setattr(AgentRuntime, "_workflow_execution", observe_execution)
    repository = FileConfigRepository(tmp_path / "data")
    repository.update_system(
        lambda system: system["settings"].update(
            {"recursion_limit": 321, "max_concurrency": 7}
        )
    )
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        workflow = create_workflow(
            client,
            name="Configured limits",
            is_model_entry=True,
        )
        save_linear_workflow_graph(client, workflow, main_agent)
        reply = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )
        assert reply.status_code == 200, reply.text
    assert captured["run_config"]["recursion_limit"] == 321
    assert captured["run_config"]["max_concurrency"] == 7
    assert "run_id" not in captured["run_config"]
    assert "configurable" not in captured["run_config"]


def test_incomplete_saved_workflow_draft_is_not_a_public_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        workflow = create_workflow(
            client,
            name="Incomplete Workflow",
            is_model_entry=True,
        )
        saved = client.put(
            f"/agent-shell/api/workflows/{workflow['id']}/draft",
            json={
                "definition": {
                    "schema_version": 1,
                    "state_contract": "agent-shell.workflow.control.v1",
                    "nodes": [
                        {"id": "start", "type": "start", "type_version": 1, "config": {}},
                        {"id": "end", "type": "end", "type_version": 1, "config": {}},
                    ],
                    "edges": [],
                },
                "layout": {"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
            },
        )
        response = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )

    assert saved.status_code == 200, saved.text
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_found"


def test_chat_materializes_command_package_before_compiling_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_dir = (
        tmp_path
        / "data"
        / "templates"
        / "workflow"
        / "command"
        / "always-run"
    )
    package_dir.mkdir(parents=True)
    (package_dir / "main.py").write_text(
        "from langgraph.types import Command\n"
        "def create_command():\n"
        "    async def route(state, runtime):\n"
        "        return Command(goto='end')\n"
        "    return route\n",
        encoding="utf-8",
    )
    with make_client(tmp_path, monkeypatch) as client:
        selected = client.get(
            "/agent-shell/api/python-package-templates/command"
        ).json()["catalog"][0]
        router = client.post(
            "/agent-shell/api/blocks/command",
            json={
                "name": "Always run",
                "python_package": {"folder": ""},
                "python_package_template": {
                    "key": selected["key"],
                    "revision": selected["revision"],
                },
            },
        )
        assert router.status_code == 200, router.text
        workflow = create_workflow(
            client,
            name="Routed Workflow",
            is_model_entry=True,
        )
        graph = client.put(
            f"/agent-shell/api/workflows/{workflow['id']}/graph",
            json={
                "definition": {
                    "schema_version": 1,
                    "state_contract": "agent-shell.workflow.control.v1",
                    "nodes": [
                        {"id": "start", "type": "start", "type_version": 1, "config": {}},
                        {
                            "id": "router",
                            "type": "command",
                            "type_version": 1,
                            "config": {"command_id": router.json()["id"]},
                        },
                        {"id": "end", "type": "end", "type_version": 1, "config": {}},
                    ],
                    "edges": [
                        {"id": "start-router", "source": "start", "source_handle": "next", "target": "router", "target_handle": "in"},
                        {"id": "finish", "source": "router", "source_handle": "next", "target": "end", "target_handle": "in"},
                    ],
                },
                "layout": {"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
            },
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
    assert response.json()["choices"][0]["message"]["content"] == ""


def test_chat_completion_stream_runs_current_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        workflow = create_workflow(
            client,
            name="Streaming Workflow",
            is_model_entry=True,
        )
        save_linear_workflow_graph(client, workflow, main_agent)
        with client.stream(
            "POST",
            "/compat/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "run"}],
                "stream": True,
            },
        ) as response:
            lines = [line for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(line.removeprefix("data: ")) for line in lines[:-1]]
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    content = "".join(
        chunk["choices"][0]["delta"].get("content", "") for chunk in chunks
    )
    assert content == ""
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_message_interception_captures_raw_request_before_workflow_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_request = (
        '{"model":"not-a-workflow","messages":['
        '{"role":"user","content":"preserve  spacing"}],"stream":false}'
    )
    with make_client(tmp_path, monkeypatch) as client:
        monkeypatch.setattr(
            client.app.state.agent_runtime,
            "capture",
            lambda: pytest.fail("Workflow configuration must not be captured"),
        )
        enabled = client.put(
            "/agent-shell/api/message-interception",
            json={"enabled": True},
        )
        response = client.post(
            "/compat/openai/v1/chat/completions",
            content=raw_request,
            headers={"Content-Type": "application/json"},
        )
        snapshot = client.get("/agent-shell/api/message-interception")

    with ScopedAuthTestClient(create_app()) as restarted:
        after_restart = restarted.get("/agent-shell/api/message-interception")

    assert enabled.status_code == 200
    assert enabled.json() == {"enabled": True, "latest": None}
    assert response.status_code == 200
    assert response.json()["choices"][0] == {
        "index": 0,
        "message": {"role": "assistant", "content": "消息已拦截"},
        "finish_reason": "stop",
    }
    assert response.json()["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    latest = snapshot.json()["latest"]
    assert snapshot.json()["enabled"] is True
    assert latest["sequence"] == 1
    assert latest["request_id"]
    assert latest["request_raw_json"] == raw_request
    assert after_restart.json() == {"enabled": True, "latest": None}


def test_message_interception_returns_openai_stream_without_running_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        monkeypatch.setattr(
            client.app.state.agent_runtime,
            "capture",
            lambda: pytest.fail("Workflow configuration must not be captured"),
        )
        client.put("/agent-shell/api/message-interception", json={"enabled": True})
        with client.stream(
            "POST",
            "/compat/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={
                "model": "not-a-workflow",
                "messages": [{"role": "user", "content": "capture"}],
                "stream": True,
            },
        ) as response:
            lines = [line for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(line.removeprefix("data: ")) for line in lines[:-1]]
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert chunks[1]["choices"][0]["delta"] == {"content": "消息已拦截"}
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert chunks[-1]["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def test_root_agent_middleware_injects_frozen_client_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    InspectingFakeChatModel.seen_messages = []
    model = InspectingFakeChatModel(responses=["middleware reply"])
    write_middleware_template(
        tmp_path,
        "request-injection",
            "from langchain.agents.middleware import AgentMiddleware\n"
            "from langchain_core.messages import HumanMessage\n"
            "from langgraph.types import Overwrite\n"
            "from agent_shell.runtime.lifecycle_store import LIFECYCLE_INPUT_KEY, lifecycle_input_namespace\n"
        "class InjectRequest(AgentMiddleware):\n"
        "    async def abefore_agent(self, state, runtime):\n"
        "        item = await runtime.store.aget(lifecycle_input_namespace(runtime.context.lifecycle_id), LIFECYCLE_INPUT_KEY)\n"
        "        content = item.value['messages'][-1]['content']\n"
            "        return {'messages': Overwrite([HumanMessage(content=content)])}\n"
        "def create_middleware(agent):\n"
        "    return InjectRequest()\n",
    )

    with make_client(tmp_path, monkeypatch) as client:
        monkeypatch.setattr(
            "agent_shell.runtime.agent_builder._build_chat_model",
            lambda _block, _credential, _http_clients: model,
        )
        main_agent = create_main_agent(client, is_model_entry=True)
        selected = client.get(
            "/agent-shell/api/python-package-templates/middleware"
        ).json()["catalog"][0]
        custom = client.post(
            "/agent-shell/api/blocks/custom-middleware",
            json={
                "name": "Request message injection",
                "python_package": {"folder": ""},
                "python_package_template": {
                    "key": selected["key"],
                    "revision": selected["revision"],
                },
            },
        )
        assert custom.status_code == 200, custom.text
        updated = client.put(
            f"/agent-shell/api/main-agents/{main_agent['id']}",
            json={
                "name": main_agent["name"],
                "is_model_entry": True,
                "capability_refs": main_agent["capability_refs"],
                "middleware_refs": [{"middleware_id": custom.json()["id"]}],
                "subagents": [],
            },
        )
        assert updated.status_code == 200, updated.text
        response = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": updated.json()["name"],
                "messages": [{"role": "user", "content": "frozen client input"}],
            },
        )

    assert response.status_code == 200, response.text
    assert "middleware reply" in response.json()["choices"][0]["message"]["content"]
    assert [
        message.content
        for message in InspectingFakeChatModel.seen_messages[0]
        if message.type != "system"
    ] == ["frozen client input"]
