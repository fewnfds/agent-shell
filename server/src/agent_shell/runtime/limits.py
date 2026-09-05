from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain.agents.middleware.types import ModelRequest, ModelResponse

from agent_shell.runtime.errors import AgentRuntimeError


def _provider_error(exc: Exception) -> AgentRuntimeError:
    status_code = 502
    current: BaseException | None = exc
    for _depth in range(6):
        if current is None:
            break
        status = getattr(current, "status_code", None)
        if not isinstance(status, int):
            status = getattr(getattr(current, "response", None), "status_code", None)
        if isinstance(status, int) and 400 <= status <= 599:
            status_code = status
            break
        current = current.__cause__ or current.__context__
    return AgentRuntimeError(
        "provider_request_failed",
        "The model provider request failed.",
        status_code=status_code,
    )


class ToolErrorBoundaryMiddleware(AgentMiddleware):
    """Classify exceptions from the selected tool without changing its result."""

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        try:
            return handler(request)
        except AgentRuntimeError:
            raise
        except Exception as exc:
            raise AgentRuntimeError(
                "tool_execution_failed",
                "A selected tool failed during execution.",
                status_code=502,
            ) from exc

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        try:
            return await handler(request)
        except AgentRuntimeError:
            raise
        except Exception as exc:
            raise AgentRuntimeError(
                "tool_execution_failed",
                "A selected tool failed during execution.",
                status_code=502,
            ) from exc


class ProviderErrorBoundaryMiddleware(AgentMiddleware):
    """Classify exceptions from the innermost model/provider call only."""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        try:
            return handler(request)
        except AgentRuntimeError:
            raise
        except Exception as exc:
            raise _provider_error(exc) from exc

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        try:
            return await handler(request)
        except AgentRuntimeError:
            raise
        except Exception as exc:
            raise _provider_error(exc) from exc
