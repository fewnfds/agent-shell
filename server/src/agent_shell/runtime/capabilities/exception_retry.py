from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from langchain.agents.middleware import AgentMiddleware, ModelRetryMiddleware


def _retry_field(provider: object) -> str:
    return "retries" if provider == "google_genai" else "max_retries"


def model_block_with_retry_overrides(
    model_block: dict[str, Any],
    capability: dict[str, Any],
) -> dict[str, Any]:
    """Apply the selected retry owner and optional streaming override."""

    configured = dict(model_block)
    provider_settings = dict(model_block.get("provider_settings") or {})
    if capability["force_non_streaming"]:
        provider_settings["streaming"] = False
    retry_count = (
        int(capability["max_retries"])
        if capability["strategy"] == "provider_native"
        else 0
    )
    provider_settings[_retry_field(model_block.get("provider"))] = retry_count
    configured["provider_settings"] = provider_settings
    return configured


def _exception_chain(exc: Exception):
    current: BaseException | None = exc
    for _depth in range(6):
        if current is None:
            return
        yield current
        current = current.__cause__ or current.__context__


def _status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _should_retry(exc: Exception, conditions: frozenset[str]) -> bool:
    for current in _exception_chain(exc):
        status = _status_code(current)
        name = type(current).__name__.lower()
        if "authentication_error" in conditions and (
            status == 401 or "authentication" in name or "unauthorized" in name
        ):
            return True
        if "rate_limit" in conditions and (
            status == 429 or "ratelimit" in name
        ):
            return True
        if "server_error" in conditions and (
            (isinstance(status, int) and 500 <= status <= 599)
            or "serviceunavailable" in name
            or "internalserver" in name
        ):
            return True
        if "timeout" in conditions and (
            isinstance(current, (TimeoutError, httpx.TimeoutException))
            or status == 408
            or "timeout" in name
        ):
            return True
        if "transport_error" in conditions and (
            isinstance(current, ConnectionError)
            or (
                isinstance(current, httpx.TransportError)
                and not isinstance(current, httpx.TimeoutException)
            )
            or any(
                token in name
                for token in (
                    "connection",
                    "providerstream",
                )
            )
            or ("requestexception" in name and status is None)
        ):
            return True
    return False


@dataclass(frozen=True, slots=True)
class ExceptionRetryRuntime:
    after_provider_boundary: tuple[AgentMiddleware, ...] = ()


def materialize_exception_retry(capability: dict[str, Any]) -> ExceptionRetryRuntime:
    if capability["strategy"] == "provider_native":
        return ExceptionRetryRuntime()

    retry_conditions = frozenset(capability["retry_on"])
    return ExceptionRetryRuntime(
        after_provider_boundary=(
            ModelRetryMiddleware(
                max_retries=int(capability["max_retries"]),
                retry_on=lambda exc: _should_retry(exc, retry_conditions),
                on_failure="error",
            ),
        ),
    )


__all__ = [
    "ExceptionRetryRuntime",
    "materialize_exception_retry",
    "model_block_with_retry_overrides",
]
