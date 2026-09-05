from __future__ import annotations

import asyncio
import httpx
import pytest

from agent_shell import __version__
from agent_shell.app import create_app

from .provider_secret_support import *


def test_model_catalog_reports_a_missing_saved_connection_as_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = make_client(tmp_path, monkeypatch)

    response = client.post(
        "/agent-shell/api/fetch-models",
        json={
            "provider": "openai",
            "base_url": "https://provider.example/v1",
            "credential": None,
            "block_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "model_connection_not_found"
    assert response.json()["detail"]["message_key"] == (
        "errors.modelConnectionNotFound"
    )

def test_model_catalog_uses_entered_or_saved_key_and_allows_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = make_client(tmp_path, monkeypatch)
    connection = client.post("/agent-shell/api/model-connections", json=model_payload()).json()
    original_resolve_connection = client.app.state.model_resources.resolve_connection

    def resolve_connection_outside_event_loop(connection_id: str) -> dict:
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return original_resolve_connection(connection_id)

    monkeypatch.setattr(
        client.app.state.model_resources,
        "resolve_connection",
        resolve_connection_outside_event_loop,
    )
    observed: list[tuple[str, str]] = []
    observed_timeouts: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_timeouts.append(request.extensions.get("timeout"))
        observed.append(
            (
                request.headers.get("Authorization", ""),
                request.headers.get("User-Agent", ""),
            )
        )
        return httpx.Response(
            200,
            request=request,
            json={"data": [{"id": "one", "owned_by": "provider-private"}]},
        )

    monkeypatch.setattr(
        "agent_shell.provider_http.ProviderAsyncCurlTransport",
        lambda **kwargs: httpx.MockTransport(handler),
    )
    response = client.post(
        "/agent-shell/api/fetch-models",
        json={
            "provider": "openai",
            "base_url": connection["base_url"],
            "credential": None,
            "block_id": connection["id"],
        },
    )
    no_key_response = client.post(
        "/agent-shell/api/fetch-models",
        json={
            "provider": "openai",
            "base_url": connection["base_url"],
            "credential": None,
            "block_id": "",
        },
    )

    assert response.status_code == 200
    assert no_key_response.status_code == 200
    assert response.json() == ["one"]
    assert observed == [
        (f"Bearer {LOCAL_SECRET}", f"Agent-Shell/{__version__}"),
        ("", f"Agent-Shell/{__version__}"),
    ]
    assert observed_timeouts == [
        {"connect": None, "read": None, "write": None, "pool": None},
        {"connect": None, "read": None, "write": None, "pool": None},
    ]
    assert LOCAL_SECRET not in response.text
    assert "provider-private" not in response.text

def test_model_catalog_never_reuses_saved_key_for_a_different_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = make_client(tmp_path, monkeypatch)
    connection = client.post("/agent-shell/api/model-connections", json=model_payload()).json()
    upstream_called = False

    def unexpected_client(**kwargs):
        nonlocal upstream_called
        upstream_called = True
        raise AssertionError("the changed endpoint must not receive an upstream request")

    monkeypatch.setattr(
        "agent_shell.provider_http.ProviderAsyncCurlTransport", unexpected_client
    )
    response = client.post(
        "/agent-shell/api/fetch-models",
        json={
            "provider": "openai",
            "base_url": "https://other-provider.example/v1",
            "credential": None,
            "block_id": connection["id"],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "provider_credential_connection_changed"
    assert upstream_called is False
    assert LOCAL_SECRET not in response.text

def test_model_catalog_reports_cloudflare_browser_challenge_without_leaking_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = make_client(tmp_path, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            request=request,
            headers={"Cf-Mitigated": "challenge", "Server": "cloudflare"},
            text="provider-private challenge body",
        )

    monkeypatch.setattr(
        "agent_shell.provider_http.ProviderAsyncCurlTransport",
        lambda **kwargs: httpx.MockTransport(handler),
    )
    response = client.post(
        "/agent-shell/api/fetch-models",
        json={
            "provider": "openai",
            "base_url": "https://provider.example/v1",
            "credential": LOCAL_SECRET,
            "block_id": "",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "model_catalog_browser_challenge"
    assert "provider-private" not in response.text

def test_model_catalog_never_reuses_saved_key_for_a_different_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = make_client(tmp_path, monkeypatch)
    connection = client.post("/agent-shell/api/model-connections", json=model_payload()).json()
    upstream_called = False

    def unexpected_client(**kwargs):
        nonlocal upstream_called
        upstream_called = True
        raise AssertionError("the changed Provider must not receive an upstream request")

    monkeypatch.setattr(
        "agent_shell.provider_http.ProviderAsyncCurlTransport", unexpected_client
    )
    response = client.post(
        "/agent-shell/api/fetch-models",
        json={
            "provider": "deepseek",
            "base_url": connection["base_url"],
            "credential": None,
            "block_id": connection["id"],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "provider_credential_connection_changed"
    assert upstream_called is False
    assert LOCAL_SECRET not in response.text

@pytest.mark.parametrize(
    "provider_payload",
    [
        {"unexpected": []},
        {"data": "not-a-list"},
        {"data": [{"id": ""}]},
        {"data": [{"id": 123}]},
        {"data": [{"id": "safe-model", "secret_field": "provider-private"}, None]},
    ],
)
def test_model_catalog_rejects_malformed_provider_payload_without_leaking_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_payload: object,
) -> None:
    client, _ = make_client(tmp_path, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json=provider_payload)

    monkeypatch.setattr(
        "agent_shell.provider_http.ProviderAsyncCurlTransport",
        lambda **kwargs: httpx.MockTransport(handler),
    )
    response = client.post(
        "/agent-shell/api/fetch-models",
        json={
            "provider": "openai",
            "base_url": "https://provider.example/v1",
            "credential": None,
            "block_id": "",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalid_model_catalog_response"
    assert "provider-private" not in response.text
