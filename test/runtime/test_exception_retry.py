from __future__ import annotations

import httpx
import pytest
from deepagents import create_deep_agent
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from agent_shell.runtime.capabilities.exception_retry import (
    materialize_exception_retry,
    model_block_with_retry_overrides,
)
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.limits import ProviderErrorBoundaryMiddleware


class BoundFakeModel(FakeMessagesListChatModel):
    calls: int = 0
    seen_tool_choices: list[object] = []
    seen_bind_kwargs: list[dict] = []

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        self.seen_tool_choices.append(tool_choice)
        self.seen_bind_kwargs.append(dict(kwargs))
        return self.bind(**kwargs)

    def _generate(self, *args, **kwargs):
        self.calls += 1
        return super()._generate(*args, **kwargs)


class TransientOnceModel(BoundFakeModel):
    def _generate(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise httpx.ConnectError("transient test failure")
        return FakeMessagesListChatModel._generate(self, *args, **kwargs)


class AuthenticationFailure(Exception):
    status_code = 401


class AuthenticationOnceModel(BoundFakeModel):
    def _generate(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise AuthenticationFailure("test authentication failure")
        return FakeMessagesListChatModel._generate(self, *args, **kwargs)


def capability(**updates) -> dict:
    return {
        "strategy": "model_retry_middleware",
        "force_non_streaming": False,
        "max_retries": 1,
        "retry_on": [
            "transport_error",
            "timeout",
            "rate_limit",
            "server_error",
        ],
        **updates,
    }


def graph_with_retry(model, configuration: dict, *, tools=()):
    runtime = materialize_exception_retry(configuration)
    return create_agent(
        model=model,
        tools=list(tools),
        middleware=[
            ProviderErrorBoundaryMiddleware(),
            *runtime.after_provider_boundary,
        ],
    )


def test_retry_owner_overrides_current_provider_parameter_names() -> None:
    base = {
        "provider": "openai",
        "provider_settings": {"streaming": True, "max_retries": 4},
        "model_settings": {"parallel_tool_calls": True},
    }
    provider_native = model_block_with_retry_overrides(
        base,
        capability(
            strategy="provider_native",
            force_non_streaming=True,
            max_retries=3,
        ),
    )
    middleware = model_block_with_retry_overrides(base, capability())
    google = model_block_with_retry_overrides(
        {
            **base,
            "provider": "google_genai",
            "provider_settings": {"streaming": True, "retries": 4},
        },
        capability(strategy="provider_native", max_retries=6),
    )

    assert provider_native["provider_settings"] == {
        "streaming": False,
        "max_retries": 3,
    }
    assert provider_native["model_settings"] == {"parallel_tool_calls": True}
    assert middleware["provider_settings"]["max_retries"] == 0
    assert google["provider_settings"]["retries"] == 6
    assert "max_retries" not in google["provider_settings"]
    assert materialize_exception_retry(
        capability(strategy="provider_native")
    ).after_provider_boundary == ()


def test_official_model_retry_handles_transient_provider_failure() -> None:
    model = TransientOnceModel(responses=[AIMessage(content="done")])
    graph = graph_with_retry(model, capability())

    output = graph.invoke({"messages": [HumanMessage("answer")]})

    assert model.calls == 2
    assert output["messages"][-1].text == "done"


def test_deep_agent_uses_official_model_retry_middleware() -> None:
    model = TransientOnceModel(responses=[AIMessage(content="done")])
    runtime = materialize_exception_retry(capability())
    graph = create_deep_agent(
        model=model,
        middleware=[
            ProviderErrorBoundaryMiddleware(),
            *runtime.after_provider_boundary,
        ],
        name="retry_integration",
    )

    output = graph.invoke({"messages": [HumanMessage("answer")]})

    assert model.calls == 2
    assert output["messages"][-1].text == "done"


def test_authentication_retry_is_explicit_and_off_by_default() -> None:
    default_model = AuthenticationOnceModel(responses=[AIMessage(content="done")])
    default_graph = graph_with_retry(default_model, capability())

    with pytest.raises(AgentRuntimeError, match="provider_request_failed"):
        default_graph.invoke({"messages": [HumanMessage("answer")]})

    opted_in_model = AuthenticationOnceModel(responses=[AIMessage(content="done")])
    opted_in_graph = graph_with_retry(
        opted_in_model,
        capability(
            retry_on=[
                "transport_error",
                "timeout",
                "rate_limit",
                "server_error",
                "authentication_error",
            ]
        ),
    )
    output = opted_in_graph.invoke({"messages": [HumanMessage("answer")]})

    assert default_model.calls == 1
    assert opted_in_model.calls == 2
    assert output["messages"][-1].text == "done"


def test_middleware_preserves_normal_text_and_parallel_tool_calls() -> None:
    @tool
    def echo(value: str) -> str:
        """Return a test value."""

        return value

    model = BoundFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "echo",
                        "args": {"value": "one"},
                        "id": "echo-1",
                        "type": "tool_call",
                    },
                    {
                        "name": "echo",
                        "args": {"value": "two"},
                        "id": "echo-2",
                        "type": "tool_call",
                    },
                ],
            ),
            AIMessage(content="complete"),
        ]
    )
    graph = graph_with_retry(model, capability(), tools=[echo])

    output = graph.invoke({"messages": [HumanMessage("use tools")]})

    tool_results = [
        message.content
        for message in output["messages"]
        if isinstance(message, ToolMessage)
    ]
    assert tool_results == ["one", "two"]
    assert output["messages"][-1].text == "complete"
    assert model.calls == 2
    assert model.seen_tool_choices == [None, None]
    assert all("parallel_tool_calls" not in item for item in model.seen_bind_kwargs)
