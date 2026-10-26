from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import ClassVar

from starlette.middleware.base import BaseHTTPMiddleware

from agent_shell.api import api_server
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.request_snapshot import (
    LifecycleRunCoordinator,
    RequestSnapshotRuntime,
)
from agent_shell.storage.file_config import FileConfigRepository

from .support import *


class _CompletionConnection:
    """Drive the real API route with explicit ASGI transport messages."""

    def __init__(self, payload: dict, *, spec_version: str = "2.3") -> None:
        self.incoming: asyncio.Queue[dict] = asyncio.Queue()
        body = json.dumps(payload).encode()
        self.incoming.put_nowait(
            {"type": "http.request", "body": body[:5], "more_body": True}
        )
        self.incoming.put_nowait(
            {"type": "http.request", "body": body[5:], "more_body": False}
        )
        self.sent: list[dict] = []
        self.chunk_sent = asyncio.Event()
        self.fail_send = False
        self.scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": spec_version},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/compat/openai/v1/chat/completions",
            "query_string": b"",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"authorization", f"Bearer {API_KEY}".encode()),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }

    async def send(self, message: dict) -> None:
        if self.fail_send:
            raise OSError("the response transport is closed")
        self.sent.append(message)
        if message["type"] == "http.response.body":
            self.chunk_sent.set()

    async def run(self, app) -> None:
        await app(self.scope, self.incoming.get, self.send)


@pytest.mark.parametrize(
    ("stream", "phase"),
    [(False, "result"), (True, "stream"), (True, "start"), (False, "capture")],
)
def test_client_disconnect_notifies_once_across_request_phases_and_keeps_execution_owned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stream: bool, phase: str
) -> None:
    async def dispatch(request, call_next):
        return await call_next(request)

    test_client = make_client(tmp_path, monkeypatch)
    test_client.app.add_middleware(BaseHTTPMiddleware, dispatch=dispatch)
    with test_client as client:
        main_agent = create_main_agent(client, is_model_entry=True)

        async def scenario() -> None:
            entered = asyncio.Event()
            startup_release = asyncio.Event()
            execution_release = asyncio.Event()
            consumed = asyncio.Event()
            notified = asyncio.Event()
            policy_release = asyncio.Event()
            notifications: list[str] = []
            original_capture = RequestSnapshotRuntime.capture

            class Execution:
                identity = None
                usage: dict[str, int] = {}
                finish_reason = "stop"

                async def run(self):
                    if phase == "result":
                        entered.set()
                    await execution_release.wait()
                    consumed.set()
                    return "background result", {}

                async def stream_text(self):
                    if phase == "stream":
                        entered.set()
                    await execution_release.wait()
                    yield "background output"
                    consumed.set()

            async def capture(runtime):
                if phase == "capture":
                    entered.set()
                    await startup_release.wait()
                return await original_capture(runtime)

            async def start(coordinator, _agent, payload, **_kwargs):
                assert payload["messages"] == [{"role": "user", "content": "hello"}]
                if phase == "start":
                    entered.set()
                    await startup_release.wait()
                return Execution()

            async def disconnect(_coordinator):
                notifications.append("disconnected")
                notified.set()
                await policy_release.wait()

            monkeypatch.setattr(RequestSnapshotRuntime, "capture", capture)
            monkeypatch.setattr(LifecycleRunCoordinator, "start_agent", start)
            monkeypatch.setattr(LifecycleRunCoordinator, "disconnect", disconnect)
            connection = _CompletionConnection(
                {
                    "model": main_agent["name"],
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": stream,
                }
            )
            request = asyncio.create_task(connection.run(client.app))
            await asyncio.wait_for(entered.wait(), timeout=2)
            if phase == "stream":
                await asyncio.wait_for(connection.chunk_sent.wait(), timeout=2)
            connection.incoming.put_nowait({"type": "http.disconnect"})
            # The HTTP request returns even while policy cleanup is blocked.
            await asyncio.wait_for(request, timeout=2)
            sent_before_resume = len(connection.sent)
            startup_release.set()
            await asyncio.wait_for(notified.wait(), timeout=2)
            assert not consumed.is_set()
            execution_release.set()
            await asyncio.wait_for(consumed.wait(), timeout=2)
            policy_release.set()
            assert notifications == ["disconnected"]
            assert len(connection.sent) == sent_before_resume

        assert client.portal is not None
        client.portal.call(scenario)


