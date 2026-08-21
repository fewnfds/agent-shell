from __future__ import annotations

from dataclasses import fields, is_dataclass
import re
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel


REDACTED = "[REDACTED]"
UNAVAILABLE = "[UNAVAILABLE]"
LOCAL_PATH = "[LOCAL_PATH]"
MAX_REDACTION_DEPTH = 12
REDACTION_BOUNDARIES = frozenset(
    {
        "http-error",
        "event-log",
        "preflight-diagnostic",
        "request-trace",
    }
)

SENSITIVE_FIELD_REGISTRY = {
    "api_key": "secret",
    "authorization": "secret",
    "access_token": "secret",
    "refresh_token": "secret",
    "bearer_token": "secret",
    "management_token": "secret",
    "client_secret": "secret",
    "secret": "secret",
    "secret_value": "secret",
    "password": "secret",
    "messages": "content",
    "upstream_messages": "content",
    "tool_arguments": "content",
    "tool_args": "content",
    "provider_response": "content",
    "raw_response": "content",
    "response_body": "content",
    "traceback": "content",
    "stacktrace": "content",
    "source_code": "content",
    "local_path": "path",
    "source_path": "path",
    "database_path": "path",
    "runtime_dir": "path",
}

_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/=]+")
_API_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_WINDOWS_PATH_PATTERN = re.compile(
    r"(?i)(?<![A-Z0-9])(?:[A-Z]:[\\/]|\\\\)[^\s\"'<>]+"
)
_POSIX_HOST_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9:/])/(?:Users|home|var|tmp|etc|opt|srv|mnt)/[^\s\"'<>]+"
)


class RedactionPolicy:
    def __init__(self, known_secret_values: Iterable[str] = ()) -> None:
        self._known_secrets = tuple(
            sorted(
                {value for value in known_secret_values if isinstance(value, str) and value},
                key=len,
                reverse=True,
            )
        )

    def redact(self, value: Any) -> Any:
        return self._redact(value, (), 0, set())

    def _redact(
        self,
        value: Any,
        path: tuple[str, ...],
        depth: int,
        active: set[int],
    ) -> Any:
        if depth > MAX_REDACTION_DEPTH:
            return UNAVAILABLE
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return self._redact_string(
                value,
                path_sensitive=bool(
                    path and SENSITIVE_FIELD_REGISTRY.get(path[-1]) == "path"
                ),
            )
        if isinstance(value, bytes):
            return REDACTED
        if isinstance(value, BaseException):
            cause = value.__cause__ or value.__context__
            return {
                "type": "exception",
                "message": "An internal operation failed.",
                "cause": (
                    self._redact(cause, (*path, "cause"), depth + 1, active)
                    if cause is not None
                    else None
                ),
            }

        identity = id(value)
        if identity in active:
            return UNAVAILABLE
        active.add(identity)
        try:
            if isinstance(value, BaseModel):
                try:
                    dumped = value.model_dump(mode="json")
                except Exception:
                    return UNAVAILABLE
                return self._redact(dumped, path, depth + 1, active)
            if is_dataclass(value) and not isinstance(value, type):
                payload: dict[str, Any] = {}
                for field in fields(value):
                    try:
                        payload[field.name] = getattr(value, field.name)
                    except Exception:
                        payload[field.name] = UNAVAILABLE
                return self._redact(payload, path, depth + 1, active)
            if isinstance(value, dict):
                result: dict[str, Any] = {}
                for raw_key, child in value.items():
                    if not isinstance(raw_key, str):
                        result[UNAVAILABLE] = UNAVAILABLE
                        continue
                    kind = SENSITIVE_FIELD_REGISTRY.get(raw_key.lower())
                    if kind in {"secret", "content"}:
                        result[raw_key] = REDACTED
                    else:
                        result[raw_key] = self._redact(
                            child, (*path, raw_key.lower()), depth + 1, active
                        )
                return result
            if isinstance(value, (list, tuple)):
                return [
                    self._redact(child, (*path, str(index)), depth + 1, active)
                    for index, child in enumerate(value)
                ]
            if isinstance(value, (set, frozenset)):
                return [UNAVAILABLE for _ in value]
            return UNAVAILABLE
        finally:
            active.discard(identity)

    def _redact_string(self, value: str, *, path_sensitive: bool) -> str:
        if path_sensitive and (
            value.startswith("/")
            or _WINDOWS_PATH_PATTERN.match(value)
        ):
            return LOCAL_PATH
        redacted = self._remove_url_userinfo(value)
        redacted = _BEARER_PATTERN.sub(f"Bearer {REDACTED}", redacted)
        redacted = _API_KEY_PATTERN.sub(REDACTED, redacted)
        redacted = _WINDOWS_PATH_PATTERN.sub(LOCAL_PATH, redacted)
        redacted = _POSIX_HOST_PATH_PATTERN.sub(LOCAL_PATH, redacted)
        for secret in self._known_secrets:
            redacted = redacted.replace(secret, REDACTED)
        return redacted

    @staticmethod
    def _remove_url_userinfo(value: str) -> str:
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or parsed.username is None:
                return value
            hostname = parsed.hostname or ""
            if ":" in hostname:
                hostname = f"[{hostname}]"
            netloc = hostname
            if parsed.port is not None:
                netloc = f"{netloc}:{parsed.port}"
            return urlunsplit(
                (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
            )
        except (ValueError, UnicodeError):
            return REDACTED if "://" in value and "@" in value else value


DEFAULT_REDACTION_POLICY = RedactionPolicy()


def redact_for_boundary(boundary: str, value: Any) -> Any:
    if boundary not in REDACTION_BOUNDARIES:
        raise ValueError("unsupported redaction boundary")
    return DEFAULT_REDACTION_POLICY.redact(value)
