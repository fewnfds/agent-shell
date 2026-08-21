from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable


def make_model_request_settings_middleware(
    *,
    tool_choice: object,
    model_settings: dict[str, object],
) -> Any:
    """Apply one Model block's request-time bind settings."""

    from langchain.agents.middleware import AgentMiddleware

    class ModelRequestSettingsMiddleware(AgentMiddleware):
        @staticmethod
        def _prepare(request: Any) -> Any:
            overrides: dict[str, object] = {}
            if tool_choice is not None:
                overrides["tool_choice"] = deepcopy(tool_choice)
            if model_settings:
                overrides["model_settings"] = {
                    **(request.model_settings or {}),
                    **deepcopy(model_settings),
                }
            return request.override(**overrides)

        def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
            return handler(self._prepare(request))

        async def awrap_model_call(
            self, request: Any, handler: Callable[[Any], Any]
        ) -> Any:
            return await handler(self._prepare(request))

    return ModelRequestSettingsMiddleware()
