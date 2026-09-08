from __future__ import annotations

import asyncio
import runpy
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.language_models.fake_chat_models import (
    FakeListChatModel,
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGenerationChunk
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agent_shell.runtime.stream_transformers import RawCustomEventTransformer

from .protocol_event_fixtures import (
    message_text_delta_event,
    nested_custom_event,
    nested_lifecycle_started_event,
    values_with_message_event,
)


class _State(TypedDict, total=False):
    value: str


class _StreamingToolCallModel(FakeMessagesListChatModel):
    """Deterministic LangChain model that exercises the real agent loop."""

    chunks: list[list[AIMessageChunk]]
    stream_index: int = 0

    def bind_tools(self, _tools: object, **_kwargs: object):
        return self

    def _stream(
        self,
        _messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object = None,
        **_kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        del stop, run_manager
        chunks = self.chunks[self.stream_index]
        self.stream_index += 1
        for chunk in chunks:
            yield ChatGenerationChunk(message=chunk)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for chunk in self._stream(messages, stop, run_manager, **kwargs):
            yield chunk


@tool
def protocol_lookup(query: str) -> str:
    """Return one deterministic value for the event-stream contract test."""

    return f"found:{query}"


def _streaming_tool_agent():
    model = _StreamingToolCallModel(
        responses=[AIMessage(content="unused")],
        chunks=[
            [
                AIMessageChunk(
                    content=[{"type": "reasoning", "reasoning": "think"}],
                    id="message-1",
                ),
                AIMessageChunk(
                    content=[],
                    id="message-1",
                    tool_call_chunks=[
                        {
                            "name": "protocol_lookup",
                            "args": '{"query":"value"}',
                            "id": "call-1",
                            "index": 0,
                        }
                    ],
                ),
                AIMessageChunk(
                    content="",
                    id="message-1",
                    chunk_position="last",
                ),
            ],
            [
                AIMessageChunk(
                    content="done",
                    id="message-2",
                    chunk_position="last",
                )
            ],
        ],
    )
    return create_agent(model=model, tools=[protocol_lookup])


def _message_payload(event: Mapping[str, object]) -> Mapping[str, object] | None:
    params = event.get("params")
    data = params.get("data") if isinstance(params, Mapping) else None
    if not isinstance(data, (list, tuple)) or len(data) != 2:
        return None
    return data[0] if isinstance(data[0], Mapping) else None


async def _collect(
    run_factory: Callable[[], Awaitable[Any]],
) -> list[dict[str, object]]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        run = await run_factory()
    events: list[dict[str, object]] = []
    async with run:
        async for event in run:
            events.append(event)
    return events


def test_locked_fixtures_keep_official_envelope_and_python_payload() -> None:
    message = message_text_delta_event()
    payload, metadata = message["params"]["data"]
    assert message["type"] == "event"
    assert message["method"] == "messages"
    assert message["params"]["namespace"] == []
    assert payload == {
        "event": "content-block-delta",
        "index": 0,
        "delta": {"type": "text-delta", "text": "h"},
    }
    assert metadata == {
        "run_id": "model-run-1",
        "langgraph_node": "model",
    }

    values = values_with_message_event()
    value_message = values["params"]["data"]["messages"][0]
    assert isinstance(value_message, HumanMessage)
    assert value_message.content == "hi"

    for event in (
        message,
        values,
        nested_custom_event(),
        nested_lifecycle_started_event(),
    ):
        assert "lifecycle_id" not in event
        assert "run_id" not in event
        assert "workflow_id" not in event


def test_locked_message_fixture_matches_real_v3_public_stream() -> None:
    agent = create_agent(model=FakeListChatModel(responses=["hello"]))

    async def run_factory():
        return await agent.astream_events(
            {"messages": [{"role": "user", "content": "hi"}]},
            version="v3",
        )

    events = asyncio.run(_collect(run_factory))
    delta = next(
        event
        for event in events
        if event.get("method") == "messages"
        and event["params"]["data"][0].get("event") == "content-block-delta"
    )
    expected = message_text_delta_event()
    actual_payload, actual_metadata = delta["params"]["data"]
    expected_payload, expected_metadata = expected["params"]["data"]

    assert delta["type"] == expected["type"]
    assert delta["method"] == expected["method"]
    assert delta["params"]["namespace"] == expected["params"]["namespace"]
    assert actual_payload == expected_payload
    assert set(expected_metadata) <= set(actual_metadata)
    assert isinstance(actual_metadata["run_id"], str)
    assert actual_metadata["run_id"]
    assert actual_metadata["langgraph_node"] == "model"
    assert isinstance(delta["seq"], int) and delta["seq"] > 0
    assert isinstance(delta["params"]["timestamp"], int)

    root_values = next(event for event in events if event.get("method") == "values")
    assert root_values["params"]["namespace"] == []
    assert isinstance(root_values["params"]["data"]["messages"][0], HumanMessage)


def test_real_agent_model_and_tool_events_reach_both_all_events_examples() -> None:
    agent = _streaming_tool_agent()

    async def run_factory():
        return await agent.astream_events(
            {"messages": [{"role": "user", "content": "use the tool"}]},
            version="v3",
        )

    events = asyncio.run(_collect(run_factory))
    messages = [event for event in events if event.get("method") == "messages"]
    tools = [event for event in events if event.get("method") == "tools"]
    values = [event for event in events if event.get("method") == "values"]

    def message_event(event_name: str, block_type: str) -> dict[str, object]:
        return next(
            event
            for event in messages
            if (payload := _message_payload(event)) is not None
            and payload.get("event") == event_name
            and isinstance(
                block := payload.get("content") or payload.get("delta"),
                Mapping,
            )
            and (
                block.get("type") == block_type
                or (
                    block.get("type") == "block-delta"
                    and isinstance(block.get("fields"), Mapping)
                    and block["fields"].get("type") == block_type
                )
            )
        )

    reasoning_start = message_event("content-block-start", "reasoning")
    reasoning_delta = message_event("content-block-delta", "reasoning-delta")
    reasoning_finish = message_event("content-block-finish", "reasoning")
    tool_start = message_event("content-block-start", "tool_call_chunk")
    tool_arguments = message_event("content-block-delta", "tool_call_chunk")
    tool_finish = message_event("content-block-finish", "tool_call")
    text_start = message_event("content-block-start", "text")
    text_delta = message_event("content-block-delta", "text-delta")
    text_finish = message_event("content-block-finish", "text")
    tool_started = next(
        event
        for event in tools
        if event["params"]["data"].get("event") == "tool-started"
    )
    tool_finished = next(
        event
        for event in tools
        if event["params"]["data"].get("event") == "tool-finished"
    )

    assert _message_payload(reasoning_delta)["delta"]["reasoning"] == "think"
    assert _message_payload(tool_arguments)["delta"]["fields"]["args"] == (
        '{"query":"value"}'
    )
    assert _message_payload(tool_finish)["content"]["args"] == {"query": "value"}
    assert tool_started["params"]["data"]["input"] == {"query": "value"}
    assert tool_finished["params"]["data"]["output"].content == "found:value"
    assert _message_payload(text_delta)["delta"]["text"] == "done"
    assert int(text_delta["seq"]) < int(events[-1]["seq"])

    actual_target_events = (
        reasoning_start,
        reasoning_delta,
        reasoning_finish,
        tool_start,
        tool_arguments,
        tool_finish,
        tool_started,
        tool_finished,
        text_start,
        text_delta,
        text_finish,
        values[-1],
    )
    source_root = Path(__file__).resolve().parents[2] / "examples"
    common_origin = {
        "lifecycle_id": "lifecycle-1",
        "run_id": "run-1",
        "thread_id": "thread-1",
        "assistant_id": "assistant-1",
    }
    for relative_path, origin in (
        (
            Path("agent-components/agent-event-output/all-events/main.py"),
            {
                **common_origin,
                "main_agent_id": "agent-1",
                "main_agent_name": "Writer",
                "agent_profile_id": "agent-1",
                "subagent_profile_id": "",
                "subagent_name": "",
            },
        ),
        (
            Path("workflow-components/workflow-event-output/all-events/main.py"),
            {
                **common_origin,
                "workflow_id": "workflow-1",
                "workflow_name": "Research Workflow",
            },
        ),
    ):
        output = runpy.run_path(str(source_root / relative_path))["output"]
        rendered = [output(event, origin) for event in actual_target_events]
        assert all(rendered)
        assert "think" in rendered[1]
        assert "query" in rendered[4] and "value" in rendered[4]
        assert "done" in rendered[9]


def test_nested_events_share_one_root_sequence_and_independent_runs_restart_it() -> None:
    def child_node(_state: _State) -> dict[str, str]:
        get_stream_writer()({"kind": "child-progress"})
        return {"value": "child"}

    child_builder = StateGraph(_State)
    child_builder.add_node("child_node", child_node)
    child_builder.add_edge(START, "child_node")
    child_builder.add_edge("child_node", END)
    child = child_builder.compile(name="child_graph")

    root_builder = StateGraph(_State)
    root_builder.add_node("child", child)
    root_builder.add_edge(START, "child")
    root_builder.add_edge("child", END)
    graph = root_builder.compile(name="root_graph")

    async def collect_once() -> list[dict[str, object]]:
        async def run_factory():
            return await graph.astream_events(
                {},
                version="v3",
                transformers=(RawCustomEventTransformer,),
            )

        return await _collect(run_factory)

    async def scenario() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        return await collect_once(), await collect_once()

    first, second = asyncio.run(scenario())
    for events in (first, second):
        assert [event["seq"] for event in events] == list(range(1, len(events) + 1))

    assert first[0]["seq"] == 1
    assert second[0]["seq"] == 1

    started = next(
        event
        for event in first
        if event.get("method") == "lifecycle"
        and event["params"]["data"].get("event") == "started"
    )
    custom = next(event for event in first if event.get("method") == "custom")
    expected_started = nested_lifecycle_started_event()
    expected_custom = nested_custom_event()

    assert started["params"]["namespace"] == expected_started["params"]["namespace"]
    assert started["params"]["data"]["graph_name"] == "child"
    child_namespace = started["params"]["data"]["namespace"]
    assert custom["params"]["namespace"] == child_namespace
    assert custom["params"]["data"] == expected_custom["params"]["data"]
    assert len(child_namespace) == 1
    node_name, separator, invocation_id = child_namespace[0].partition(":")
    assert (node_name, separator) == ("child", ":")
    assert invocation_id
    assert started["params"]["data"]["trigger_call_id"] == invocation_id

    source_root = Path(__file__).resolve().parents[2] / "examples"
    common_origin = {
        "lifecycle_id": "lifecycle-1",
        "run_id": "run-1",
        "thread_id": "thread-1",
        "assistant_id": "assistant-1",
    }
    for relative_path, origin in (
        (
            Path("agent-components/agent-event-output/all-events/main.py"),
            {
                **common_origin,
                "main_agent_id": "agent-1",
                "main_agent_name": "Writer",
                "agent_profile_id": "agent-1",
                "subagent_profile_id": "",
                "subagent_name": "",
            },
        ),
        (
            Path("workflow-components/workflow-event-output/all-events/main.py"),
            {
                **common_origin,
                "workflow_id": "workflow-1",
                "workflow_name": "Research Workflow",
            },
        ),
    ):
        output = runpy.run_path(str(source_root / relative_path))["output"]
        assert all(output(event, origin) for event in (started, custom))
