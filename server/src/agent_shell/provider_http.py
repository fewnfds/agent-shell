from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from curl_cffi.const import CurlECode
from curl_cffi.requests.exceptions import RequestException
from httpx_curl_cffi import AsyncCurlTransport, CurlTransport
from httpx_curl_cffi.transport import CurlAsyncByteStream

from agent_shell.storage.runtime_policy import RUNTIME_POLICY_DEFAULTS, RuntimePolicyStore


def provider_http_timeout(
    runtime_policy: RuntimePolicyStore | None = None,
) -> httpx.Timeout:
    policy = (
        runtime_policy.snapshot()
        if runtime_policy is not None
        else RUNTIME_POLICY_DEFAULTS
    )
    return httpx.Timeout(
        float(policy.provider_timeout_seconds),
        connect=float(policy.provider_connect_timeout_seconds),
    )


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


class ProviderHttpClients:
    """Process-owned curl-backed clients shared by Provider integrations."""

    def __init__(self, runtime_policy: RuntimePolicyStore | None = None) -> None:
        self._runtime_policy = runtime_policy
        self._sync_client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Provider HTTP clients are closed")

    def timeout(self) -> httpx.Timeout:
        return provider_http_timeout(self._runtime_policy)

    @property
    def sync_client(self) -> httpx.Client:
        self._ensure_open()
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                transport=CurlTransport(
                    impersonate="chrome",
                    default_headers=False,
                ),
                timeout=self.timeout(),
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
                    max_connections=100,
                ),
                timeout=self.timeout(),
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