@pytest.mark.parametrize("ending", ["normal", "management", "task_cancel", "closed_send"])
def test_completion_transport_distinguishes_disconnect_from_other_endings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    async def dispatch(request, call_next):
        return await call_next(request)

    test_client = make_client(tmp_path, monkeypatch)
    if ending != "closed_send":
        test_client.app.add_middleware(BaseHTTPMiddleware, dispatch=dispatch)
    with test_client as client:
        main_agent = create_main_agent(client, is_model_entry=True)

        async def scenario() -> None:
            started = asyncio.Event()
            release = asyncio.Event()
            consumed = asyncio.Event()
            notified = asyncio.Event()
            coordinators: list[LifecycleRunCoordinator] = []
            notifications: list[str] = []

            class Execution:
                identity = None
                usage: dict[str, int] = {}
                finish_reason = "stop"

                async def stream_text(self):
                    started.set()
                    await release.wait()
                    yield "answer"
                    consumed.set()

            async def start(coordinator, *_args, **_kwargs):
                coordinator._begin_lifecycle("lifecycle-transport")
                coordinators.append(coordinator)
                return Execution()

            async def disconnect(_coordinator):
                notifications.append("disconnected")
                notified.set()

            monkeypatch.setattr(LifecycleRunCoordinator, "start_agent", start)
            monkeypatch.setattr(LifecycleRunCoordinator, "disconnect", disconnect)
            connection = _CompletionConnection(
                {
                    "model": main_agent["name"],
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
                spec_version="2.4" if ending == "closed_send" else "2.3",
            )
            request = asyncio.create_task(connection.run(client.app))
            await asyncio.wait_for(started.wait(), timeout=2)
            await asyncio.wait_for(connection.chunk_sent.wait(), timeout=2)
            if ending == "management":
                coordinators[0].terminate_response()
            elif ending == "task_cancel":
                request.cancel()
            elif ending == "closed_send":
                connection.fail_send = True
            if ending in {"normal", "closed_send"}:
                release.set()
            await asyncio.wait_for(
                asyncio.gather(request, return_exceptions=ending == "task_cancel"),
                timeout=2,
            )
            # Some servers expose http.disconnect after a normal final body.
            connection.incoming.put_nowait({"type": "http.disconnect"})
            release.set()
            await asyncio.wait_for(consumed.wait(), timeout=2)
            if ending == "closed_send":
                await asyncio.wait_for(notified.wait(), timeout=2)
                assert notifications == ["disconnected"]
            else:
                assert notifications == []
            output = b"".join(item.get("body", b"") for item in connection.sent)
            if ending == "normal":
                assert b"answer" in output and b"[DONE]" in output
            elif ending == "management":
                assert b"completion_cancelled" in output and b"[DONE]" in output

        assert client.portal is not None
        client.portal.call(scenario)


def test_published_main_agent_runs_without_filesystem_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(
            client,
            include_filesystem=False,
            is_model_entry=True,
        )
        response = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": main_agent["name"],
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        summary = client.post(
            "/agent-shell/api/blocks/summarization",
            json={"name": "Summary without filesystem"},
        ).json()
        summary_payload = main_agent_payload(main_agent)
        summary_payload["capability_refs"] = [
            *summary_payload["capability_refs"],
            {"type": "summarization", "block_id": summary["id"]},
        ]
        summary_agent = publish_main_agent(client, main_agent, summary_payload)
        summarized_response = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": summary_agent["name"],
                "messages": [{"role": "user", "content": "hello again"}],
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "runtime reply"
    assert summarized_response.status_code == 200, summarized_response.text


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


def test_configuration_failure_returns_concrete_error_and_records_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client, is_model_entry=True)

        async def fail_capture(_self):
            raise RuntimeError("snapshot exploded")

        monkeypatch.setattr(RequestSnapshotRuntime, "capture", fail_capture)
        response = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": main_agent["name"],
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            },
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        request_id = response.headers["x-request-id"]
        events = client.get(
            "/agent-shell/api/event-feed",
            params=event_feed_params(source="runtime", query=request_id),
        ).json()["items"]

    assert response.status_code == 500
    assert response.json()["error"] == {
        "message": "The request configuration could not be prepared.",
        "type": "server_error",
        "param": None,
        "code": "configuration_snapshot_failed",
        "request_id": request_id,
    }
    assert response.json()["request_id"] == request_id
    assert "snapshot exploded" not in response.text
    assert events[0]["summary"].endswith("RuntimeError: snapshot exploded")


