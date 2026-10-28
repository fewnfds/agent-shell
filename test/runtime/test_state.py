from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from deepagents.backends.utils import create_file_data
from langchain.agents import create_agent
from langchain_core.language_models import FakeListChatModel
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from agent_shell.runtime.state import (
    AgentInitialFilesMiddleware,
    AgentShellState,
    WORKFLOW_STATE_CHANNEL,
    flatten_workflow_state,
    merge_workflow_state,
    wrap_workflow_state_update,
    validate_workflow_state_update,
)


def test_workflow_state_exposes_one_flat_store_channel() -> None:
    assert merge_workflow_state({"left": 1}, {"right": 2}) == {
        "left": 1,
        "right": 2,
    }
    assert validate_workflow_state_update(
        {WORKFLOW_STATE_CHANNEL: {"enabled": True}}
    ) == {WORKFLOW_STATE_CHANNEL: {"enabled": True}}
    with pytest.raises(ValidationError, match="state"):
        validate_workflow_state_update({WORKFLOW_STATE_CHANNEL: []})


def test_workflow_state_wrap_and_flatten_round_trip() -> None:
    flat = {"topic": "x", "count": 3}
    channel = wrap_workflow_state_update(flat)
    assert channel == {WORKFLOW_STATE_CHANNEL: flat}
    assert flatten_workflow_state(channel) == flat
    assert flatten_workflow_state({}) == {}
    assert flatten_workflow_state({WORKFLOW_STATE_CHANNEL: []}) == {}


def test_initial_files_middleware_isolates_source_and_each_seed() -> None:
    expected = create_file_data("configured content")
    source = {"/seed.txt": deepcopy(expected)}
    middleware = AgentInitialFilesMiddleware(source)
    source["/seed.txt"].clear()

    async def scenario() -> None:
        first = await middleware.abefore_agent({}, None)
        assert first is not None
        assert first["files"] == {"/seed.txt": expected}
        first["files"]["/seed.txt"].clear()

        second = await middleware.abefore_agent({}, None)
        assert second is not None
        assert second["files"] == {"/seed.txt": expected}

    asyncio.run(scenario())


def test_initial_files_are_seeded_once_per_agent_thread() -> None:
    seed = create_file_data("configured content")
    edited = create_file_data("user edited content")
    agent = create_agent(
        model=FakeListChatModel(responses=["ok"]),
        middleware=[AgentInitialFilesMiddleware({"/seed.txt": seed})],
        state_schema=AgentShellState,
        checkpointer=InMemorySaver(),
    )

    async def scenario() -> None:
        config = {"configurable": {"thread_id": "first-thread"}}
        first = await agent.ainvoke({"messages": [("user", "first turn")]}, config)
        assert first["files"]["/seed.txt"] == seed
        await agent.aupdate_state(config, {"files": {"/seed.txt": edited}})

        continued = await agent.ainvoke({"messages": [("user", "next turn")]}, config)
        assert continued["files"]["/seed.txt"] == edited

        other = await agent.ainvoke(
            {"messages": [("user", "independent thread")]},
            {"configurable": {"thread_id": "second-thread"}},
        )
        assert other["files"]["/seed.txt"] == seed

    asyncio.run(scenario())
