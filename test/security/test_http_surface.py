from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from agent_shell.app import create_app

from .http_security_support import *


class _AdminAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []
        self.external: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        target = ""
        if tag == "script":
            target = attributes.get("src") or ""
        elif tag == "link" and "stylesheet" in (attributes.get("rel") or "").split():
            target = attributes.get("href") or ""
        if not target:
            return
        if target.startswith(("http://", "https://", "//")):
            self.external.append(target)
        else:
            self.assets.append(target)


def test_health_and_static_shell_remain_public_when_api_auth_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_auth(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        health = client.get("/api/health")
        admin = client.get("/admin")
        protected = client.get("/api/catalog")

    assert health.status_code == 200
    assert admin.status_code == 200
    assert protected.status_code == 401

def test_admin_shell_uses_only_bundled_script_assets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_auth(monkeypatch, tmp_path)

    with TestClient(create_app(), follow_redirects=False) as client:
        root = client.get("/")
        admin = client.get("/admin")
        favicon = client.get("/admin/favicon.ico")
        parser = _AdminAssetParser()
        parser.feed(admin.text)
        assets = {path: client.get(path) for path in parser.assets}
        removed_assets = [
            client.get(path)
            for path in (
                "/admin/assets/vendor/vue-3.5.13.global.prod.js",
                "/admin/assets/icons.js",
                "/admin/assets/api.js",
            )
        ]
        protected = client.get("/api/catalog")
        authorized = client.get(
            "/api/catalog", headers=_bearer(MANAGEMENT_TOKEN)
        )

    assert root.status_code == 307
    assert root.headers["location"] == "/admin"
    assert admin.status_code == 200
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/x-icon")
    assert favicon.content
    assert parser.external == []
    assert parser.assets
    assert len(parser.assets) == len(set(parser.assets))
    for path, response in assets.items():
        assert re.fullmatch(
            r"/admin/assets/[A-Za-z0-9_-]+-[A-Za-z0-9_-]+\.(?:js|css)", path
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            "text/javascript" if path.endswith(".js") else "text/css"
        )
    assert all(response.status_code == 404 for response in removed_assets)
    assert protected.status_code == 401
    assert authorized.status_code == 200


def test_automatic_fastapi_documentation_is_not_registered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_auth(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        responses = [client.get(path) for path in ("/openapi.json", "/docs", "/redoc")]

    assert all(response.status_code == 404 for response in responses)
