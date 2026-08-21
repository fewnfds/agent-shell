from __future__ import annotations

from importlib.util import find_spec
from typing import Iterable

from agent_shell.settings import Settings
from agent_shell.storage.permissions import PermissionStatus


_DEPENDENCIES = {
    "langchain": "langchain",
    "anthropic_provider": "langchain_anthropic",
    "deepseek_provider": "langchain_deepseek",
    "google_genai_provider": "langchain_google_genai",
    "google_vertexai_provider": "langchain_google_vertexai",
    "openai_provider": "langchain_openai",
    "xai_provider": "langchain_xai",
    "deepagents": "deepagents",
}


def _module_available(module: str) -> bool:
    try:
        return find_spec(module) is not None
    except (ImportError, AttributeError, ValueError):
        return False


class ReadinessService:
    def __init__(
        self,
        *,
        settings: Settings,
        startup_permission_statuses: Iterable[PermissionStatus],
    ) -> None:
        self._settings = settings
        self._startup_permissions = tuple(startup_permission_statuses)

    def snapshot(self) -> dict[str, object]:
        permissions = [
            {
                "path_kind": item.path_kind,
                "enforced": item.enforced,
                "mechanism": item.mechanism,
                "boundary": item.boundary,
            }
            for item in self._startup_permissions
        ]
        startup_permissions_confirmed = bool(permissions) and all(
            item["enforced"] for item in permissions
        )
        dependencies = {
            key: {
                "status": "available" if _module_available(module) else "unavailable",
                "module": module,
            }
            for key, module in _DEPENDENCIES.items()
        }
        runtime_ready = all(
            dependency["status"] == "available"
            for dependency in dependencies.values()
        )
        return {
            "status": (
                "configuration_ready"
                if startup_permissions_confirmed
                else "configuration_unavailable"
            ),
            "sections": {
                "security_settings": {
                    "status": "ready",
                    "deployment_mode": self._settings.deployment_mode,
                    "authentication": "required",
                    "cors": "configured" if self._settings.cors_origins else "disabled",
                    "trusted_proxy": (
                        "configured"
                        if self._settings.trusted_proxy_cidrs
                        else "disabled"
                    ),
                },
                "storage": {
                    "status": (
                        "startup_permissions_confirmed"
                        if startup_permissions_confirmed
                        else "startup_permissions_unconfirmed"
                    ),
                    "permissions": permissions,
                },
                "runtime_dependencies": {
                    "status": "ready" if runtime_ready else "unavailable",
                    "dependencies": dependencies,
                    "code": (
                        "model_streaming"
                        if runtime_ready
                        else "runtime_dependency_missing"
                    ),
                },
            },
        }
