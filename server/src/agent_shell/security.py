from __future__ import annotations

import hmac
import ipaddress
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Literal
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent_shell.localization import localized_message
from agent_shell.settings import Settings, bearer_token_is_valid
from agent_shell.request_context import bind_request_context

if TYPE_CHECKING:
    from agent_shell.security_events import SecurityEventLogger


_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_FORWARDED_HEADER_NAMES = {
    b"forwarded",
    b"x-forwarded-for",
    b"x-forwarded-proto",
    b"x-forwarded-host",
}


@dataclass(frozen=True)
class SecurityPrincipal:
    scope: Literal["management", "api"]
    authenticated: bool
    subject: str


class SecurityFailure(ValueError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.safe_message = message
        super().__init__(code)


class ApiKeyPolicyError(ValueError):
    def __init__(self, code: str, message_key: str, message: str) -> None:
        self.code = code
        self.message_key = message_key
        self.safe_message = message
        super().__init__(code)


class ProxyHeaderError(ValueError):
    pass


def validate_api_key_policy(settings: Settings, api_key: str | None) -> None:
    if api_key is None:
        if settings.deployment_mode == "authenticated_remote":
            raise ApiKeyPolicyError(
                "api_key_required",
                "errors.apiKeyRequired",
                "Remote access requires an API Key.",
            )
        return
    if not bearer_token_is_valid(api_key):
        raise ApiKeyPolicyError(
            "api_key_invalid",
            "errors.apiKeyInvalid",
            "The API Key must be a non-empty printable ASCII value without spaces.",
        )

def _header_values(scope: Scope, name: bytes) -> list[bytes]:
    return [value for key, value in scope.get("headers", []) if key.lower() == name]


def request_id_for_scope(scope: Scope) -> str:
    values = _header_values(scope, b"x-request-id")
    if len(values) == 1:
        try:
            candidate = values[0].decode("ascii")
        except UnicodeDecodeError:
            candidate = ""
        if _REQUEST_ID_PATTERN.fullmatch(candidate):
            return candidate
    return f"req_{uuid4().hex}"


def security_error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    required_scope: str | None = None,
) -> JSONResponse:
    error_type = {
        400: "invalid_request_error",
        401: "authentication_error",
        403: "permission_error",
    }.get(status_code, "security_error")
    headers = {"X-Request-ID": request_id}
    if status_code == 401:
        headers["WWW-Authenticate"] = (
            'Bearer realm="agent-shell", error="invalid_token"'
        )
    elif status_code == 403:
        scope_value = required_scope or ""
        headers["WWW-Authenticate"] = (
            'Bearer realm="agent-shell", error="insufficient_scope", '
            f'scope="{scope_value}"'
        )
    error: dict[str, object] = {
        "message": message,
        "type": error_type,
        "param": None,
        "code": code,
    }
    if required_scope == "management":
        message_key = {
            "insufficient_scope": "errors.managementScopeRequired",
            "invalid_api_key": "errors.invalidManagementCredential",
            "invalid_proxy_headers": "errors.invalidProxyHeaders",
        }.get(code, "errors.requestFailed")
        error.update(
            localized_message(message_key)
        )
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "error": error,
            "request_id": request_id,
        },
    )


def _required_scope(path: str) -> Literal["management", "api"] | None:
    if path == "/api/health":
        return None
    if path == "/api" or path.startswith("/api/"):
        return "management"
    if path == "/v1" or path.startswith("/v1/"):
        return "api"
    return None


def _is_cors_preflight(scope: Scope) -> bool:
    return bool(
        scope.get("method") == "OPTIONS"
        and len(_header_values(scope, b"origin")) == 1
        and len(_header_values(scope, b"access-control-request-method")) == 1
    )


def _parse_bearer(scope: Scope) -> str:
    values = _header_values(scope, b"authorization")
    if len(values) != 1:
        raise SecurityFailure(
            401, "invalid_api_key", "A valid Bearer token is required."
        )
    try:
        raw = values[0].decode("ascii")
    except UnicodeDecodeError as exc:
        raise SecurityFailure(
            401, "invalid_api_key", "A valid Bearer token is required."
        ) from exc
    parts = raw.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise SecurityFailure(
            401, "invalid_api_key", "A valid Bearer token is required."
        )
    if any(
        character.isspace() or ord(character) < 33 or ord(character) == 127
        for character in parts[1]
    ):
        raise SecurityFailure(
            401, "invalid_api_key", "A valid Bearer token is required."
        )
    return parts[1]


class ScopeAuthenticationMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        settings: Settings,
        api_key_provider: Callable[[], str | None],
        event_logger: SecurityEventLogger | None = None,
    ) -> None:
        self.app = app
        self.management_token = (
            settings.management_token.get_secret_value()
            if settings.management_token is not None
            else None
        )
        self.api_key_provider = api_key_provider
        self.event_logger = event_logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = request_id_for_scope(scope)
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        required_scope = _required_scope(scope.get("path", ""))
        if required_scope is None or _is_cors_preflight(scope):
            await self._call_with_request_id(scope, receive, send, request_id)
            return

        api_key = self._current_api_key()
        try:
            candidate = _parse_bearer(scope)
            principal = self._authenticate(
                candidate, required_scope, api_key=api_key
            )
        except SecurityFailure as exc:
            if self.event_logger is not None:
                self.event_logger.emit(
                    "authentication_failed",
                    {
                        "required_scope": required_scope,
                        "status_code": exc.status_code,
                        "code": exc.code,
                    },
                    request_id=request_id,
                    actor="public",
                )
            response = security_error_response(
                exc.status_code,
                exc.code,
                exc.safe_message,
                request_id,
                required_scope,
            )
            await response(scope, receive, send)
            return

        state["principal"] = principal
        await self._call_with_request_id(scope, receive, send, request_id)

    def _authenticate(
        self,
        candidate: str,
        required_scope: Literal["management", "api"],
        *,
        api_key: str | None,
    ) -> SecurityPrincipal:
        management_match = bool(
            self.management_token is not None
            and hmac.compare_digest(candidate, self.management_token)
        )
        api_match = bool(
            api_key is not None
            and hmac.compare_digest(candidate, api_key)
        )
        expected_match = (
            management_match if required_scope == "management" else api_match
        )
        other_match = api_match if required_scope == "management" else management_match
        if expected_match:
            return SecurityPrincipal(
                scope=required_scope,
                authenticated=True,
                subject=f"{required_scope}-token",
            )
        if other_match:
            scope_label = "API" if required_scope == "api" else "management"
            raise SecurityFailure(
                403,
                "insufficient_scope",
                f"The {scope_label} scope is required.",
            )
        raise SecurityFailure(
            401, "invalid_api_key", "A valid Bearer token is required."
        )

    def _current_api_key(self) -> str | None:
        return self.api_key_provider()

    async def _call_with_request_id(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        request_id: str,
    ) -> None:
        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers = [
                    item for item in headers if item[0].lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        principal = scope.get("state", {}).get("principal")
        actor = getattr(principal, "subject", "public")
        with bind_request_context(request_id, actor):
            await self.app(scope, receive, send_with_request_id)


def _split_quoted(value: str, delimiter: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    escaped = False
    for character in value:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\" and quoted:
            escaped = True
        elif character == '"':
            quoted = not quoted
            current.append(character)
        elif character == delimiter and not quoted:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if quoted or escaped:
        raise ProxyHeaderError("unterminated quoted value")
    parts.append("".join(current).strip())
    if any(not part for part in parts):
        raise ProxyHeaderError("empty forwarded element")
    return parts


def _unquote_forwarded(value: str) -> str:
    if value.startswith('"') or value.endswith('"'):
        if len(value) < 2 or not (value.startswith('"') and value.endswith('"')):
            raise ProxyHeaderError("malformed quoted value")
        value = value[1:-1]
    if any(ord(character) < 33 or ord(character) == 127 for character in value):
        raise ProxyHeaderError("control character in forwarded value")
    return value


def _parse_forwarded_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    value = _unquote_forwarded(value)
    if value.lower() == "unknown" or value.startswith("_"):
        raise ProxyHeaderError("obfuscated forwarded address is unsupported")
    host = value
    if value.startswith("["):
        closing = value.find("]")
        if closing < 0:
            raise ProxyHeaderError("invalid forwarded IPv6 address")
        host = value[1:closing]
        suffix = value[closing + 1 :]
        if suffix and (not suffix.startswith(":") or not suffix[1:].isdigit()):
            raise ProxyHeaderError("invalid forwarded port")
    elif value.count(":") == 1:
        possible_host, possible_port = value.rsplit(":", 1)
        if possible_port.isdigit():
            host = possible_host
    try:
        return ipaddress.ip_address(host)
    except ValueError as exc:
        raise ProxyHeaderError("forwarded address must be an IP literal") from exc


def _parse_forwarded_host(value: str) -> tuple[str, int | None, str]:
    value = _unquote_forwarded(value)
    if any(character in value for character in "/?#@"):
        raise ProxyHeaderError("invalid forwarded host")
    host = value
    port: int | None = None
    if value.startswith("["):
        closing = value.find("]")
        if closing < 0:
            raise ProxyHeaderError("invalid forwarded host")
        host = value[1:closing]
        suffix = value[closing + 1 :]
        if suffix:
            if not suffix.startswith(":") or not suffix[1:].isdigit():
                raise ProxyHeaderError("invalid forwarded host port")
            port = int(suffix[1:])
    elif value.count(":") == 1:
        host, port_text = value.rsplit(":", 1)
        if not port_text.isdigit():
            raise ProxyHeaderError("invalid forwarded host port")
        port = int(port_text)
    if not host or any(character.isspace() for character in host):
        raise ProxyHeaderError("invalid forwarded host")
    if port is not None and not 1 <= port <= 65535:
        raise ProxyHeaderError("invalid forwarded host port")
    return host.lower(), port, value.lower()


class TrustedProxyHeadersMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        trusted_proxy_cidrs: tuple[str, ...],
    ) -> None:
        self.app = app
        self.trusted_networks = tuple(
            ipaddress.ip_network(cidr) for cidr in trusted_proxy_cidrs
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header_names = [name.lower() for name, _ in scope.get("headers", [])]
        has_forwarding = any(
            name == b"forwarded"
            or name == b"x-real-ip"
            or name.startswith(b"x-forwarded-")
            for name in header_names
        )
        if not has_forwarding:
            await self.app(scope, receive, send)
            return

        request_id = request_id_for_scope(scope)
        try:
            prepared = self._prepare_scope(scope)
        except ProxyHeaderError:
            response = security_error_response(
                400,
                "invalid_proxy_headers",
                "Forwarding headers are invalid for this deployment.",
                request_id,
                _required_scope(scope.get("path", "")),
            )
            await response(scope, receive, send)
            return
        await self.app(prepared, receive, send)

    def _prepare_scope(self, scope: Scope) -> Scope:
        client = scope.get("client")
        try:
            peer = ipaddress.ip_address(client[0] if client else "")
        except ValueError as exc:
            raise ProxyHeaderError("direct peer is not an IP literal") from exc
        if not self._is_trusted(peer):
            raise ProxyHeaderError("forwarding headers came from an untrusted peer")

        names = [name.lower() for name, _ in scope.get("headers", [])]
        unknown_x = {
            name
            for name in names
            if name.startswith(b"x-forwarded-")
            and name not in _FORWARDED_HEADER_NAMES
        }
        if unknown_x or b"x-real-ip" in names:
            raise ProxyHeaderError("unsupported forwarding header")

        forwarded = _header_values(scope, b"forwarded")
        x_values = {
            name: _header_values(scope, name)
            for name in _FORWARDED_HEADER_NAMES
            if name != b"forwarded"
        }
        has_x = any(x_values.values())
        if forwarded and has_x:
            raise ProxyHeaderError("forwarded header families conflict")
        if len(forwarded) > 1 or any(len(values) > 1 for values in x_values.values()):
            raise ProxyHeaderError("duplicate forwarding header")

        if forwarded:
            chain, scheme, host = self._parse_forwarded(forwarded[0])
        elif has_x:
            chain, scheme, host = self._parse_x_forwarded(x_values)
        else:
            raise ProxyHeaderError("unsupported forwarding header")

        prepared = dict(scope)
        client_address = self._client_from_chain(chain)
        prepared["client"] = (str(client_address), 0)
        if scheme is not None:
            prepared["scheme"] = scheme
        if host is not None:
            hostname, port, serialized = host
            current_port = prepared.get("server", ("", 0))[1]
            prepared["server"] = (hostname, port or current_port)
            headers = [
                item for item in scope.get("headers", []) if item[0].lower() != b"host"
            ]
            headers.append((b"host", serialized.encode("ascii")))
            prepared["headers"] = headers
        return prepared

    def _parse_x_forwarded(
        self,
        values: dict[bytes, list[bytes]],
    ) -> tuple[
        list[ipaddress.IPv4Address | ipaddress.IPv6Address],
        str | None,
        tuple[str, int | None, str] | None,
    ]:
        for_values = values.get(b"x-forwarded-for", [])
        if len(for_values) != 1:
            raise ProxyHeaderError("x-forwarded-for is required")
        try:
            raw_chain = for_values[0].decode("ascii")
        except UnicodeDecodeError as exc:
            raise ProxyHeaderError("invalid x-forwarded-for encoding") from exc
        chain = [
            _parse_forwarded_address(item)
            for item in _split_quoted(raw_chain, ",")
        ]
        scheme = self._single_scheme(values.get(b"x-forwarded-proto", []))
        host = self._single_host(values.get(b"x-forwarded-host", []))
        return chain, scheme, host

    def _parse_forwarded(
        self,
        raw: bytes,
    ) -> tuple[
        list[ipaddress.IPv4Address | ipaddress.IPv6Address],
        str | None,
        tuple[str, int | None, str] | None,
    ]:
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ProxyHeaderError("invalid forwarded encoding") from exc
        chain: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        schemes: list[str] = []
        hosts: list[tuple[str, int | None, str]] = []
        for element in _split_quoted(text, ","):
            parameters: dict[str, str] = {}
            for parameter in _split_quoted(element, ";"):
                if "=" not in parameter:
                    raise ProxyHeaderError("malformed forwarded parameter")
                key, value = parameter.split("=", 1)
                key = key.strip().lower()
                value = value.strip()
                if key not in {"for", "by", "proto", "host"} or key in parameters:
                    raise ProxyHeaderError("unknown or duplicate forwarded parameter")
                parameters[key] = value
            if "for" not in parameters:
                raise ProxyHeaderError("forwarded for parameter is required")
            chain.append(_parse_forwarded_address(parameters["for"]))
            if "proto" in parameters:
                schemes.append(self._validate_scheme(parameters["proto"]))
            if "host" in parameters:
                hosts.append(_parse_forwarded_host(parameters["host"]))
        if schemes and len(set(schemes)) != 1:
            raise ProxyHeaderError("conflicting forwarded proto values")
        if hosts and len({item[2] for item in hosts}) != 1:
            raise ProxyHeaderError("conflicting forwarded host values")
        return chain, schemes[0] if schemes else None, hosts[0] if hosts else None

    @staticmethod
    def _validate_scheme(value: str) -> str:
        scheme = _unquote_forwarded(value).lower()
        if scheme not in {"http", "https"}:
            raise ProxyHeaderError("unsupported forwarded scheme")
        return scheme

    def _single_scheme(self, values: list[bytes]) -> str | None:
        if not values:
            return None
        try:
            text = values[0].decode("ascii")
        except UnicodeDecodeError as exc:
            raise ProxyHeaderError("invalid forwarded scheme encoding") from exc
        if "," in text:
            raise ProxyHeaderError("multiple forwarded scheme values")
        return self._validate_scheme(text.strip())

    @staticmethod
    def _single_host(
        values: list[bytes],
    ) -> tuple[str, int | None, str] | None:
        if not values:
            return None
        try:
            text = values[0].decode("ascii")
        except UnicodeDecodeError as exc:
            raise ProxyHeaderError("invalid forwarded host encoding") from exc
        if "," in text:
            raise ProxyHeaderError("multiple forwarded host values")
        return _parse_forwarded_host(text.strip())

    def _client_from_chain(
        self,
        chain: list[ipaddress.IPv4Address | ipaddress.IPv6Address],
    ) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        if not chain:
            raise ProxyHeaderError("empty forwarding chain")
        for address in reversed(chain):
            if not self._is_trusted(address):
                return address
        return chain[0]

    def _is_trusted(
        self, address: ipaddress.IPv4Address | ipaddress.IPv6Address
    ) -> bool:
        return any(address in network for network in self.trusted_networks)