def test_run_start_failure_returns_exception_chain_and_lifecycle_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client, is_model_entry=True)

        async def fail_start(coordinator, *_args, **_kwargs):
            coordinator._begin_lifecycle("lifecycle-start-failure")
            try:
                raise OSError("provider connection refused")
            except OSError as cause:
                raise RuntimeError("run creation exploded") from cause

        monkeypatch.setattr(LifecycleRunCoordinator, "start_agent", fail_start)
        response = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": main_agent["name"],
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            },
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

    request_id = response.headers["x-request-id"]
    assert response.status_code == 500
    assert response.json()["error"] == {
        "message": "The Run could not be started.",
        "type": "server_error",
        "param": None,
        "code": "run_start_failed",
        "request_id": request_id,
        "lifecycle_id": "lifecycle-start-failure",
    }
    assert response.json()["request_id"] == request_id
    assert response.json()["lifecycle_id"] == "lifecycle-start-failure"
    assert "run creation exploded" not in response.text


def test_execution_failure_returns_decoded_provider_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Execution:
        identity = SimpleNamespace(run_id="run-provider-failure")

        async def run(self):
            raise AgentRuntimeError(
                "provider_request_failed",
                "ProviderGatewayError: upstream returned 503 with an invalid payload",
                status_code=502,
                source_exception_type="ProviderGatewayError",
                diagnostic_id="1" * 32,
                decoded_from_server=True,
            )

    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client, is_model_entry=True)

        async def fail_execution(coordinator, *_args, **_kwargs):
            coordinator._begin_lifecycle("lifecycle-provider-failure")
            return Execution()

        monkeypatch.setattr(LifecycleRunCoordinator, "start_agent", fail_execution)
        response = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": main_agent["name"],
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            },
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

    request_id = response.headers["x-request-id"]
    assert response.status_code == 502
    assert response.json()["error"] == {
        "message": "The provider request failed.",
        "type": "server_error",
        "param": None,
        "code": "provider_request_failed",
        "request_id": request_id,
        "lifecycle_id": "lifecycle-provider-failure",
    }
    assert "ProviderGatewayError" not in response.text
    assert "upstream returned 503" not in response.text


