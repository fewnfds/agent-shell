from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent_shell.runtime.context import AgentRuntimeContext


def _load_example() -> ModuleType:
    source = (
        Path(__file__).parents[2]
        / "examples"
        / "agent-components"
        / "custom-middleware"
        / "agent-additional-prompt"
        / "main.py"
    )
    spec = importlib.util.spec_from_file_location("agent_additional_prompt_example", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_additional_prompt_example_initializes_one_agent_thread_once() -> None:
    module = _load_example()
    middleware = module.create_middleware(
        backend=object(),
        scope="main_agent",
        package_id="example-id",
    )
    context = AgentRuntimeContext(
        request_id="request-id",
        lifecycle_id="lifecycle-id",
        run_id="run-id",
        main_agent_id="agent-id",
    )

    update = asyncio.run(
        middleware.abefore_agent(
            {"messages": [HumanMessage(content="request")]},
            SimpleNamespace(context=context, store=None),
        )
    )

    assert middleware.name == "AgentAdditionalPromptMiddleware_example-id"
    prepared = update["messages"].value
    assert [(message.type, message.content) for message in prepared] == [
        ("human", "request"),
    ]
    marker = next(key for key in update if key.startswith("_agent_shell_aap_"))
    assert update[marker] is True
    assert asyncio.run(
        middleware.abefore_agent(
            {"messages": prepared, marker: True},
            SimpleNamespace(context=context, store=None),
        )
    ) is None


def test_agent_additional_prompt_marker_and_messages_continue_on_same_thread() -> None:
    module = _load_example()
    middleware = module.create_middleware(
        backend=object(),
        scope="main_agent",
        package_id="threaded-example",
    )
    graph = create_agent(
        model=FakeListChatModel(responses=["first reply", "second reply"]),
        middleware=[middleware],
        checkpointer=InMemorySaver(),
        context_schema=AgentRuntimeContext,
    )

    async def scenario() -> tuple[list[str], dict[str, object]]:
        config = {"configurable": {"thread_id": "same-agent-thread"}}
        await graph.ainvoke(
            {"messages": [{"role": "user", "content": "first request"}]},
            config=config,
            context=AgentRuntimeContext(main_agent_id="agent-id"),
        )
        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": "second request"}]},
            config=config,
            context=AgentRuntimeContext(main_agent_id="agent-id"),
        )
        state = await graph.aget_state(config)
        return [message.content for message in result["messages"]], state.values

    messages, state = asyncio.run(scenario())

    assert messages == [
        "first request",
        "first reply",
        "second request",
        "second reply",
    ]
    assert state["_agent_shell_aap_threaded_example_initialized"] is True
