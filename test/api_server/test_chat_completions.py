from __future__ import annotations

import asyncio
import json
from typing import ClassVar

from agent_shell.api import api_server

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


@pytest.mark.parametrize("cancel_on_disconnect", (True, False))
def test_completion_stream_applies_workflow_disconnect_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel_on_disconnect: bool,
) -> None:
    class Execution:
        context = None
        finish_reason = "stop"
        usage: dict[str, int] = {}

        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.cancelled = asyncio.Event()
            self.cancel_recorded = asyncio.Event()
            self.completed = asyncio.Event()

        async def cancel(self) -> None:
            self.cancel_recorded.set()

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
            stream = api_server._completion_stream(
                execution,
                "Workflow",
                background_tasks=client.app.state.background_tasks,
                cancel_on_disconnect=cancel_on_disconnect,
            )
            first = await anext(stream)
            assert '"role":"assistant"' in first
            pending = asyncio.create_task(anext(stream))
            await execution.started.wait()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            if cancel_on_disconnect:
                await asyncio.wait_for(execution.cancelled.wait(), timeout=1)
                await asyncio.wait_for(execution.cancel_recorded.wait(), timeout=1)
            else:
                execution.release.set()
                await asyncio.wait_for(execution.completed.wait(), timeout=1)
            return execution.cancelled.is_set(), execution.completed.is_set()

        cancelled, completed = portal.call(scenario)

    assert cancelled is cancel_on_disconnect
    assert completed is (not cancel_on_disconnect)


def test_completion_stream_does_not_wait_for_graph_cancellation_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Execution:
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

        async def cancel(self) -> None:
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
                background_tasks=client.app.state.background_tasks,
                cancel_on_disconnect=True,
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

