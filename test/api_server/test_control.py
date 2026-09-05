from __future__ import annotations

from threading import Thread

from .support import *


def test_api_server_events_publish_from_worker_thread() -> None:
    hub = ApiServerEventHub()

    async def receive() -> str:
        stream = hub.stream()
        pending: asyncio.Task[str] | None = None
        try:
            assert await anext(stream) == ": connected\n\n"
            pending = asyncio.create_task(anext(stream))
            await asyncio.sleep(0)
            errors: list[BaseException] = []

            def publish() -> None:
                try:
                    hub.publish_nowait({"type": "runtime_diagnostic"})
                except BaseException as exc:
                    errors.append(exc)

            worker = Thread(target=publish)
            worker.start()
            worker.join()
            assert errors == []
            return await asyncio.wait_for(pending, timeout=1)
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await stream.aclose()

    received = asyncio.run(receive(), debug=True)

    assert received == 'data: {"type":"runtime_diagnostic"}\n\n'

def test_api_key_is_write_only_and_takes_effect_immediately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "page-inference-key"
    with make_client(tmp_path, monkeypatch) as client:
        initial = client.get("/compat/openai/v1/models")
        saved = client.put(
            "/agent-shell/api/api-server",
            json={"api_key": {"operation": "replace", "value": secret}},
        )
        missing = client.get("/compat/openai/v1/models", headers={"Authorization": ""})
        wrong = client.get(
            "/compat/openai/v1/models", headers={"Authorization": "Bearer wrong-key"}
        )
        allowed = client.get(
            "/compat/openai/v1/models", headers={"Authorization": f"Bearer {secret}"}
        )
        status = client.get("/agent-shell/api/api-server")

    with ScopedAuthTestClient(create_app()) as restarted:
        persisted = restarted.get(
            "/compat/openai/v1/models", headers={"Authorization": f"Bearer {secret}"}
        )

    assert initial.status_code == 200
    assert saved.status_code == 200
    assert saved.json()["api_key"] == {"configured": True}
    assert secret not in saved.text
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 200
    assert persisted.status_code == 200
    assert status.json()["message_interception_enabled"] is False
    assert secret not in status.text


def test_start_stop_and_known_workflow_runs_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        workflow = create_workflow(
            client,
            name="Runnable later",
            is_model_entry=True,
        )
        save_linear_workflow_graph(client, workflow, main_agent)
        stopped = client.post("/agent-shell/api/api-server/stop")
        unavailable = client.get("/compat/openai/v1/models")
        started = client.post("/agent-shell/api/api-server/start")
        models = client.get("/compat/openai/v1/models")
        completion = client.post(
            "/compat/openai/v1/chat/completions",
            json={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "stream"}],
                "stream": False,
            },
        )

    assert stopped.json()["enabled"] is False
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "api_server_stopped"
    assert started.json()["enabled"] is True
    assert [item["id"] for item in models.json()["data"]] == [workflow["name"]]
    assert completion.status_code == 200
    assert completion.json()["choices"][0]["message"]["content"] == "runtime reply"
