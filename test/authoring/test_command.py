from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command, Send

from agent_shell.command import (
    CommandError,
    CommandStateSchemaError,
    run_command,
)
from agent_shell.graph_schema import compile_graph_schema
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.state import (
    WORKFLOW_STATE_CHANNEL,
    wrap_workflow_state_update,
)


def _runtime() -> Runtime[WorkflowRuntimeContext]:
    return Runtime(context=WorkflowRuntimeContext())


def test_command_returns_official_update_and_declared_goto() -> None:
    seen = {}

    async def command(state, runtime):
        seen["state"] = deepcopy(state)
        seen["runtime"] = runtime
        state["ignored_mutation"] = True
        return Command(
            update={"reviewed": True},
            goto="review",
        )

    original = wrap_workflow_state_update({"risk": 90})
    result = asyncio.run(
        run_command(
            command,
            state=original,
            runtime=_runtime(),
            target_map={"review": "review"},
        )
    )

    assert original == {WORKFLOW_STATE_CHANNEL: {"risk": 90}}
    assert seen["state"] is not original[WORKFLOW_STATE_CHANNEL]
    assert seen["state"] == {"risk": 90}
    assert result.update == {WORKFLOW_STATE_CHANNEL: {"reviewed": True}}
    assert result.goto == "review"


def test_command_maps_canvas_end_node_and_accepts_official_end() -> None:
    async def by_node_id(state, runtime):
        return Command(goto="finish")

    async def by_sentinel(state, runtime):
        return Command(goto=END)

    for command in (by_node_id, by_sentinel):
        result = asyncio.run(
            run_command(
                command,
                state=wrap_workflow_state_update({}),
                runtime=_runtime(),
                target_map={"finish": END},
            )
        )
        assert result.goto == END


@pytest.mark.parametrize(
    "result",
    [
        {"update": {}, "goto": "next"},
        Command(goto="missing"),
        Command(goto=Send("next", {})),
        Command(resume="resume"),
        Command(graph=Command.PARENT, goto="next"),
    ],
)
def test_command_rejects_non_control_contracts(result) -> None:
    async def command(state, runtime):
        return result

    with pytest.raises(CommandError):
        asyncio.run(
            run_command(
                command,
                state=wrap_workflow_state_update({}),
                runtime=_runtime(),
                target_map={"next": "next"},
            )
        )


def test_command_allows_an_empty_goto_to_end_the_current_path() -> None:
    async def command(state, runtime):
        return Command(update={"done": True})

    result = asyncio.run(
        run_command(
            command,
            state=wrap_workflow_state_update({}),
            runtime=_runtime(),
            target_map={},
        )
    )
    assert result.goto == ()
    assert result.update == {WORKFLOW_STATE_CHANNEL: {"done": True}}


def test_command_without_an_update_publishes_no_state_patch() -> None:
    async def command(state, runtime):
        return Command()

    result = asyncio.run(
        run_command(
            command,
            state=wrap_workflow_state_update({"kept": True}),
            runtime=_runtime(),
            target_map={},
        )
    )

    assert result.goto == ()
    assert result.update is None


def test_command_accepts_updates_that_satisfy_the_declared_state_schema() -> None:
    async def command(state, runtime):
        return Command(update={"topic": f"topic-{state['count']}"})

    result = asyncio.run(
        run_command(
            command,
            state=wrap_workflow_state_update({"count": 2}),
            runtime=_runtime(),
            target_map={},
            state_schema=compile_graph_schema(
                """
from pydantic import BaseModel, ConfigDict


class State(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    topic: str
"""
            ),
        )
    )
    assert result.update == {WORKFLOW_STATE_CHANNEL: {"topic": "topic-2"}}


def test_command_rejects_updates_that_break_the_declared_state_schema() -> None:
    async def command(state, runtime):
        return Command(update={"count": "many"})

    with pytest.raises(CommandStateSchemaError):
        asyncio.run(
            run_command(
                command,
                state=wrap_workflow_state_update({"count": 1}),
                runtime=_runtime(),
                target_map={},
                state_schema=compile_graph_schema(
                    """
from pydantic import BaseModel, ConfigDict


class State(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
"""
                ),
            )
        )


def test_command_classifies_non_json_updates_as_state_schema_errors() -> None:
    async def command(state, runtime):
        return Command(update={"unsupported": {"set-value"}})

    with pytest.raises(CommandStateSchemaError):
        asyncio.run(
            run_command(
                command,
                state=wrap_workflow_state_update({}),
                runtime=_runtime(),
                target_map={},
            )
        )
