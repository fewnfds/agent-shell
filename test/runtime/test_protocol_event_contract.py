from __future__ import annotations

import asyncio
import warnings
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage
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
