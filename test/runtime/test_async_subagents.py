from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain.agents.middleware.types import ToolCallRequest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import ExecutionInfo
from langgraph.types import Command
from langchain.tools import ToolRuntime
from pydantic import Field

from agent_shell.runtime.subagent_middleware import (
    AsyncSubagentRunMiddleware,
    AsyncSubagentRunTarget,
)


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


def _tool_request(name: str) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": {}, "id": "call-1", "type": "tool_call"},
        tool=None,
        state={"messages": []},
        runtime=ToolRuntime(
            state={"messages": []},
            context=None,
            config={},
            stream_writer=lambda _value: None,
            tool_call_id="call-1",
            store=None,
            execution_info=ExecutionInfo(
                checkpoint_id="checkpoint-1",
                checkpoint_ns="",
                task_id="task-1",
                thread_id="parent-thread",
                run_id="parent-run",
            ),
        ),
    )


def test_async_run_middleware_records_public_command_causality() -> None:
    class Observer:
        def __init__(self) -> None:
            self.events: list[tuple[str, object]] = []

        def begin_async_subagent_call(self, parent_run_id: str) -> None:
            self.events.append(("begin", parent_run_id))

        def end_async_subagent_call(self, parent_run_id: str) -> None:
            self.events.append(("end", parent_run_id))

        async def record_async_subagent_run(self, **kwargs) -> None:
            self.events.append(("record", kwargs))

        def detach_async_subagent_observation(self, *_args, **_kwargs) -> None:
            raise AssertionError("the completed handler must not detach")

    async def scenario() -> Observer:
        observer = Observer()
        target = AsyncSubagentRunTarget(
            async_subagent_id="profile-1",
            main_agent_id="agent-1",
            main_agent_name="Research Agent",
            on_disconnect="cancel",
        )
        middleware = AsyncSubagentRunMiddleware(
            targets={"researcher": target},
            observer=observer,
        )

        async def handler(_request):
            return Command(
                update={
                    "async_tasks": {
                        "child-thread": {
                            "agent_name": "researcher",
                            "thread_id": "child-thread",
                            "run_id": "child-run",
                        }
                    }
                }
            )

        result = await middleware.awrap_tool_call(
            _tool_request("start_async_task"),
            handler,
        )
        assert isinstance(result, Command)
        return observer

    observer = asyncio.run(scenario())
    assert observer.events[0] == ("begin", "parent-run")
    assert observer.events[1][0] == "record"
    assert observer.events[1][1]["parent_run_id"] == "parent-run"
    assert observer.events[1][1]["thread_id"] == "child-thread"
    assert observer.events[1][1]["run_id"] == "child-run"
    assert observer.events[2] == ("end", "parent-run")


def test_cancelled_parent_tool_call_detaches_child_registration() -> None:
    class Observer:
        def __init__(self) -> None:
            self.recorded = asyncio.Event()
            self.ended = asyncio.Event()
            self.detached: list[asyncio.Task] = []

        def begin_async_subagent_call(self, _parent_run_id: str) -> None:
            return None

        def end_async_subagent_call(self, _parent_run_id: str) -> None:
            self.ended.set()

        async def record_async_subagent_run(self, **_kwargs) -> None:
            self.recorded.set()

        def detach_async_subagent_observation(self, coroutine, *, name: str) -> None:
            self.detached.append(asyncio.create_task(coroutine, name=name))

    async def scenario() -> None:
        observer = Observer()
        release = asyncio.Event()
        middleware = AsyncSubagentRunMiddleware(
            targets={
                "researcher": AsyncSubagentRunTarget(
                    async_subagent_id="profile-1",
                    main_agent_id="agent-1",
                    main_agent_name="Research Agent",
                    on_disconnect="cancel",
                )
            },
            observer=observer,
        )

        async def handler(_request):
            await release.wait()
            return Command(
                update={
                    "async_tasks": {
                        "child-thread": {
                            "agent_name": "researcher",
                            "thread_id": "child-thread",
                            "run_id": "child-run",
                        }
                    }
                }
            )

        call = asyncio.create_task(
            middleware.awrap_tool_call(
                _tool_request("start_async_task"),
                handler,
            )
        )
        await asyncio.sleep(0)
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)
        assert len(observer.detached) == 1
        release.set()
        await asyncio.gather(*observer.detached)
        assert observer.recorded.is_set()
        assert observer.ended.is_set()

    asyncio.run(scenario())
