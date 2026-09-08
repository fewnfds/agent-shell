from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from curl_cffi.const import CurlECode, CurlHttpVersion, CurlOpt
from curl_cffi.requests.exceptions import RequestException
from httpx_curl_cffi import AsyncCurlTransport, CurlTransport
from httpx_curl_cffi.transport import CurlAsyncByteStream

from agent_shell.provider_http import ProviderHttpSettings


class ProviderStreamError(RuntimeError):
    """Preserve a curl failure after a Provider response stream has started."""

    def __init__(self, message: str, *, curl_code: int) -> None:
        self.curl_code = curl_code
        try:
            self.curl_error = CurlECode(curl_code).name
        except ValueError:
            self.curl_error = "UNKNOWN"
        super().__init__(
            f"Provider response stream failed with curl {self.curl_error} "
            f"({self.curl_code}): {message}"
        )


class _ProviderAsyncByteStream(CurlAsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for data in super().__aiter__():
                yield data
        except RequestException as exc:
            raise ProviderStreamError(str(exc), curl_code=int(exc.code)) from exc


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


def _transport_options(
    settings: ProviderHttpSettings,
    *,
    ca_bundle: Path | None,
) -> dict[str, object]:
    versions = {
        "auto": None,
        "http1": CurlHttpVersion.V1_1,
        "http2": CurlHttpVersion.V2TLS,
    }
    options: dict[str, object] = {
        "impersonate": "chrome",
        "default_headers": False,
        "verify": settings.tls_verify,
        "http_version": versions[settings.http_version],
        "proxy": settings.proxy_url,
    }
    if ca_bundle is not None:
        options["curl_options"] = {CurlOpt.CAINFO: str(ca_bundle)}
    return options


def build_curl_transport(
    settings: ProviderHttpSettings,
    *,
    ca_bundle: Path | None,
    asynchronous: bool,
) -> httpx.BaseTransport | httpx.AsyncBaseTransport:
    options = _transport_options(settings, ca_bundle=ca_bundle)
    if asynchronous:
        return ProviderAsyncCurlTransport(**options)
    return CurlTransport(**options)
