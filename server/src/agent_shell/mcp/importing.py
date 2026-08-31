from __future__ import annotations

from copy import deepcopy
import json
from pathlib import PurePath
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from agent_shell.storage.mcp_connections import MCP_CONNECTION_ADAPTER


_ENV_REFERENCE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")
_NPM_RECIPE = re.compile(
    r"^(?P<package>(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*)@"
    r"(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?(?:\+[0-9A-Za-z][0-9A-Za-z.-]*)?)$"
)
_PYPI_RECIPE = re.compile(
    r"^(?P<package>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)=="
    r"(?P<version>[^=<>!~\s]+)$"
)
McpImportedValueSource = Literal["literal", "secret"]


class McpImportValueSources(BaseModel):
    model_config = ConfigDict(extra="forbid")

    env: dict[str, McpImportedValueSource] = Field(default_factory=dict)
    headers: dict[str, McpImportedValueSource] = Field(default_factory=dict)


MCP_IMPORT_VALUE_SOURCES_ADAPTER = TypeAdapter(
    dict[str, McpImportValueSources]
)


def _document(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("MCP import document is not valid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"mcpServers"}:
        raise ValueError("MCP import document must contain only mcpServers")
    servers = value.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        raise ValueError("mcpServers must be a non-empty object")
    return value


def _string_map(value: object, *, label: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or any(
        not isinstance(name, str) or not isinstance(item, str)
        for name, item in value.items()
    ):
        raise ValueError(f"{label} must be an object of string values")
    unresolved = sorted(
        name for name, item in value.items() if _ENV_REFERENCE.fullmatch(item)
    )
    if unresolved:
        raise ValueError(
            f"{label} contains unresolved environment references: "
            + ", ".join(unresolved)
        )
    return dict(value)


def _transport(server: dict[str, Any]) -> str:
    declared_type = server.get("type")
    declared_transport = server.get("transport")
    declared = [
        value
        for value in (declared_type, declared_transport)
        if value is not None
    ]
    if not declared:
        declared = ["http" if "url" in server else "stdio"]

    normalized_values: list[str] = []
    for raw in declared:
        if not isinstance(raw, str):
            raise ValueError("MCP import transport must be a string")
        normalized = raw.strip().lower().replace("-", "_")
        if normalized in {"http", "streamable_http"}:
            normalized_values.append("http")
        elif normalized == "stdio":
            normalized_values.append("stdio")
        else:
            raise ValueError(f"MCP import transport is unsupported: {raw}")
    if len(set(normalized_values)) != 1:
        raise ValueError("MCP import type and transport disagree")
    return normalized_values[0]


def _managed_package_recipe(
    server_name: str,
    command: str,
    args: list[str],
) -> tuple[str, str, str, str | None, list[str]]:
    executable = PurePath(command.strip()).name.casefold()
    if executable in {"npx", "npx.cmd", "npx.exe"}:
        remaining = list(args)
        if remaining and remaining[0] in {"-y", "--yes"}:
            remaining.pop(0)
        if not remaining:
            raise ValueError(f"MCP npx server {server_name!r} requires an exact package recipe")
        matched = _NPM_RECIPE.fullmatch(remaining.pop(0))
        if matched is None:
            raise ValueError(
                f"MCP npx server {server_name!r} requires package@exact-version"
            )
        return (
            "npm",
            matched.group("package"),
            matched.group("version"),
            None,
            remaining,
        )
    if executable in {"uvx", "uvx.exe"}:
        remaining = list(args)
        entrypoint: str | None = None
        if len(remaining) >= 3 and remaining[0] == "--from":
            recipe = remaining[1]
            entrypoint = remaining[2]
            remaining = remaining[3:]
        elif remaining:
            recipe = remaining.pop(0)
        else:
            raise ValueError(f"MCP uvx server {server_name!r} requires an exact package recipe")
        matched = _PYPI_RECIPE.fullmatch(recipe)
        if matched is None:
            raise ValueError(
                f"MCP uvx server {server_name!r} requires package==exact-version"
            )
        return (
            "pypi",
            matched.group("package"),
            matched.group("version"),
            entrypoint,
            remaining,
        )
    raise ValueError(
        f"MCP stdio server {server_name!r} is not a supported managed npx or uvx recipe"
    )


def normalize_mcp_servers_import(
    document: object,
    *,
    value_sources: object | None = None,
) -> list[dict[str, Any]]:
    """Translate the common mcpServers JSON shape into Connection inputs."""

    parsed = _document(document)
    source_overrides = MCP_IMPORT_VALUE_SOURCES_ADAPTER.validate_python(
        value_sources or {}
    )
    normalized: list[dict[str, Any]] = []
    for server_name, raw_server in parsed["mcpServers"].items():
        if not isinstance(server_name, str) or not server_name.strip():
            raise ValueError("MCP server names must be non-empty strings")
        if not isinstance(raw_server, dict):
            raise ValueError(f"MCP server {server_name!r} must be an object")
        server = deepcopy(raw_server)
        transport = _transport(server)
        allowed = (
            {"type", "transport", "command", "args", "env", "cwd", "enabled"}
            if transport == "stdio"
            else {"type", "transport", "url", "headers", "enabled"}
        )
        unknown = sorted(set(server).difference(allowed))
        if unknown:
            raise ValueError(
                f"MCP server {server_name!r} contains unsupported fields: "
                + ", ".join(unknown)
            )
        overrides = source_overrides.get(server_name, McpImportValueSources())
        if transport == "stdio":
            command = server.get("command")
            args = server.get("args", [])
            if not isinstance(command, str) or not command.strip():
                raise ValueError(f"MCP stdio server {server_name!r} requires command")
            if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
                raise ValueError(f"MCP stdio server {server_name!r} args must be strings")
            package_source, package, version, entrypoint, runtime_args = (
                _managed_package_recipe(server_name, command, args)
            )
            env = _string_map(server.get("env"), label=f"MCP server {server_name!r} env")
            unexpected = sorted(set(overrides.headers) | (set(overrides.env) - set(env)))
            if unexpected:
                raise ValueError(
                    f"MCP import value source targets do not exist for {server_name!r}: "
                    + ", ".join(unexpected)
                )
            candidate: dict[str, Any] = {
                "name": server_name.strip(),
                "transport": "stdio",
                "package_source": package_source,
                "package": package,
                "version": version,
                "entrypoint": entrypoint,
                "args": runtime_args,
                "env": {
                    name: {
                        "source": overrides.env.get(name, "secret"),
                        "value": value,
                    }
                    for name, value in env.items()
                },
            }
            if server.get("cwd") is not None:
                candidate["cwd"] = server["cwd"]
        else:
            url = server.get("url")
            if not isinstance(url, str) or not url.strip():
                raise ValueError(f"MCP HTTP server {server_name!r} requires url")
            headers = _string_map(
                server.get("headers"),
                label=f"MCP server {server_name!r} headers",
            )
            unexpected = sorted(set(overrides.env) | (set(overrides.headers) - set(headers)))
            if unexpected:
                raise ValueError(
                    f"MCP import value source targets do not exist for {server_name!r}: "
                    + ", ".join(unexpected)
                )
            candidate = {
                "name": server_name.strip(),
                "transport": "http",
                "url": url,
                "headers": {
                    name: {
                        "source": overrides.headers.get(name, "secret"),
                        "value": value,
                    }
                    for name, value in headers.items()
                },
            }
        normalized.append(
            MCP_CONNECTION_ADAPTER.validate_python(candidate).model_dump(
                mode="json",
                exclude_none=True,
            )
        )
    return normalized


def mcp_import_preview(document: object) -> dict[str, Any]:
    connections = normalize_mcp_servers_import(document)
    previews: list[dict[str, Any]] = []
    for connection in connections:
        field = "env" if connection["transport"] == "stdio" else "headers"
        previews.append(
            {
                "name": connection["name"],
                "transport": connection["transport"],
                **(
                    {"package_source": connection["package_source"]}
                    if connection["transport"] == "stdio"
                    else {}
                ),
                "values": [
                    {"target": field, "name": name, "source": configured["source"]}
                    for name, configured in connection.get(field, {}).items()
                ],
            }
        )
    return {"connections": previews}


__all__ = ["mcp_import_preview", "normalize_mcp_servers_import"]
