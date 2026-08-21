from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from agent_shell.app import create_app
from agent_shell.redaction import (
    LOCAL_PATH,
    REDACTED,
    UNAVAILABLE,
    RedactionPolicy,
    REDACTION_BOUNDARIES,
    redact_for_boundary,
)
from support import ScopedAuthTestClient, configure_scope_tokens


GOLDEN_PATH = Path(__file__).parents[1] / "fixtures" / "redaction_golden.json"


@pytest.fixture(autouse=True)
def clean_agent_shell_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.upper().startswith("AGENT_SHELL_"):
            monkeypatch.delenv(key, raising=False)


def configure_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    return create_app()


def test_nested_redaction_matches_golden_for_all_registered_sensitive_classes() -> None:
    payload = {
        "api_key": "provider-secret-sentinel",
        "authorization": "Bearer bearer-secret-sentinel",
        "url": "https://username:url-secret@provider.example/v1",
        "messages": [{"role": "user", "content": "message-secret-sentinel"}],
        "tool_args": {"path": "C:\\Users\\private\\file.txt", "value": "tool-secret"},
        "local_path": "C:\\Users\\private\\workspace",
        "nested": [
            {
                "provider_response": {"raw": "provider-response-sentinel"},
                "safe": "request used Bearer bearer-secret-sentinel",
            }
        ],
    }

    assert redact_for_boundary("http-error", payload) == json.loads(
        GOLDEN_PATH.read_text(encoding="utf-8")
    )


def test_redaction_handles_pydantic_dataclass_exception_cycles_and_unknown_objects() -> None:
    class SecretModel(BaseModel):
        api_key: str
        safe: str

    @dataclass
    class SecretDataclass:
        password: str
        model: SecretModel

    class DangerousUnknown:
        def __repr__(self) -> str:
            raise AssertionError("repr must not be called")

        def __str__(self) -> str:
            raise AssertionError("str must not be called")

    cause = ValueError("provider-response-sentinel C:\\Users\\private")
    error = RuntimeError("outer-secret")
    error.__cause__ = cause
    cyclic: list[object] = []
    cyclic.append(cyclic)

    result = redact_for_boundary(
        "http-error",
        {
            "model": SecretModel(api_key="model-secret", safe="ok"),
            "dataclass": SecretDataclass(
                password="password-secret",
                model=SecretModel(api_key="nested-secret", safe="ok"),
            ),
            "exception": error,
            "cycle": cyclic,
            "unknown": DangerousUnknown(),
        }
    )

    assert result["model"] == {"api_key": REDACTED, "safe": "ok"}
    assert result["dataclass"]["password"] == REDACTED
    assert result["exception"] == {
        "type": "exception",
        "message": "An internal operation failed.",
        "cause": {
            "type": "exception",
            "message": "An internal operation failed.",
            "cause": None,
        },
    }
    assert result["cycle"] == [UNAVAILABLE]
    assert result["unknown"] == UNAVAILABLE


def test_dynamic_secret_values_and_host_paths_are_removed_from_safe_strings() -> None:
    policy = RedactionPolicy(["opaque-provider-value"])
    result = policy.redact(
        {
            "safe": (
                "opaque-provider-value at /home/private/runtime/file.txt and "
                "sk-abcdefghijklmnop"
            ),
            "source_path": "/custom/private/source.py",
        }
    )

    assert result["safe"] == f"{REDACTED} at {LOCAL_PATH} and {REDACTED}"
    assert result["source_path"] == LOCAL_PATH


def test_every_public_boundary_uses_the_same_fail_closed_policy() -> None:
    payload = {
        "authorization": "Bearer boundary-token-sentinel",
        "messages": [{"content": "boundary-message-sentinel"}],
        "local_path": "C:\\Users\\private\\boundary.txt",
        "unknown": object(),
    }

    results = {
        boundary: redact_for_boundary(boundary, payload)
        for boundary in REDACTION_BOUNDARIES
    }

    assert len(results) == 4
    baseline = redact_for_boundary("http-error", payload)
    assert all(result == baseline for result in results.values())
    serialized = json.dumps(results)
    assert "boundary-token-sentinel" not in serialized
    assert "boundary-message-sentinel" not in serialized
    assert "Users" not in serialized
    with pytest.raises(ValueError, match="unsupported redaction boundary"):
        redact_for_boundary("ad-hoc-replacement", payload)


def test_http_and_unhandled_errors_reuse_safe_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = configure_app(monkeypatch, tmp_path)

    @app.get("/api/redacted-http-error")
    async def redacted_http_error() -> None:
        raise HTTPException(
            status_code=400,
            detail={
                "authorization": "Bearer http-secret-sentinel",
                "local_path": "C:\\Users\\private\\data.txt",
                "safe": "action failed",
            },
        )

    @app.get("/api/redacted-internal-error")
    async def redacted_internal_error() -> None:
        raise RuntimeError(
            "internal-secret-sentinel C:\\Users\\private\\trace.py"
        )

    with ScopedAuthTestClient(app, raise_server_exceptions=False) as client:
        public = client.get("/api/redacted-http-error")
        internal = client.get("/api/redacted-internal-error")

    assert public.status_code == 400
    assert public.json()["detail"] == {
        "code": "request_failed",
        "message": "The management request failed.",
        "message_key": "errors.requestFailed",
        "message_args": {},
    }
    assert "http-secret-sentinel" not in public.text
    assert internal.status_code == 500
    assert internal.json()["detail"]["code"] == "internal_error"
    assert internal.json()["detail"]["message_key"] == "errors.internalError"
    assert internal.json()["request_id"].startswith("req_")
    assert "internal-secret-sentinel" not in internal.text
    assert "Users" not in internal.text
