from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from agent_shell.app import create_app
from support import MANAGEMENT_TOKEN, ScopedAuthTestClient, configure_scope_tokens


class _DebugPayload(BaseModel):
    count: int
    retries: int


@pytest.fixture(autouse=True)
def clean_agent_shell_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.upper().startswith("AGENT_SHELL_"):
            monkeypatch.delenv(key, raising=False)


def test_authenticated_http_error_keeps_structured_detail_and_debug_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    app = create_app()

    @app.get("/agent-shell/api/debug-error")
    async def debug_error() -> None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "provider_request_rejected",
                "authorization": "Bearer ordinary-debug-value",
                "messages": [{"content": "complete user message"}],
                "provider_response": "provider-private response body",
                "traceback": r"C:\Users\developer\agent.py:42",
                "stored_secret": MANAGEMENT_TOKEN,
                "222": {"run_id": "22222222-2222-4222-8222-222222222222", "duration_ms": 222.796},
            },
        )

    with ScopedAuthTestClient(app) as client:
        saved = client.post("/agent-shell/api/model-connections", json={
            "name": "Numeric credential", "provider": "openai", "credential": "222",
            "base_url": "https://provider.example/v1", "model": "fake",
            "provider_settings": {}, "model_settings": {},
            "tool_choice": None, "response_format": None,
        })
        assert saved.status_code == 200, saved.text
        response = client.get("/agent-shell/api/debug-error")

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "provider_request_rejected",
        "authorization": "Bearer ordinary-debug-value",
        "messages": [{"content": "complete user message"}],
        "provider_response": "provider-private response body",
        "traceback": r"C:\Users\developer\agent.py:42",
        "stored_secret": MANAGEMENT_TOKEN,
        "222": {"run_id": "22222222-2222-4222-8222-222222222222", "duration_ms": 222.796},
    }


def test_unhandled_error_keeps_exception_reason_and_host_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    app = create_app()

    @app.get("/agent-shell/api/unhandled-debug-error")
    async def unhandled_debug_error() -> None:
        raise RuntimeError(r"provider failed at C:\Users\developer\trace.py")

    with ScopedAuthTestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/agent-shell/api/unhandled-debug-error")

    assert response.status_code == 500
    assert response.json()["detail"]["message"] == (
        r"RuntimeError: provider failed at C:\Users\developer\trace.py"
    )


def test_anonymous_unhandled_error_hides_exception_chain_and_keeps_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    app = create_app(serve_frontend=False)

    @app.get("/admin/unhandled-anonymous-error")
    async def unhandled_anonymous_error() -> None:
        raise RuntimeError(
            rf"admin shell failed at C:\Users\developer\anonymous.py with {MANAGEMENT_TOKEN}"
        )

    with ScopedAuthTestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/admin/unhandled-anonymous-error")
        diagnostics = client.get(
            "/agent-shell/api/event-feed",
            params={
                "started_at": "2000-01-01T00:00:00+00:00",
                "ended_at": "2100-01-01T00:00:00+00:00",
                "source": "runtime",
                "query": "internal_error",
            },
        ).json()["items"]

    assert response.status_code == 500
    payload = response.json()
    assert payload["error"]["code"] == "internal_error"
    assert payload["error"]["message"] == (
        "The request failed due to an internal server error."
    )
    assert payload["request_id"]
    assert MANAGEMENT_TOKEN not in response.text
    assert "anonymous.py" not in response.text
    assert "RuntimeError" not in response.text

    assert len(diagnostics) == 1
    assert "RuntimeError: admin shell failed" in diagnostics[0]["summary"]
    assert "anonymous.py" in diagnostics[0]["summary"]
    assert MANAGEMENT_TOKEN in diagnostics[0]["summary"]


def test_wrapped_http_error_keeps_its_underlying_exception_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    app = create_app()

    @app.get("/agent-shell/api/wrapped-debug-error")
    async def wrapped_debug_error() -> None:
        try:
            raise ValueError("provider response body explains the failure")
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "provider_request_failed",
                    "message": "The provider request failed.",
                },
            ) from exc

    with ScopedAuthTestClient(app) as client:
        response = client.get("/agent-shell/api/wrapped-debug-error")

    assert response.status_code == 422
    assert response.json()["detail"]["message"] == (
        "The provider request failed.\n"
        "Cause: ValueError: provider response body explains the failure"
    )


