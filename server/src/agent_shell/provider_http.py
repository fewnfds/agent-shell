from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from curl_cffi.const import CurlECode
from curl_cffi.requests.exceptions import RequestException
from httpx_curl_cffi import AsyncCurlTransport, CurlTransport
from httpx_curl_cffi.transport import CurlAsyncByteStream


class ProviderStreamError(RuntimeError):
    """Safe evidence for a curl failure after a response stream has started."""

    def __init__(self, *, curl_code: int) -> None:
        self.curl_code = curl_code
        try:
            self.curl_error = CurlECode(curl_code).name
        except ValueError:
            self.curl_error = "UNKNOWN"
        super().__init__("provider response stream failed")


class _ProviderAsyncByteStream(CurlAsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for data in super().__aiter__():
                yield data
        except RequestException as exc:
            raise ProviderStreamError(curl_code=int(exc.code)) from exc


class ProviderAsyncCurlTransport(AsyncCurlTransport):
    _stream_wrap_cls = _ProviderAsyncByteStream

    def _create_request_params(self, req: httpx.Request) -> dict[str, Any]:
        params = super()._create_request_params(req)
        # httpx expands timeout=None into four disabled timeout fields, while
        # httpx-curl-cffi 0.1.5 forwards the relevant pair as (None, None).
        # curl-cffi represents the same disabled timeout as a single None.
        if params.get("timeout") == (None, None):
            params["timeout"] = None
        return params


class ProviderHttpClients:
    """Process-owned curl-backed clients shared by Provider integrations."""

    def __init__(self) -> None:
        self._sync_client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Provider HTTP clients are closed")

    @property
    def sync_client(self) -> httpx.Client:
        self._ensure_open()
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                transport=CurlTransport(
                    impersonate="chrome",
                    default_headers=False,
                ),
                trust_env=False,
            )
        return self._sync_client

    @property
    def async_client(self) -> httpx.AsyncClient:
        self._ensure_open()
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                transport=ProviderAsyncCurlTransport(
                    impersonate="chrome",
                    default_headers=False,
                ),
                trust_env=False,
            )
        return self._async_client

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        async_client, self._async_client = self._async_client, None
        sync_client, self._sync_client = self._sync_client, None
        try:
            if async_client is not None:
                await async_client.aclose()
        finally:
            if sync_client is not None:
                sync_client.close()
