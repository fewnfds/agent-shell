from __future__ import annotations

import asyncio

import pytest
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command, Send

from agent_shell.command import CommandError, run_command
from agent_shell.runtime.context import WorkflowRuntimeContext


def _runtime() -> Runtime[WorkflowRuntimeContext]:
    return Runtime(context=WorkflowRuntimeContext())


def test_command_returns_official_update_and_declared_goto() -> None:
    seen = {}

    async def command(state, runtime):
        seen["state"] = state
        seen["runtime"] = runtime
        state["shared_vars"]["ignored_mutation"] = True
        return Command(
            update={"shared_vars": {"reviewed": True}},
            goto="review",
        )

    original = {"shared_vars": {"risk": 90}}
    result = asyncio.run(
        run_command(
            command,
            state=original,
            runtime=_runtime(),
            target_map={"review": "review"},
        )
    )

    assert original == {"shared_vars": {"risk": 90}}
    assert seen["state"] is not original
    assert result.update == {"shared_vars": {"reviewed": True}}
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
                state={"shared_vars": {}},
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
        Command(update={"messages": []}, goto="next"),
    ],
)
def test_command_rejects_non_control_contracts(result) -> None:
    async def command(state, runtime):
        return result

    with pytest.raises(CommandError):
        asyncio.run(
            run_command(
                command,
                state={"shared_vars": {}},
                runtime=_runtime(),
                target_map={"next": "next"},
            )
        )


def test_command_allows_an_empty_goto_to_end_the_current_path() -> None:
    async def command(state, runtime):
        return Command(update={"shared_vars": {"done": True}})

    result = asyncio.run(
        run_command(
            command,
            state={"shared_vars": {}},
            runtime=_runtime(),
            target_map={},
        )
    )
    assert result.goto == ()
    assert result.update == {"shared_vars": {"done": True}}