def test_completion_stream_reports_cancelled_lifecycle_without_disconnect(
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
            self.release = asyncio.Event()

        async def stream_text(self):
            self.started.set()
            await self.release.wait()
            yield "late output"

    with make_client(tmp_path, monkeypatch) as client:
        portal = client.portal
        assert portal is not None

        async def scenario() -> tuple[str, str]:
            execution = Execution()
            terminated = asyncio.Event()
            stream = api_server._completion_stream(
                execution,
                "Workflow",
                detached_tasks=client.app.state.detached_tasks,
                response_terminated=terminated,
            )
            await anext(stream)
            pending = asyncio.create_task(anext(stream))
            await execution.started.wait()
            terminated.set()
            error_chunk = await asyncio.wait_for(pending, timeout=1)
            done = await anext(stream)
            execution.release.set()
            await asyncio.sleep(0)
            return error_chunk, done

        error_chunk, done = portal.call(scenario)

    assert '"finish_reason":"error"' in error_chunk
    assert '"code":"completion_cancelled"' in error_chunk
    assert done == "data: [DONE]\n\n"


def test_completion_result_reports_cancelled_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Execution:
        identity = None
        context = None

        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def run(self) -> tuple[str, dict[str, int]]:
            self.started.set()
            await self.release.wait()
            return "late", {}

    with make_client(tmp_path, monkeypatch) as client:
        portal = client.portal
        assert portal is not None

        async def scenario() -> str:
            execution = Execution()
            terminated = asyncio.Event()

            pending = asyncio.ensure_future(
                api_server._completion_result(
                    execution,
                    detached_tasks=client.app.state.detached_tasks,
                    response_terminated=terminated,
                )
            )
            await execution.started.wait()
            terminated.set()
            with pytest.raises(AgentRuntimeError) as failure:
                await asyncio.wait_for(pending, timeout=1)
            execution.release.set()
            return failure.value.code

        code = portal.call(scenario)

    assert code == "completion_cancelled"


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


def test_unknown_compat_path_belongs_to_the_compat_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        response = client.get("/compat/openai/v1/unknown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


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


def test_post_publish_command_package_failure_reaches_user_and_runtime_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_dir = (
        tmp_path
        / "data"
        / "templates"
        / "workflow"
        / "command"
        / "broken-after-publish"
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
        command = client.post(
            "/agent-shell/api/blocks/command",
            json={
                "name": "Broken after publish",
                "python_package": {"folder": ""},
                "python_package_template": {
                    "key": selected["key"],
                    "revision": selected["revision"],
                },
            },
        )
        assert command.status_code == 200, command.text
        workflow = create_workflow(
            client,
            name="Runtime package failure",
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
                            "id": "command",
                            "type": "command",
                            "type_version": 1,
                            "config": {"command_id": command.json()["id"]},
                        },
                        {"id": "end", "type": "end", "type_version": 1, "config": {}},
                    ],
                    "edges": [
                        {"id": "start-command", "source": "start", "source_handle": "next", "target": "command", "target_handle": "in"},
                        {"id": "command-end", "source": "command", "source_handle": "next", "target": "end", "target_handle": "in"},
                    ],
                },
                "layout": {"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
            },
        )
        assert graph.status_code == 200, graph.text

        folder = command.json()["python_package"]["folder"]
        main_path = (
            client.app.state.agent_runtime._configuration.python_packages_root
            / "command"
            / folder
            / "main.py"
        )
        main_path.write_text("def create_command(:\n", encoding="utf-8")

        snapshot = asyncio.run(client.app.state.agent_runtime.capture())
        assert snapshot.workflow_by_id(workflow["id"]) is not None
        response = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "run"}],
                "stream": True,
            },
        )
        request_id = response.headers["x-request-id"]
        diagnostics = client.get(
            "/agent-shell/api/event-feed",
            params=event_feed_params(source="runtime", query=request_id),
        ).json()["items"]
        detail = client.get(
            f"/agent-shell/api/event-feed/runtime/{diagnostics[0]['id']}/download"
        )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "python_package.invalid"
    assert response.json()["error"]["message"] == (
        "The request could not be executed with the current configuration."
    )
    assert "main.py" not in response.text
    assert response.json()["lifecycle_id"]
    assert len(diagnostics) == 1
    assert '"code": "python_package.invalid"' in diagnostics[0]["inline_content"]
    assert "main.py contains a syntax error on line 1" in diagnostics[0]["summary"]
    assert detail.status_code == 200
    assert "SyntaxError" in detail.content.decode("utf-8")


def test_completion_stream_returns_python_package_failure_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Execution:
        finish_reason = "error"
        usage: dict[str, int] = {}

        def __init__(self, request_id: str) -> None:
            self.identity = SimpleNamespace(
                run_id="run-package-failure",
                request_id=request_id,
                lifecycle_id="lifecycle-package-failure",
            )

        async def stream_text(self):
            try:
                raise ImportError("No module named 'workflow_dependency'")
            except ImportError as cause:
                raise AgentRuntimeError(
                    "python_package.load_failed",
                    "Python package 'broken-command' could not be loaded.",
                    status_code=422,
                ) from cause
            yield ""

    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client, is_model_entry=True)

        async def fail_execution(coordinator, *_args, **kwargs):
            coordinator._begin_lifecycle("lifecycle-package-failure")
            return Execution(str(kwargs.get("request_id", "")))

        monkeypatch.setattr(LifecycleRunCoordinator, "start_agent", fail_execution)
        with client.stream(
            "POST",
            "/compat/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={
                "model": main_agent["name"],
                "messages": [{"role": "user", "content": "run"}],
                "stream": True,
            },
        ) as response:
            lines = [line for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(line.removeprefix("data: ")) for line in lines[:-1]]
    error_chunk = chunks[-1]
    assert error_chunk["choices"][0]["finish_reason"] == "error"
    assert error_chunk["error"]["code"] == "python_package.load_failed"
    assert error_chunk["error"]["message"] == (
        "The request could not be executed with the current configuration."
    )
    assert "workflow_dependency" not in lines[-2]
    assert error_chunk["error"]["request_id"]
    assert error_chunk["error"]["lifecycle_id"] == "lifecycle-package-failure"


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
        "        content = item.value['request']['messages'][-1]['content']\n"
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
        updated_agent = publish_main_agent(client, updated.json())
        response = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": updated_agent["name"],
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
