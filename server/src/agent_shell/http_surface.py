from __future__ import annotations

from typing import TypedDict
from urllib.parse import quote

from fastapi import APIRouter, Request


ADMIN_PATH = "/admin"
AGENT_SHELL_API_PREFIX = "/agent-shell/api"
COMPAT_API_PREFIX = "/compat"
OPENAI_COMPAT_API_PREFIX = f"{COMPAT_API_PREFIX}/openai/v1"

MANAGEMENT_BEARER_SCHEME = "ManagementBearer"
API_KEY_BEARER_SCHEME = "ApiKeyBearer"

LANGGRAPH_ROUTE_FAMILIES = (
    "/assistants/*",
    "/threads/*",
    "/runs/*",
    "/store/*",
    "/mcp/",
    "/a2a/{assistant_id}",
)


class ServiceEntries(TypedDict):
    management_console_url: str
    agent_server_base_url: str
    api_docs_url: str
    openapi_schema_url: str
    langgraph_studio_url: str


class ApiEndpoints(TypedDict):
    agent_shell_base_url: str
    openai_base_url: str
    models_endpoint: str
    chat_completions_endpoint: str
    langgraph_route_families: tuple[str, ...]
    agent_shell_health_endpoint: str
    agent_shell_readiness_endpoint: str
    langgraph_health_endpoint: str
    langgraph_info_endpoint: str
    langgraph_metrics_endpoint: str


class HttpSurface(TypedDict):
    service_entries: ServiceEntries
    api_endpoints: ApiEndpoints


def management_api_router() -> APIRouter:
    return APIRouter(prefix=AGENT_SHELL_API_PREFIX)


def openai_compat_api_router() -> APIRouter:
    return APIRouter(prefix=OPENAI_COMPAT_API_PREFIX)


def is_agent_shell_api_path(path: str) -> bool:
    return path == AGENT_SHELL_API_PREFIX or path.startswith(
        f"{AGENT_SHELL_API_PREFIX}/"
    )


def is_compat_api_path(path: str) -> bool:
    return path == COMPAT_API_PREFIX or path.startswith(f"{COMPAT_API_PREFIX}/")


def request_origin(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _absolute(origin: str, path: str) -> str:
    return f"{origin}{path}"


def http_surface(request: Request) -> HttpSurface:
    origin = request_origin(request)
    return {
        "service_entries": {
            "management_console_url": f"{_absolute(origin, ADMIN_PATH)}#/",
            "agent_server_base_url": origin,
            "api_docs_url": _absolute(origin, "/docs"),
            "openapi_schema_url": _absolute(origin, "/openapi.json"),
            "langgraph_studio_url": (
                "https://smith.langchain.com/studio/"
                f"?baseUrl={quote(origin, safe='')}"
            ),
        },
        "api_endpoints": {
            "agent_shell_base_url": _absolute(origin, AGENT_SHELL_API_PREFIX),
            "openai_base_url": _absolute(origin, OPENAI_COMPAT_API_PREFIX),
            "models_endpoint": _absolute(
                origin, f"{OPENAI_COMPAT_API_PREFIX}/models"
            ),
            "chat_completions_endpoint": _absolute(
                origin, f"{OPENAI_COMPAT_API_PREFIX}/chat/completions"
            ),
            "langgraph_route_families": LANGGRAPH_ROUTE_FAMILIES,
            "agent_shell_health_endpoint": _absolute(
                origin, f"{AGENT_SHELL_API_PREFIX}/health"
            ),
            "agent_shell_readiness_endpoint": _absolute(
                origin, f"{AGENT_SHELL_API_PREFIX}/readiness"
            ),
            "langgraph_health_endpoint": _absolute(origin, "/ok"),
            "langgraph_info_endpoint": _absolute(origin, "/info"),
            "langgraph_metrics_endpoint": _absolute(origin, "/metrics"),
        },
    }


__all__ = [
    "ADMIN_PATH",
    "AGENT_SHELL_API_PREFIX",
    "API_KEY_BEARER_SCHEME",
    "COMPAT_API_PREFIX",
    "MANAGEMENT_BEARER_SCHEME",
    "OPENAI_COMPAT_API_PREFIX",
    "http_surface",
    "is_agent_shell_api_path",
    "is_compat_api_path",
    "management_api_router",
    "openai_compat_api_router",
    "request_origin",
]
