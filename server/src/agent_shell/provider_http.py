from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
from typing import Literal, cast
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ProviderHttpTransport = Literal["httpx", "curl_cffi"]
ProviderHttpVersion = Literal["auto", "http1", "http2"]

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
    ) -> None:
        self.settings = (settings or ProviderHttpSettings()).model_copy(deep=True)
        self._ca_bundle = self.settings.resolve_ca_bundle(
            (data_root or Path.cwd()).resolve()
        )
        self._sync_client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None
        self._closed = False

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
                self._sync_client = httpx.Client(**self._httpx_options())
            else:
                self._sync_client = httpx.Client(
                    transport=self._curl_transport(asynchronous=False),
                    trust_env=False,
                )
        return self._sync_client

    @property
    def async_client(self) -> httpx.AsyncClient:
        self._ensure_open()
        if self._async_client is None:
            if self.settings.transport == "httpx":
                self._async_client = httpx.AsyncClient(**self._httpx_options())
            else:
                self._async_client = httpx.AsyncClient(
                    transport=cast(
                        httpx.AsyncBaseTransport,
                        self._curl_transport(asynchronous=True),
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
