from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import sys
import threading
import warnings

import httpx
import pytest
from blockbuster import BlockBuster
from blockbuster.blockbuster import BlockingError
from curl_cffi.const import CurlECode, CurlHttpVersion
from curl_cffi.requests.exceptions import RequestException
from curl_cffi.utils import CurlCffiWarning

from agent_shell import langgraph_dev, provider_curl, provider_http


@pytest.mark.parametrize("transport", ["httpx", "curl_cffi"])
def test_provider_routes_send_real_sync_and_async_requests(
    transport: str,
) -> None:
    observed: list[tuple[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            observed.append(
                (
                    self.headers.get("User-Agent", ""),
                    self.headers.get("X-OpenCode-Session", ""),
                )
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, _format: str, *_args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    clients = provider_http.ProviderHttpClients(
        provider_http.ProviderHttpSettings(
            transport=transport,
            http_version="http1",
            default_headers={
                "User-Agent": "my-agent/2.0",
                "X-OpenCode-Session": "cache-group",
            },
        )
    )
    url = f"http://127.0.0.1:{server.server_port}/models"
    headers = clients.request_headers()

    async def scenario() -> None:
        assert clients.sync_client.get(url, headers=headers).text == "ok"
        assert (await clients.async_client.get(url, headers=headers)).text == "ok"
        await clients.aclose()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", CurlCffiWarning)
            asyncio.run(scenario())
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert observed == [
        ("my-agent/2.0", "cache-group"),
        ("my-agent/2.0", "cache-group"),
    ]


def test_async_curl_transport_preserves_disabled_httpx_timeout() -> None:
    loop = asyncio.SelectorEventLoop()
    transport = provider_curl.ProviderAsyncCurlTransport(
        loop=loop,
        impersonate="chrome",
        default_headers=False,
    )
    request = httpx.Request(
        "GET",
        "https://provider.example/v1/models",
        extensions={
            "timeout": {
                "connect": None,
                "read": None,
                "write": None,
                "pool": None,
            }
        },
    )
    try:
        assert transport._create_request_params(request)["timeout"] is None
    finally:
        loop.run_until_complete(transport.aclose())
        loop.close()


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows curl-cffi compatibility",
)
def test_windows_curl_selector_socketpair_keeps_blocking_detection_enabled() -> None:
    async def scenario() -> None:
        blockbuster = BlockBuster(excluded_modules=[])
        blockbuster.activate()
        transport = provider_curl.ProviderAsyncCurlTransport(
            loop=asyncio.get_running_loop(),
            impersonate="chrome",
            default_headers=False,
        )
        try:
            langgraph_dev._allow_windows_curl_selector_socketpair(blockbuster)
            with pytest.warns(CurlCffiWarning, match="Proactor event loop"):
                _ = transport._session.acurl

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen()
                with pytest.raises(BlockingError, match="socket.socket.accept"):
                    listener.accept()
        finally:
            await transport.aclose()
            blockbuster.deactivate()

    asyncio.run(scenario())


def test_provider_http_settings_validate_network_contract(tmp_path: Path) -> None:
    ca_file = tmp_path / "provider-ca.pem"
    ca_file.write_text("certificate", encoding="utf-8")
    settings = provider_http.ProviderHttpSettings(
        transport="httpx",
        http_version="http2",
        ca_bundle="provider-ca.pem",
        proxy_url="https://proxy.example:8443/",
        default_headers={"X-OpenCode-Session": "session-1"},
    )

    assert settings.proxy_url == "https://proxy.example:8443"
    assert settings.resolve_ca_bundle(tmp_path) == ca_file.resolve()
    assert provider_http.merge_http_headers(
        {"User-Agent": "Agent-Shell/1", "X-Test": "default"},
        {"user-agent": "configured", "x-test": "configured"},
        {"X-Test": "request"},
    ) == {"user-agent": "configured", "X-Test": "request"}

    with pytest.raises(ValueError, match="ca_bundle requires"):
        provider_http.ProviderHttpSettings(tls_verify=False, ca_bundle="ca.pem")
    with pytest.raises(ValueError, match="credentials"):
        provider_http.ProviderHttpSettings(proxy_url="http://user:pass@proxy.example")
    with pytest.raises(ValueError, match="line break"):
        provider_http.ProviderHttpSettings(default_headers={"X-Test": "a\nb"})


def test_standard_httpx_route_builds_shared_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json={"ok": True})

    class SyncClient(httpx.Client):
        def __init__(self, **kwargs):
            calls.append(("sync", kwargs))
            super().__init__(transport=httpx.MockTransport(handler))

    class AsyncClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            calls.append(("async", kwargs))
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(provider_http.httpx, "Client", SyncClient)
    monkeypatch.setattr(provider_http.httpx, "AsyncClient", AsyncClient)
    clients = provider_http.ProviderHttpClients(
        provider_http.ProviderHttpSettings(
            transport="httpx",
            http_version="http2",
            tls_verify=False,
            proxy_url="http://proxy.example:8080",
        )
    )

    async def scenario() -> None:
        assert clients.sync_client is clients.sync_client
        assert clients.async_client is clients.async_client
        assert clients.sync_client.get("https://provider.example/v1").status_code == 200
        assert (
            await clients.async_client.get("https://provider.example/v1")
        ).status_code == 200
        await clients.aclose()
        await clients.aclose()

    asyncio.run(scenario())

    options = {
        "verify": False,
        "http1": False,
        "http2": True,
        "proxy": "http://proxy.example:8080",
        "trust_env": False,
    }
    assert calls == [("sync", options), ("async", options)]
    with pytest.raises(RuntimeError, match="closed"):
        _ = clients.sync_client


def test_browser_compatible_route_keeps_current_chrome_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[bool, dict]] = []

    def build_transport(settings, *, ca_bundle, asynchronous):
        calls.append(
            (
                asynchronous,
                provider_curl._transport_options(settings, ca_bundle=ca_bundle),
            )
        )
        handler = lambda request: httpx.Response(200, request=request)
        return httpx.MockTransport(handler)

    monkeypatch.setattr(provider_curl, "build_curl_transport", build_transport)
    clients = provider_http.ProviderHttpClients(
        provider_http.ProviderHttpSettings(
            transport="curl_cffi",
            http_version="http2",
        )
    )

    async def scenario() -> None:
        _ = clients.sync_client
        _ = clients.async_client
        await clients.aclose()

    asyncio.run(scenario())

    expected = {
        "impersonate": "chrome",
        "default_headers": False,
        "verify": True,
        "http_version": CurlHttpVersion.V2TLS,
        "proxy": None,
    }
    assert calls == [(False, expected), (True, expected)]


def test_async_provider_stream_preserves_complete_curl_failure_evidence() -> None:
    provider_detail = "https://provider.example/private provider response body"

    class FailingResponse:
        queue = True

        async def aiter_content(self):
            yield b"partial"
            raise RequestException(provider_detail, CurlECode.RECV_ERROR)

        async def aclose(self) -> None:
            return None

    async def scenario() -> provider_curl.ProviderStreamError:
        stream = provider_curl._ProviderAsyncByteStream(FailingResponse())
        chunks = aiter(stream)
        assert await anext(chunks) == b"partial"
        with pytest.raises(provider_curl.ProviderStreamError) as raised:
            await anext(chunks)
        await stream.aclose()
        return raised.value

    error = asyncio.run(scenario())

    assert error.curl_code == 56
    assert error.curl_error == "RECV_ERROR"
    assert provider_detail in str(error)
