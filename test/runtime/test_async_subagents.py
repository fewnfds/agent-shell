from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field


class ToolCallingModel(FakeMessagesListChatModel):
    bound_tool_names: set[str] = Field(default_factory=set)

    def bind_tools(self, tools, **kwargs):
        self.bound_tool_names.update(tool.name for tool in tools)
        return self.bind(**kwargs)


class FakeThreads:
    async def create(self):
        return {"thread_id": "async-thread-1"}

    async def get(self, *, thread_id: str):
        assert thread_id == "async-thread-1"
        return {
            "thread_id": thread_id,
            "values": {
                "messages": [
                    {"role": "assistant", "content": "background result"}
                ]
            },
        }


class FakeRuns:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.cancelled: list[tuple[str, str]] = []

    async def create(self, *, thread_id: str, assistant_id: str, **kwargs):
        self.created.append(
            {
                "thread_id": thread_id,
                "assistant_id": assistant_id,
                **kwargs,
            }
        )
        return {"run_id": f"async-run-{len(self.created)}"}

    async def get(self, *, thread_id: str, run_id: str):
        assert thread_id == "async-thread-1"
        return {
            "run_id": run_id,
            "status": "success" if run_id == "async-run-1" else "running",
        }

    async def cancel(self, *, thread_id: str, run_id: str):
        self.cancelled.append((thread_id, run_id))


def tool_call(name: str, args: dict[str, object], index: int) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": args,
                "id": f"call-{index}",
                "type": "tool_call",
            }
        ],
    )


def test_official_async_subagent_tools_use_one_child_thread_and_persist_parent_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = FakeRuns()
    client = SimpleNamespace(threads=FakeThreads(), runs=runs)
    monkeypatch.setattr(
        "deepagents.middleware.async_subagents.get_client",
        lambda **_kwargs: client,
    )
    model = ToolCallingModel(
        responses=[
            tool_call(
                "start_async_task",
                {
                    "description": "Research the request.",
                    "subagent_type": "researcher",
                },
                1,
            ),
            AIMessage(content="started"),
            tool_call(
                "check_async_task",
                {"task_id": "async-thread-1"},
                2,
            ),
            AIMessage(content="checked"),
            tool_call(
                "update_async_task",
                {
                    "task_id": "async-thread-1",
                    "message": "Also compare alternatives.",
                },
                3,
            ),
            AIMessage(content="updated"),
            tool_call("list_async_tasks", {}, 4),
            AIMessage(content="listed"),
            tool_call(
                "cancel_async_task",
                {"task_id": "async-thread-1"},
                5,
            ),
            AIMessage(content="cancelled"),
        ]
    )
    graph = create_deep_agent(
        model=model,
        subagents=[
            {
                "name": "researcher",
                "description": "Research in the background.",
                "graph_id": "stable-target-assistant",
            }
        ],
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "supervisor-thread"}}

    async def run() -> dict:
        result: dict = {}
        for request in ("start", "check", "update", "list", "cancel"):
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content=request)]},
                config,
            )
        return result

    result = asyncio.run(run())

    assert {
        "start_async_task",
        "check_async_task",
        "update_async_task",
        "cancel_async_task",
        "list_async_tasks",
    }.issubset(model.bound_tool_names)
    assert runs.created == [
        {
            "thread_id": "async-thread-1",
            "assistant_id": "stable-target-assistant",
            "input": {
                "messages": [
                    {"role": "user", "content": "Research the request."}
                ]
            },
        },
        {
            "thread_id": "async-thread-1",
            "assistant_id": "stable-target-assistant",
            "input": {
                "messages": [
                    {"role": "user", "content": "Also compare alternatives."}
                ]
            },
            "multitask_strategy": "interrupt",
        },
    ]
    assert runs.cancelled == [("async-thread-1", "async-run-2")]
    assert result["async_tasks"]["async-thread-1"]["status"] == "cancelled"
    tool_messages = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    assert any("background result" in str(message.content) for message in tool_messages)
    assert any("1 tracked task(s)" in str(message.content) for message in tool_messages)
