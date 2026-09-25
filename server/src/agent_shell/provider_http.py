from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
from typing import Literal, cast
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_shell import __version__
from agent_shell.provider_http_logging import (
    GoogleObservedTransport,
    ObservedAsyncTransport,
    ObservedSyncTransport,
    ProviderHttpObserver,
)


ProviderHttpTransport = Literal["httpx", "curl_cffi"]
ProviderHttpVersion = Literal["auto", "http1", "http2"]
DEFAULT_PROVIDER_USER_AGENT = f"Agent-Shell/{__version__}"

_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


class ProviderHttpSettings(BaseModel):
    """Persisted process-wide Provider network settings."""

    model_config = ConfigDict(extra="forbid")

    transport: ProviderHttpTransport = "curl_cffi"
    http_version: ProviderHttpVersion = "auto"
    tls_verify: bool = True
    ca_bundle: str | None = None
    proxy_url: str | None = None
    default_headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("ca_bundle", mode="before")
    @classmethod
    def normalize_ca_bundle(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("proxy_url", mode="before")
    @classmethod
    def validate_proxy_url(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().rstrip("/")
        if not normalized:
            return None
        parsed = urlsplit(normalized)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "must be an HTTP(S) proxy URL without credentials, path, query, or fragment"
            )
        return normalized

    @field_validator("default_headers")
    @classmethod
    def validate_default_headers(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        names: set[str] = set()
        for raw_name, raw_value in value.items():
            name = raw_name.strip()
            if not name or not _HEADER_NAME.fullmatch(name):
                raise ValueError(f"invalid HTTP header name: {raw_name!r}")
            folded = name.lower()
            if folded in names:
                raise ValueError(f"duplicate HTTP header name: {name!r}")
            if "\r" in raw_value or "\n" in raw_value:
                raise ValueError(f"HTTP header value contains a line break: {name!r}")
            try:
                raw_value.encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError(
                    f"HTTP header value must contain ASCII characters: {name!r}"
                ) from exc
            names.add(folded)
            normalized[name] = raw_value
        return normalized

    @model_validator(mode="after")
    def validate_tls_options(self) -> "ProviderHttpSettings":
        if self.ca_bundle is not None and not self.tls_verify:
            raise ValueError("ca_bundle requires tls_verify=true")
        return self

    def resolve_ca_bundle(self, data_root: Path) -> Path | None:
        if self.ca_bundle is None:
            return None
        candidate = Path(self.ca_bundle)
        if not candidate.is_absolute():
            candidate = data_root / candidate
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError("ca_bundle must reference a file")
        return resolved


def merge_http_headers(*layers: Mapping[str, str]) -> dict[str, str]:
    """Merge Header layers case-insensitively; later layers win."""

    merged: dict[str, tuple[str, str]] = {}
    for layer in layers:
        for name, value in layer.items():
            merged[name.lower()] = (name, value)
    return {name: value for name, value in merged.values()}


class ProviderHttpClients:
    """Own the shared sync/async clients for the selected Provider route."""

    def __init__(
        self,
        settings: ProviderHttpSettings | None = None,
        *,
        data_root: Path | None = None,
        observer: ProviderHttpObserver | None = None,
    ) -> None:
        self.settings = (settings or ProviderHttpSettings()).model_copy(deep=True)
        self._ca_bundle = self.settings.resolve_ca_bundle(
            (data_root or Path.cwd()).resolve()
        )
        self._sync_client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None
        self._google_sync_client: httpx.Client | None = None
        self._google_async_client: httpx.AsyncClient | None = None
        self._closed = False
        self._observer = observer

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Provider HTTP clients are closed")

    def request_headers(
        self,
        defaults: Mapping[str, str] | None = None,
        overrides: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        return merge_http_headers(
            defaults or {},
            self.settings.default_headers,
            overrides or {},
        )

    def _httpx_options(self) -> dict[str, object]:
        return {
            "verify": str(self._ca_bundle)
            if self._ca_bundle is not None
            else self.settings.tls_verify,
            "http1": self.settings.http_version != "http2",
            "http2": self.settings.http_version != "http1",
            "proxy": self.settings.proxy_url,
            "trust_env": False,
        }

    def _curl_transport(self, *, asynchronous: bool) -> httpx.BaseTransport:
        try:
            from agent_shell.provider_curl import build_curl_transport
        except ImportError as exc:
            raise RuntimeError(
                "The curl-cffi Provider route is selected but its runtime dependency "
                "is unavailable"
            ) from exc
        return cast(
            httpx.BaseTransport,
            build_curl_transport(
                self.settings,
                ca_bundle=self._ca_bundle,
                asynchronous=asynchronous,
            ),
        )

    @property
    def sync_client(self) -> httpx.Client:
        self._ensure_open()
        if self._sync_client is None:
            if self.settings.transport == "httpx":
                if self._observer is None:
                    self._sync_client = httpx.Client(**self._httpx_options())
                else:
                    inner = httpx.HTTPTransport(**self._httpx_options())
                    self._sync_client = httpx.Client(
                        transport=ObservedSyncTransport(inner, self._observer),
                        trust_env=False,
                    )
            else:
                transport = self._curl_transport(asynchronous=False)
                self._sync_client = httpx.Client(
                    transport=(
                        ObservedSyncTransport(transport, self._observer, already_decoded=True)
                        if self._observer is not None else transport
                    ),
                    trust_env=False,
                )
        return self._sync_client

    @property
    def async_client(self) -> httpx.AsyncClient:
        self._ensure_open()
        if self._async_client is None:
            if self.settings.transport == "httpx":
                if self._observer is None:
                    self._async_client = httpx.AsyncClient(**self._httpx_options())
                else:
                    inner = httpx.AsyncHTTPTransport(**self._httpx_options())
                    self._async_client = httpx.AsyncClient(
                        transport=ObservedAsyncTransport(inner, self._observer),
                        trust_env=False,
                    )
            else:
                transport = cast(
                    httpx.AsyncBaseTransport,
                    self._curl_transport(asynchronous=True),
                )
                self._async_client = httpx.AsyncClient(
                    transport=(
                        ObservedAsyncTransport(transport, self._observer, already_decoded=True)
                        if self._observer is not None else transport
                    ),
                    trust_env=False,
                )
        return self._async_client

    def google_transport(self) -> GoogleObservedTransport | None:
        self._ensure_open()
        if self._observer is None:
            return None
        if self._google_sync_client is None:
            self._google_sync_client = httpx.Client()
        if self._google_async_client is None:
            self._google_async_client = httpx.AsyncClient()
        return GoogleObservedTransport(
            self._observer,
            sync_client=self._google_sync_client,
            async_client=self._google_async_client,
        )

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        async_client, self._async_client = self._async_client, None
        sync_client, self._sync_client = self._sync_client, None
        google_async, self._google_async_client = self._google_async_client, None
        google_sync, self._google_sync_client = self._google_sync_client, None
        try:
            if async_client is not None:
                await async_client.aclose()
        finally:
            try:
                if google_async is not None:
                    await google_async.aclose()
            finally:
                try:
                    if sync_client is not None:
                        sync_client.close()
                finally:
                    if google_sync is not None:
                        google_sync.close()
