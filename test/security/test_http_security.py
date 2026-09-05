from __future__ import annotations

from fastapi import Request
from fastapi.testclient import TestClient
import pytest

from agent_shell.app import create_app
from agent_shell.security import SecurityFailure, _parse_bearer

from .http_security_support import *



def test_local_management_password_blocks_cross_site_state_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        before = client.get(
            "/agent-shell/api/api-server", headers=_bearer(MANAGEMENT_TOKEN)
        ).json()["enabled"]
        target = "/agent-shell/api/api-server/stop" if before else "/agent-shell/api/api-server/start"
        attack = client.post(
            target,
            headers={
                "Origin": "https://evil.example",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            content=b"x",
        )
        after = client.get(
            "/agent-shell/api/api-server", headers=_bearer(MANAGEMENT_TOKEN)
        ).json()["enabled"]

    assert attack.status_code == 401
    assert before == after

def test_api_key_remains_independent_from_management_password(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    page_key = "api-test-secret"

    with TestClient(create_app()) as client:
        saved = client.put(
            "/agent-shell/api/api-server",
            headers=_bearer(MANAGEMENT_TOKEN),
            json={"api_key": {"operation": "replace", "value": page_key}},
        )
        missing = client.get("/compat/openai/v1/models")
        wrong_scope = client.get(
            "/compat/openai/v1/models", headers=_bearer(MANAGEMENT_TOKEN)
        )
        allowed = client.get("/compat/openai/v1/models", headers=_bearer(page_key))

    assert saved.status_code == 200
    assert saved.json()["api_key"] == {"configured": True}
    assert missing.status_code == 401
    assert wrong_scope.status_code == 403
    assert allowed.status_code == 200
def test_remote_mode_requires_the_single_persisted_api_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agent_shell.settings import SettingsError

    _configure_paths(monkeypatch, tmp_path)
    _write_system_settings(tmp_path, allow_remote=True)
    with pytest.raises(SettingsError) as captured:
        create_app()

    assert captured.value.keys == ("API Server API Key",)
    assert "Remote access requires an API Key" in str(captured.value)

def test_remote_mode_cannot_clear_the_persisted_api_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_auth(monkeypatch, tmp_path)
    _write_system_settings(tmp_path, allow_remote=True)

    with TestClient(create_app()) as client:
        response = client.put(
            "/agent-shell/api/api-server",
            headers=_bearer(MANAGEMENT_TOKEN),
            json={"api_key": {"operation": "clear"}},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "api_key_required"
def test_management_and_api_scopes_are_independent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_auth(monkeypatch, tmp_path)
    app = create_app()

    @app.get("/agent-shell/api/whoami")
    async def whoami(request: Request) -> dict[str, object]:
        principal = request.state.principal
        return {
            "scope": principal.scope,
            "authenticated": principal.authenticated,
            "subject": principal.subject,
        }

    with TestClient(app) as client:
        management = client.get("/agent-shell/api/whoami", headers=_bearer(MANAGEMENT_TOKEN))
        wrong_management_scope = client.get(
            "/agent-shell/api/catalog", headers=_bearer(API_KEY)
        )
        api_namespace = client.get(
            "/compat/openai/v1/not-implemented", headers=_bearer(API_KEY)
        )
        wrong_api_scope = client.get(
            "/compat/openai/v1/not-implemented", headers=_bearer(MANAGEMENT_TOKEN)
        )

    assert management.json() == {
        "scope": "management",
        "authenticated": True,
        "subject": "management-token",
    }
    assert wrong_management_scope.status_code == 403
    assert wrong_management_scope.json()["error"]["code"] == "insufficient_scope"
    assert api_namespace.status_code == 404
    assert wrong_api_scope.status_code == 403
    assert wrong_api_scope.json()["error"]["code"] == "insufficient_scope"

@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer  two-spaces"},
        {"Authorization": "Bearer wrong-secret"},
        {"Authorization": "Bearer " + "a" * 8200},
    ],
)
def test_invalid_bearer_forms_use_stable_401_without_echo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    headers: dict[str, str],
) -> None:
    _configure_auth(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        response = client.get("/agent-shell/api/catalog", headers=headers)

    payload = response.json()
    assert response.status_code == 401
    assert payload["error"] == {
        "message": "A valid Bearer token is required.",
        "type": "authentication_error",
        "param": None,
        "code": "invalid_api_key",
        "message_key": "errors.invalidManagementCredential",
        "message_args": {},
    }
    assert payload["request_id"].startswith("req_")
    assert response.headers["x-request-id"] == payload["request_id"]
    assert 'error="invalid_token"' in response.headers["www-authenticate"]
    assert "wrong-secret" not in response.text

def test_bearer_parser_rejects_delete_control_character() -> None:
    scope = {"headers": [(b"authorization", b"Bearer invalid\x7fvalue")]}

    with pytest.raises(SecurityFailure) as raised:
        _parse_bearer(scope)

    assert raised.value.status_code == 401
    assert raised.value.code == "invalid_api_key"

def test_duplicate_authorization_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_auth(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        response = client.get(
            "/agent-shell/api/catalog",
            headers=[
                ("Authorization", f"Bearer {MANAGEMENT_TOKEN}"),
                ("Authorization", f"Bearer {MANAGEMENT_TOKEN}"),
            ],
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"

def test_authentication_stops_before_route_or_upstream_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_auth(monkeypatch, tmp_path)
    called = False
    app = create_app()

    @app.get("/agent-shell/api/auth-order/{item_id}")
    async def auth_order(item_id: str) -> dict[str, str]:
        nonlocal called
        called = True
        return {"item_id": item_id}

    with TestClient(app) as client:
        response = client.get("/agent-shell/api/auth-order/sensitive-item")

    assert response.status_code == 401
    assert called is False
    assert "sensitive-item" not in response.text

def test_valid_cors_preflight_does_not_require_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_auth(monkeypatch, tmp_path)
    _write_system_settings(tmp_path, cors_origins=["https://console.example"])

    with TestClient(create_app()) as client:
        response = client.options(
            "/agent-shell/api/catalog",
            headers={
                "Origin": "https://console.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization, X-Request-ID",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://console.example"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()

def test_allowed_cors_origin_can_read_authentication_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_auth(monkeypatch, tmp_path)
    _write_system_settings(tmp_path, cors_origins=["https://console.example"])

    with TestClient(create_app()) as client:
        response = client.get(
            "/agent-shell/api/catalog",
            headers={"Origin": "https://console.example"},
        )

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "https://console.example"
    assert response.json()["error"]["code"] == "invalid_api_key"

def test_client_request_id_is_validated_and_returned(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_auth(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        accepted = client.get(
            "/agent-shell/api/catalog",
            headers={**_bearer(MANAGEMENT_TOKEN), "X-Request-ID": "client_req-123"},
        )
        replaced = client.get(
            "/agent-shell/api/catalog",
            headers={**_bearer(MANAGEMENT_TOKEN), "X-Request-ID": "bad value"},
        )

    assert accepted.headers["x-request-id"] == "client_req-123"
    assert replaced.headers["x-request-id"].startswith("req_")