def test_models_publish_only_enabled_workflows_and_chat_runs_current_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        workflow = create_workflow(client, name="Published Workflow")
        save_linear_workflow_graph(client, workflow, main_agent)
        child = create_workflow(
            client,
            name="Internal Child Workflow",
            workflow_role="child",
        )
        save_linear_workflow_graph(client, child, main_agent)
        create_workflow(client, name="Disabled Workflow")

        models = client.get("/v1/models")
        workflow_reply = client.post(
            "/v1/chat/completions",
            json={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )
        child_reply = client.post(
            "/v1/chat/completions",
            json={
                "model": child["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )
        main_agent_name_reply = client.post(
            "/v1/chat/completions",
            json={
                "model": main_agent["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )
        main_agent_id_reply = client.post(
            "/v1/chat/completions",
            json={
                "model": main_agent["id"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )

    assert models.status_code == 200
    assert [item["id"] for item in models.json()["data"]] == [workflow["name"]]
    assert workflow_reply.status_code == 200, workflow_reply.text
    message = workflow_reply.json()["choices"][0]["message"]
    assert message["role"] == "assistant"
    assert message["content"] == "runtime reply"
    for response in (child_reply, main_agent_name_reply, main_agent_id_reply):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "model_not_found"


def test_workflow_runtime_limits_reach_the_graph_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_shell.runtime.agent_runtime import AgentRuntime

    captured: dict[str, object] = {}
    original_execution = AgentRuntime._execution

    def observe_execution(self, *args, **kwargs):
        captured["run_config"] = kwargs.get("run_config")
        captured["durability"] = kwargs.get("durability")
        captured["context"] = kwargs.get("context")
        captured["execution_timeout_seconds"] = kwargs.get(
            "execution_timeout_seconds"
        )
        return original_execution(self, *args, **kwargs)

    monkeypatch.setattr(AgentRuntime, "_execution", observe_execution)
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        workflow = create_workflow(client, name="Configured limits")
        save_linear_workflow_graph(client, workflow, main_agent)
        updated = client.put(
            f"/api/workflows/{workflow['id']}",
            json={
                "name": workflow["name"],
                "workflow_role": workflow["workflow_role"],
                "description": workflow["description"],
                "workflow_event_output_id": workflow[
                    "workflow_event_output_id"
                ],
                "recursion_limit": 321,
                "execution_timeout_seconds": 42,
                "max_concurrency": 7,
            },
        )
        assert updated.status_code == 200, updated.text
        reply = client.post(
            "/v1/chat/completions",
            json={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )
        assert reply.status_code == 200, reply.text
        assert client.app.state.workflow_checkpoints.started is False
        assert (
            tmp_path / "data" / "state" / "workflow-checkpoints.sqlite3"
        ).exists() is False

    assert captured["execution_timeout_seconds"] == 42
    assert captured["run_config"]["recursion_limit"] == 321
    assert captured["run_config"]["max_concurrency"] == 7
    assert "configurable" not in captured["run_config"]
    assert captured["durability"] is None
    assert captured["context"].checkpoint_thread_id is None


def test_workflow_checkpointer_durability_is_passed_mechanically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_shell.runtime.agent_runtime import AgentRuntime

    captured: list[dict[str, object]] = []
    original_execution = AgentRuntime._execution

    def observe_execution(self, *args, **kwargs):
        captured.append(
            {
                "run_config": kwargs.get("run_config"),
                "durability": kwargs.get("durability"),
                "context": kwargs.get("context"),
            }
        )
        return original_execution(self, *args, **kwargs)

    monkeypatch.setattr(AgentRuntime, "_execution", observe_execution)
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        for durability in ("exit", "async", "sync"):
            checkpointer = client.post(
                "/api/blocks/checkpointer",
                json={
                    "name": f"{durability} checkpoints",
                    "durability": durability,
                },
            )
            assert checkpointer.status_code == 200, checkpointer.text
            workflow = create_workflow(
                client,
                name=f"{durability} Checkpoint Workflow",
            )
            configured = client.put(
                f"/api/workflows/{workflow['id']}",
                json={
                    **{
                        key: workflow[key]
                        for key in (
                            "name",
                            "workflow_role",
                            "description",
                            "workflow_event_output_id",
                            "recursion_limit",
                            "execution_timeout_seconds",
                            "max_concurrency",
                        )
                    },
                    "checkpointer_id": checkpointer.json()["id"],
                },
            )
            assert configured.status_code == 200, configured.text
            save_linear_workflow_graph(client, configured.json(), main_agent)
            reply = client.post(
                "/v1/chat/completions",
                json={
                    "model": workflow["name"],
                    "messages": [{"role": "user", "content": "run"}],
                },
            )
            assert reply.status_code == 200, reply.text

            observed = captured[-1]
            context = observed["context"]
            assert observed["durability"] == durability
            assert context.checkpoint_thread_id
            assert observed["run_config"]["configurable"] == {
                "thread_id": context.checkpoint_thread_id,
            }
            run = client.app.state.workflow_lifecycle.history.get_run(
                context.run_id
            )
            assert run is not None
            assert run["checkpoint_thread_id"] == context.checkpoint_thread_id
            portal = client.portal
            assert portal is not None
            assert portal.call(
                client.app.state.workflow_checkpoints.checkpoint_count,
                context.checkpoint_thread_id,
            ) > 0

        assert client.app.state.workflow_checkpoints.started is True


def test_checkpointer_initialization_failure_isolated_to_configured_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        checkpointer = client.post(
            "/api/blocks/checkpointer",
            json={"name": "Unavailable checkpoints"},
        )
        assert checkpointer.status_code == 200, checkpointer.text
        configured = create_workflow(client, name="Checkpoint failure")
        configured_response = client.put(
            f"/api/workflows/{configured['id']}",
            json={
                **{
                    key: configured[key]
                    for key in (
                        "name",
                        "workflow_role",
                        "description",
                        "workflow_event_output_id",
                        "recursion_limit",
                        "execution_timeout_seconds",
                        "max_concurrency",
                    )
                },
                "checkpointer_id": checkpointer.json()["id"],
            },
        )
        assert configured_response.status_code == 200, configured_response.text
        save_linear_workflow_graph(client, configured_response.json(), main_agent)

        plain = create_workflow(client, name="No checkpoint dependency")
        save_linear_workflow_graph(client, plain, main_agent)

        async def fail_initialization():
            raise OSError("checkpoint database unavailable")

        monkeypatch.setattr(
            client.app.state.workflow_checkpoints,
            "require_checkpointer",
            fail_initialization,
        )
        failed = client.post(
            "/v1/chat/completions",
            json={
                "model": configured["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )
        succeeded = client.post(
            "/v1/chat/completions",
            json={
                "model": plain["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )

    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "workflow_checkpointer_unavailable"
    assert succeeded.status_code == 200, succeeded.text
    assert succeeded.json()["choices"][0]["message"]["content"] == "runtime reply"


def test_incomplete_saved_workflow_draft_is_not_a_public_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        workflow = create_workflow(client, name="Incomplete Workflow")
        saved = client.put(
            f"/api/workflows/{workflow['id']}/draft",
            json={
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
                    "edges": [],
                },
                "layout": {"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
            },
        )
        response = client.post(
            "/v1/chat/completions",
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
        "def create_command():\n"
        "    async def route(state, runtime):\n"
        "        return {'activate': ['run'], 'update': {}}\n"
        "    return route\n",
        encoding="utf-8",
    )
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        selected = client.get(
            "/api/python-package-templates/command"
        ).json()["catalog"][0]
        router = client.post(
            "/api/blocks/command",
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
        workflow = create_workflow(client, name="Routed Workflow")
        graph = client.put(
            f"/api/workflows/{workflow['id']}/graph",
            json={
                "definition": {
                    "schema_version": 1,
                    "state_contract": "agent-shell.workflow.agent-invocations.v1",
                    "nodes": [
                        {"id": "start", "type": "start", "type_version": 1, "config": {}},
                        {
                            "id": "router",
                            "type": "command",
                            "type_version": 1,
                            "config": {"command_id": router.json()["id"]},
                        },
                        {
                            "id": "agent",
                            "type": "agent",
                            "type_version": 1,
                            "config": {"main_agent_id": main_agent["id"]},
                        },
                        {"id": "end", "type": "end", "type_version": 1, "config": {}},
                    ],
                    "edges": [
                        {"id": "start-router", "source": "start", "source_handle": "next", "target": "router", "target_handle": "in"},
                        {"id": "run", "source": "router", "source_handle": "branch", "target": "agent", "target_handle": "in", "branch_key": "run"},
                        {"id": "finish", "source": "router", "source_handle": "branch", "target": "end", "target_handle": "in", "branch_key": "finish"},
                        {"id": "agent-end", "source": "agent", "source_handle": "next", "target": "end", "target_handle": "in"},
                    ],
                },
                "layout": {"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
            },
        )
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )

    assert graph.status_code == 200, graph.text
    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "runtime reply"


def test_chat_completion_stream_runs_current_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        workflow = create_workflow(client, name="Streaming Workflow")
        save_linear_workflow_graph(client, workflow, main_agent)
        with client.stream(
            "POST",
            "/v1/chat/completions",
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
    assert content == "runtime reply"
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
            "/api/message-interception",
            json={"enabled": True},
        )
        response = client.post(
            "/v1/chat/completions",
            content=raw_request,
            headers={"Content-Type": "application/json"},
        )
        snapshot = client.get("/api/message-interception")

    with ScopedAuthTestClient(create_app()) as restarted:
        after_restart = restarted.get("/api/message-interception")

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
        client.put("/api/message-interception", json={"enabled": True})
        with client.stream(
            "POST",
            "/v1/chat/completions",
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


def test_workflow_agent_middleware_injects_frozen_client_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    InspectingFakeChatModel.seen_messages = []
    model = InspectingFakeChatModel(responses=["middleware reply"])
    write_middleware_template(
        tmp_path,
        "request-injection",
        "from langchain.agents.middleware import AgentMiddleware\n"
        "from langchain_core.messages import HumanMessage\n"
        "from agent_shell.runtime.workflow_lifecycle import LIFECYCLE_INPUT_KEY, lifecycle_input_namespace\n"
        "class InjectRequest(AgentMiddleware):\n"
        "    async def abefore_agent(self, state, runtime):\n"
        "        item = await runtime.store.aget(lifecycle_input_namespace(runtime.context.lifecycle_id), LIFECYCLE_INPUT_KEY)\n"
        "        content = item.value['messages'][-1]['content']\n"
        "        return {'messages': [HumanMessage(content=content)]}\n"
        "def create_middleware(agent):\n"
        "    return InjectRequest()\n",
    )

    with make_client(tmp_path, monkeypatch) as client:
        monkeypatch.setattr(
            "agent_shell.runtime.agent_builder._build_chat_model",
            lambda _block, _credential, _http_clients: model,
        )
        main_agent = create_main_agent(client)
        selected = client.get(
            "/api/python-package-templates/middleware"
        ).json()["catalog"][0]
        custom = client.post(
            "/api/blocks/custom-middleware",
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
            f"/api/main-agents/{main_agent['id']}",
            json={
                "name": main_agent["name"],
                "capability_refs": main_agent["capability_refs"],
                "middleware_refs": [{"middleware_id": custom.json()["id"]}],
                "subagents": [],
            },
        )
        assert updated.status_code == 200, updated.text
        workflow = create_workflow(client, name="Middleware Workflow")
        save_linear_workflow_graph(client, workflow, updated.json())
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": workflow["name"],
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


def test_chat_completion_body_limit_runs_before_workflow_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        workflow = create_workflow(client)
        current = client.get("/api/system/runtime-policy").json()
        update = {
            key: value
            for key, value in current.items()
            if key not in {"defaults", "minimums", "configurable"}
        }
        update["chat_completion_body_bytes"] = 128
        saved = client.put("/api/system/runtime-policy", json=update)
        assert saved.status_code == 200, saved.text
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "x" * 256}],
            },
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "input_body_too_large"


def test_bounded_body_reader_stops_when_the_next_chunk_exceeds_the_limit() -> None:
    calls = 0

    async def receive() -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "type": "http.request",
                "body": b"a" * 80,
                "more_body": True,
            }
        if calls == 2:
            return {
                "type": "http.request",
                "body": b"b" * 80,
                "more_body": True,
            }
        raise AssertionError("the oversized request body was read past the limit")

    async def run() -> None:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/v1/chat/completions",
                "headers": [],
            },
            receive,
        )
        with pytest.raises(api_server._BodyTooLarge):
            await api_server._read_bounded_body(request, 128)

    asyncio.run(run())
    assert calls == 2
