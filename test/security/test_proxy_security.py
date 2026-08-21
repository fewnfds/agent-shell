from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.testclient import TestClient
import pytest

from agent_shell.app import create_app

from .http_security_support import *

def _configure_trusted_proxy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_auth(monkeypatch, tmp_path)
    _write_system_settings(
        tmp_path,
        allow_remote=True,
        trusted_proxy_cidrs=["10.0.0.0/8"],
    )


def _proxy_inspection_app() -> object:
    app = create_app()

    @app.get("/inspect-proxy")
    async def inspect_proxy(request: Request) -> dict[str, object]:
        return {
            "client": request.client.host if request.client else None,
            "scheme": request.url.scheme,
            "host": request.headers.get("host"),
        }

    return app


def test_proxy_headers_are_ignored_when_no_proxy_is_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    app = _proxy_inspection_app()

    with TestClient(app, client=("192.0.2.20", 5000)) as client:
        response = client.get(
            "/inspect-proxy",
            headers={
                "X-Forwarded-For": "198.51.100.7",
                "X-Forwarded-Proto": "https",
            },
        )

    assert response.json() == {
        "client": "192.0.2.20",
        "scheme": "http",
        "host": "testserver",
    }

def test_trusted_x_forwarded_chain_sets_only_validated_request_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_trusted_proxy(monkeypatch, tmp_path)
    app = _proxy_inspection_app()

    with TestClient(app, client=("10.2.0.4", 5000)) as client:
        response = client.get(
            "/inspect-proxy",
            headers={
                "X-Forwarded-For": "198.51.100.7, 10.1.0.3",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "Console.Example:8443",
            },
        )

    assert response.json() == {
        "client": "198.51.100.7",
        "scheme": "https",
        "host": "console.example:8443",
    }

def test_standard_forwarded_header_is_supported_from_trusted_peer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_trusted_proxy(monkeypatch, tmp_path)
    app = _proxy_inspection_app()

    with TestClient(app, client=("10.2.0.4", 5000)) as client:
        response = client.get(
            "/inspect-proxy",
            headers={
                "Forwarded": (
                    "for=198.51.100.8;proto=https;host=public.example, "
                    "for=10.1.0.3;proto=https;host=public.example"
                )
            },
        )

    assert response.json() == {
        "client": "198.51.100.8",
        "scheme": "https",
        "host": "public.example",
    }

@pytest.mark.parametrize(
    ("direct_client", "headers"),
    [
        (("192.0.2.20", 5000), {"X-Forwarded-For": "198.51.100.7"}),
        (
            ("10.2.0.4", 5000),
            {"Forwarded": "for=198.51.100.7", "X-Forwarded-For": "198.51.100.7"},
        ),
        (("10.2.0.4", 5000), {"X-Forwarded-Proto": "https"}),
        (
            ("10.2.0.4", 5000),
            {"X-Forwarded-For": "not-an-ip", "X-Forwarded-Proto": "https"},
        ),
        (
            ("10.2.0.4", 5000),
            {"X-Forwarded-For": "198.51.100.7", "X-Forwarded-Port": "443"},
        ),
    ],
)
def test_invalid_or_untrusted_proxy_headers_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    direct_client: tuple[str, int],
    headers: dict[str, str],
) -> None:
    _configure_trusted_proxy(monkeypatch, tmp_path)
    app = _proxy_inspection_app()

    with TestClient(app, client=direct_client) as client:
        response = client.get("/inspect-proxy", headers=headers)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_proxy_headers"
    assert response.headers["x-request-id"] == response.json()["request_id"]
    assert "198.51.100.7" not in response.text

def test_management_proxy_error_exposes_a_localization_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_trusted_proxy(monkeypatch, tmp_path)
    _write_system_settings(
        tmp_path,
        allow_remote=True,
        trusted_proxy_cidrs=["10.0.0.0/8"],
        cors_origins=["https://console.example"],
    )

    with TestClient(create_app(), client=("10.2.0.4", 5000)) as client:
        response = client.get(
            "/api/catalog",
            headers={
                "Origin": "https://console.example",
                "X-Forwarded-For": "not-an-ip",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"]["message_key"] == "errors.invalidProxyHeaders"
    assert response.json()["error"]["message_args"] == {}
    assert response.headers["access-control-allow-origin"] == "https://console.example"
