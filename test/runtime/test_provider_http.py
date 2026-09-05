from __future__ import annotations

import asyncio

import httpx
import pytest
from curl_cffi.const import CurlECode
from curl_cffi.requests.exceptions import RequestException

from agent_shell import provider_http


def test_async_provider_transport_preserves_disabled_httpx_timeout() -> None:
    loop = asyncio.SelectorEventLoop()
    transport = provider_http.ProviderAsyncCurlTransport(
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


def test_provider_http_clients_are_shared_and_closed_by_their_single_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json={"ok": True})

    def sync_transport(**kwargs):
        calls.append(("sync", kwargs))
        return httpx.MockTransport(handler)

    def async_transport(**kwargs):
        calls.append(("async", kwargs))
        return httpx.MockTransport(handler)

    monkeypatch.setattr(provider_http, "CurlTransport", sync_transport)
    monkeypatch.setattr(provider_http, "ProviderAsyncCurlTransport", async_transport)
    clients = provider_http.ProviderHttpClients()

    async def scenario() -> None:
        assert clients.sync_client is clients.sync_client
        assert clients.async_client is clients.async_client
        assert clients.sync_client.get("https://provider.example/v1").status_code == 200
        response = await clients.async_client.get("https://provider.example/v1")
        assert response.status_code == 200
        concurrent = await asyncio.gather(
            *(
                clients.async_client.get("https://provider.example/v1")
                for _ in range(20)
            )
        )
        assert all(item.status_code == 200 for item in concurrent)
        await clients.aclose()
        await clients.aclose()

    asyncio.run(scenario())

    assert calls == [
        ("sync", {"impersonate": "chrome", "default_headers": False}),
        (
            "async",
            {
                "impersonate": "chrome",
                "default_headers": False,
            },
        ),
    ]
    with pytest.raises(RuntimeError, match="closed"):
        _ = clients.sync_client


def test_async_provider_stream_preserves_only_safe_curl_failure_evidence() -> None:
    sensitive_detail = "https://secret.example/private provider response body"

    class FailingResponse:
        queue = True

        async def aiter_content(self):
            yield b"partial"
            raise RequestException(sensitive_detail, CurlECode.RECV_ERROR)

        async def aclose(self) -> None:
            return None

    async def scenario() -> provider_http.ProviderStreamError:
        stream = provider_http._ProviderAsyncByteStream(FailingResponse())
        chunks = aiter(stream)
        assert await anext(chunks) == b"partial"
        with pytest.raises(provider_http.ProviderStreamError) as raised:
            await anext(chunks)
        await stream.aclose()
        return raised.value

    error = asyncio.run(scenario())

    assert error.curl_code == 56
    assert error.curl_error == "RECV_ERROR"
    assert sensitive_detail not in str(error)
