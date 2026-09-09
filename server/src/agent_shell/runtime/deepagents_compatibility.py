from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse


class EmptySystemMessageMiddleware(AgentMiddleware):
    """Omit Deep Agents' empty authored system message from provider requests."""

    @staticmethod
    def _prepare(request: ModelRequest) -> ModelRequest:
        system_message = request.system_message
        if system_message is not None and system_message.content == "":
            return request.override(system_message=None)
        return request

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._prepare(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._prepare(request))
