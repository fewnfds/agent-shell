from __future__ import annotations

import asyncio
from typing import ClassVar

from deepagents import create_deep_agent
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent_shell.runtime.deepagents_compatibility import EmptySystemMessageMiddleware


class _CaptureModel(BaseChatModel):
    captured_messages: ClassVar[list[list[tuple[str, object]]]] = []

    @property
    def _llm_type(self) -> str:
        return "agent-shell-capture"

    def bind_tools(self, _tools, **_kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        del stop, run_manager, kwargs
        type(self).captured_messages.append(
            [(message.type, message.content) for message in messages]
        )
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="done"))]
        )


def test_deep_agent_without_authored_prompt_omits_empty_system_message() -> None:
    _CaptureModel.captured_messages.clear()
    agent = create_deep_agent(
        model=_CaptureModel(),
        middleware=[EmptySystemMessageMiddleware()],
    )

    agent.invoke({"messages": [{"role": "user", "content": "hello"}]})

    assert _CaptureModel.captured_messages == [[("human", "hello")]]


def test_nonempty_system_message_is_preserved() -> None:
    _CaptureModel.captured_messages.clear()
    agent = create_deep_agent(
        model=_CaptureModel(),
        system_prompt="Use the configured instructions.",
        middleware=[EmptySystemMessageMiddleware()],
    )

    agent.invoke({"messages": [{"role": "user", "content": "hello"}]})

    assert _CaptureModel.captured_messages == [
        [
            ("system", "Use the configured instructions."),
            ("human", "hello"),
        ]
    ]


def test_empty_system_message_is_omitted_on_async_model_calls() -> None:
    middleware = EmptySystemMessageMiddleware()
    request = ModelRequest(
        model=_CaptureModel(),
        messages=[],
        system_message=SystemMessage(content=""),
    )
    response = ModelResponse(result=[AIMessage(content="done")])
    captured: list[ModelRequest] = []

    async def handler(prepared: ModelRequest) -> ModelResponse:
        captured.append(prepared)
        return response

    returned = asyncio.run(middleware.awrap_model_call(request, handler))

    assert returned is response
    assert captured[0].system_message is None