def test_request_validation_omits_rejected_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    app = create_app()

    @app.post("/agent-shell/api/debug-validation")
    async def debug_validation(payload: _DebugPayload) -> None:
        del payload
        raise AssertionError("invalid input must not reach the endpoint")

    with ScopedAuthTestClient(app) as client:
        response = client.post(
            "/agent-shell/api/debug-validation",
            json={"count": "not-a-number", "retries": MANAGEMENT_TOKEN},
        )

    assert response.status_code == 422
    issues = response.json()["detail"]["issues"]
    assert {issue["loc"][-1] for issue in issues} == {"count", "retries"}
    assert all("input" not in issue for issue in issues)
    assert MANAGEMENT_TOKEN not in response.text
    assert next(issue for issue in issues if issue["loc"][-1] == "count")[
        "msg"
    ] == "Input should be a valid integer, unable to parse string as an integer"


def test_credential_validation_errors_omit_rejected_input(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    app = create_app()
    secret = "synthetic-rejected-credential"
    with ScopedAuthTestClient(app) as client:
        model = client.post("/agent-shell/api/model-connections", json={
            "name": "Invalid connection", "provider": "openai", "credential": [secret],
            "base_url": "https://provider.example/v1", "model": "fake",
            "provider_settings": {}, "model_settings": {}, "tool_choice": None,
            "response_format": None,
        })
        candidate = client.post("/agent-shell/api/fetch-models", json={
            "provider": "openai", "base_url": "https://provider.example/v1",
            "credential": [secret], "block_id": "",
        })
        mcp = client.post("/agent-shell/api/mcp-connections", json={
            "name": "Invalid MCP", "transport": "http", "url": "invalid",
            "headers": {"Authorization": {"source": "secret", "value": [secret]}},
        })
    for response in (model, candidate, mcp):
        assert response.status_code == 422, response.text
        assert secret not in response.text
        assert "input_value" not in response.text


def test_openai_error_returns_classification_and_keeps_details_in_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    app = create_app()

    async def fail_capture() -> None:
        raise RuntimeError(
            rf"Provider failed at C:\Users\developer\provider.py with {MANAGEMENT_TOKEN}"
        )

    with ScopedAuthTestClient(app) as client:
        started = client.post("/agent-shell/api/api-server/start")
        monkeypatch.setattr(client.app.state.agent_runtime, "capture", fail_capture)
        response = client.post(
            "/compat/openai/v1/chat/completions",
            json={"model": "debug-model", "messages": []},
        )
        diagnostics = client.get(
            "/agent-shell/api/event-feed",
            params={
                "started_at": "2000-01-01T00:00:00+00:00",
                "ended_at": "2100-01-01T00:00:00+00:00",
                "source": "runtime",
                "query": "configuration_snapshot_failed",
            },
        ).json()["items"]
        detail = client.get(
            f"/agent-shell/api/event-feed/runtime/{diagnostics[0]['id']}/download"
        )

    assert started.status_code == 200
    assert response.status_code == 500
    payload = response.json()
    assert payload["error"]["code"] == "configuration_snapshot_failed"
    assert payload["error"]["message"] == (
        "The request configuration could not be prepared."
    )
    assert MANAGEMENT_TOKEN not in response.text
    assert "provider.py" not in response.text
    assert payload["request_id"]

    assert len(diagnostics) == 1
    assert "RuntimeError: Provider failed" in diagnostics[0]["summary"]
    assert "provider.py" in diagnostics[0]["summary"]
    assert MANAGEMENT_TOKEN in diagnostics[0]["summary"]
    assert detail.status_code == 200
    assert r"C:\Users\developer\provider.py" in detail.content.decode("utf-8")


def test_openai_static_validation_messages_are_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    app = create_app()

    with ScopedAuthTestClient(app) as client:
        started = client.post("/agent-shell/api/api-server/start")
        missing_model = client.post(
            "/compat/openai/v1/chat/completions",
            json={"messages": []},
        )
        missing_body_model = client.post(
            "/compat/openai/v1/chat/completions",
            json={"model": "absent-model", "messages": []},
        )
        invalid_stream = client.post(
            "/compat/openai/v1/chat/completions",
            json={"model": "absent-model", "messages": [], "stream": "yes"},
        )

    assert started.status_code == 200
    assert missing_model.status_code == 422
    assert missing_model.json()["error"]["message"] == "A model is required."
    assert missing_body_model.status_code == 404
    assert missing_body_model.json()["error"]["message"] == (
        "The requested model does not exist."
    )
    assert invalid_stream.status_code == 422
    assert invalid_stream.json()["error"]["message"] == "stream must be a boolean."
