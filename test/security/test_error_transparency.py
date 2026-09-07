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


def test_request_validation_keeps_input_except_stored_secret_values(
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
    assert next(issue for issue in issues if issue["loc"][-1] == "count")[
        "input"
    ] == "not-a-number"
    assert next(issue for issue in issues if issue["loc"][-1] == "retries")[
        "input"
    ] == "[REDACTED]"


def test_openai_error_keeps_reason_and_redacts_stored_secret_value(
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

    assert started.status_code == 200
    assert response.status_code == 500
    message = response.json()["error"]["message"]
    assert r"RuntimeError: Provider failed at C:\Users\developer\provider.py" in message
    assert MANAGEMENT_TOKEN not in message
    assert "[REDACTED]" in message
