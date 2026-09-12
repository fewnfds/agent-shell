from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from agent_shell.app import create_app
from agent_shell.storage.environment import EnvironmentSnapshot
from support import MANAGEMENT_TOKEN, ScopedAuthTestClient, configure_scope_tokens


class _DebugPayload(BaseModel):
    count: int
    retries: int


@pytest.fixture(autouse=True)
def clean_agent_shell_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.upper().startswith("AGENT_SHELL_"):
            monkeypatch.delenv(key, raising=False)


def test_environment_snapshot_redacts_only_stored_secret_values() -> None:
    snapshot = EnvironmentSnapshot.capture(
        {
            "FIRST_KEY": "stored-secret",
            "SECOND_KEY": "longer-stored-secret",
        }
    )
    payload = {
        "authorization": "Bearer ordinary-debug-value",
        "messages": [{"content": "complete user message"}],
        "provider_response": "provider rejected the request",
        "traceback": r"C:\Users\developer\agent.py:42",
        "secret_occurrences": [
            "longer-stored-secret",
            "prefix stored-secret suffix",
        ],
    }

    assert snapshot.redact_secrets(payload) == {
        "authorization": "Bearer ordinary-debug-value",
        "messages": [{"content": "complete user message"}],
        "provider_response": "provider rejected the request",
        "traceback": r"C:\Users\developer\agent.py:42",
        "secret_occurrences": ["[REDACTED]", "prefix [REDACTED] suffix"],
    }


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
            },
        )

    with ScopedAuthTestClient(app) as client:
        response = client.get("/agent-shell/api/debug-error")

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "provider_request_rejected",
        "authorization": "Bearer ordinary-debug-value",
        "messages": [{"content": "complete user message"}],
        "provider_response": "provider-private response body",
        "traceback": r"C:\Users\developer\agent.py:42",
        "stored_secret": "[REDACTED]",
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
    assert MANAGEMENT_TOKEN not in diagnostics[0]["summary"]
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
