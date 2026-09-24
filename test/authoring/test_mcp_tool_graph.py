from __future__ import annotations

import asyncio

import pytest
from langgraph.graph import END
from langgraph.types import Command

from agent_shell.graph_schema import compile_graph_schema
from agent_shell.mcp_tools.compiler import compile_mcp_tool_graph
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1


COMMAND_ID = "11111111-1111-4111-8111-111111111111"
TOOL_ID = "22222222-2222-4222-8222-222222222222"
SCHEMA_SOURCE = """
from pydantic import BaseModel, ConfigDict


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str


class State(Input):
    answer: str = ""


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    answer: str
"""


def _document() -> WorkflowGraphDocumentV1:
    return WorkflowGraphDocumentV1.model_validate(
        {
            "definition": {
                "schema_version": 1,
                "state_contract": "agent-shell.workflow.control.v1",
                "nodes": [
                    {
                        "id": "start",
                        "type": "start",
                        "type_version": 1,
                        "config": {},
                    },
                    {
                        "id": "echo",
                        "type": "command",
                        "type_version": 1,
                        "config": {"command_id": COMMAND_ID},
                    },
                    {
                        "id": "end",
                        "type": "end",
                        "type_version": 1,
                        "config": {},
                    },
                ],
                "edges": [
                    {
                        "id": "start-echo",
                        "source": "start",
                        "source_handle": "next",
                        "target": "echo",
                        "target_handle": "in",
                    },
                    {
                        "id": "echo-end",
                        "source": "echo",
                        "source_handle": "next",
                        "target": "end",
                        "target_handle": "in",
                    },
                ],
            },
            "layout": {
                "nodes": {},
                "viewport": {"x": 0, "y": 0, "zoom": 1},
            },
        }
    )


def test_mcp_tool_arguments_reach_command_and_calls_are_isolated() -> None:
    seen: list[dict] = []
    schema = compile_graph_schema(
        SCHEMA_SOURCE,
        require_input=True,
        require_output=True,
    )

    async def echo(state, runtime):
        seen.append(dict(state))
        return Command(
            update={"answer": state["topic"].upper()},
            goto="end",
        )

    graph = compile_mcp_tool_graph(
        _document(),
        mcp_tool_id=TOOL_ID,
        commands={"echo": echo},
        schema=schema,
    )

    assert asyncio.run(graph.ainvoke({"topic": "hi"})) == {
        "topic": "hi",
        "answer": "HI",
    }
    assert asyncio.run(graph.ainvoke({"topic": "bye"})) == {
        "topic": "bye",
        "answer": "BYE",
    }
    assert seen == [
        {"topic": "hi", "answer": ""},
        {"topic": "bye", "answer": ""},
    ]
    assert graph.get_input_jsonschema()["properties"] == {
        "topic": {
            "title": "Topic",
            "type": "string",
        }
    }
    assert set(graph.get_output_jsonschema()["properties"]) == {
        "topic",
        "answer",
    }


def test_mcp_tool_rejects_invalid_state_and_input() -> None:
    schema = compile_graph_schema(
        SCHEMA_SOURCE,
        require_input=True,
        require_output=True,
    )

    async def invalid_update(state, runtime):
        return Command(update={"answer": 7}, goto="end")

    graph = compile_mcp_tool_graph(
        _document(),
        mcp_tool_id=TOOL_ID,
        commands={"echo": invalid_update},
        schema=schema,
    )
    with pytest.raises(AgentRuntimeError) as raised:
        asyncio.run(graph.ainvoke({"topic": "hi"}))
    assert raised.value.code == "mcp_tool.state_invalid"

    with pytest.raises(Exception):
        asyncio.run(graph.ainvoke({"topic": 7}))


def test_mcp_tool_validates_the_final_output_schema() -> None:
    schema = compile_graph_schema(
        """
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str


class State(Input):
    answer: str = ""


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    answer: str = Field(min_length=1)
""",
        require_input=True,
        require_output=True,
    )
    payload = _document().model_dump(mode="json")
    payload["definition"]["nodes"] = [
        {"id": "start", "type": "start", "type_version": 1, "config": {}},
        {"id": "end", "type": "end", "type_version": 1, "config": {}},
    ]
    payload["definition"]["edges"] = [
        {"id": "start-end", "source": "start", "source_handle": "next", "target": "end", "target_handle": "in"},
    ]
    graph = compile_mcp_tool_graph(
        WorkflowGraphDocumentV1.model_validate(payload),
        mcp_tool_id=TOOL_ID,
        schema=schema,
    )

    with pytest.raises(AgentRuntimeError) as raised:
        asyncio.run(graph.ainvoke({"topic": "missing answer"}))

    assert raised.value.code == "mcp_tool.output_invalid"
    assert "at least 1 character" in raised.value.message


def test_schema_mcp_tool_command_goto_end_runs_output_validation() -> None:
    schema = compile_graph_schema(
        """
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str


class State(Input):
    answer: str = ""


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    answer: str = Field(min_length=1)
""",
        require_input=True,
        require_output=True,
    )

    async def finish(state, runtime):
        return Command(
            update={"answer": state["topic"].upper() if state["topic"] else ""},
            goto=END,
        )

    graph = compile_mcp_tool_graph(
        _document(),
        mcp_tool_id=TOOL_ID,
        commands={"echo": finish},
        schema=schema,
    )

    assert asyncio.run(graph.ainvoke({"topic": "done"})) == {
        "topic": "done",
        "answer": "DONE",
    }
    with pytest.raises(AgentRuntimeError) as raised:
        asyncio.run(graph.ainvoke({"topic": ""}))
    assert raised.value.code == "mcp_tool.output_invalid"


def test_mcp_tool_without_schema_keeps_open_mapping_state() -> None:
    async def add_value(state, runtime):
        return Command(
            update={"answer": state["topic"].upper()},
            goto="end",
        )

    graph = compile_mcp_tool_graph(
        _document(),
        mcp_tool_id=TOOL_ID,
        commands={"echo": add_value},
    )

    assert asyncio.run(graph.ainvoke({"topic": "open"})) == {
        "topic": "open",
        "answer": "OPEN",
    }


def test_open_mcp_tool_parallel_updates_merge_distinct_keys() -> None:
    payload = _document().model_dump(mode="json")
    payload["definition"]["nodes"] = [
        {"id": "start", "type": "start", "type_version": 1, "config": {}},
        {"id": "fork", "type": "command", "type_version": 1, "config": {"command_id": COMMAND_ID}},
        {"id": "left", "type": "command", "type_version": 1, "config": {"command_id": COMMAND_ID}},
        {"id": "right", "type": "command", "type_version": 1, "config": {"command_id": COMMAND_ID}},
        {"id": "end", "type": "end", "type_version": 1, "config": {}},
    ]
    payload["definition"]["edges"] = [
        {"id": "start-fork", "source": "start", "source_handle": "next", "target": "fork", "target_handle": "in"},
        {"id": "fork-left", "source": "fork", "source_handle": "next", "target": "left", "target_handle": "in"},
        {"id": "fork-right", "source": "fork", "source_handle": "next", "target": "right", "target_handle": "in"},
        {"id": "left-end", "source": "left", "source_handle": "next", "target": "end", "target_handle": "in"},
        {"id": "right-end", "source": "right", "source_handle": "next", "target": "end", "target_handle": "in"},
    ]

    async def fork(state, runtime):
        return Command(update={"base": 1}, goto=["left", "right"])

    async def left(state, runtime):
        return Command(update={"left": 1}, goto="end")

    async def right(state, runtime):
        return Command(update={"right": 1}, goto="end")

    graph = compile_mcp_tool_graph(
        WorkflowGraphDocumentV1.model_validate(payload),
        mcp_tool_id=TOOL_ID,
        commands={"fork": fork, "left": left, "right": right},
    )

    assert asyncio.run(graph.ainvoke({"input": 1})) == {
        "input": 1,
        "base": 1,
        "left": 1,
        "right": 1,
    }


def test_schema_rejects_an_invalid_parallel_mcp_tool_state_merge() -> None:
    schema = compile_graph_schema(
        """
from typing import Self
from pydantic import BaseModel, ConfigDict, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left: int = 0
    right: int = 0


class State(Input):
    @model_validator(mode="after")
    def validate_exclusive_branch(self) -> Self:
        if self.left and self.right:
            raise ValueError("left and right cannot both be set")
        return self


class Output(Input):
    pass
""",
        require_input=True,
        require_output=True,
    )
    payload = _document().model_dump(mode="json")
    payload["definition"]["nodes"] = [
        {"id": "start", "type": "start", "type_version": 1, "config": {}},
        {"id": "fork", "type": "command", "type_version": 1, "config": {"command_id": COMMAND_ID}},
        {"id": "left", "type": "command", "type_version": 1, "config": {"command_id": COMMAND_ID}},
        {"id": "right", "type": "command", "type_version": 1, "config": {"command_id": COMMAND_ID}},
        {"id": "end", "type": "end", "type_version": 1, "config": {}},
    ]
    payload["definition"]["edges"] = [
        {"id": "start-fork", "source": "start", "source_handle": "next", "target": "fork", "target_handle": "in"},
        {"id": "fork-left", "source": "fork", "source_handle": "next", "target": "left", "target_handle": "in"},
        {"id": "fork-right", "source": "fork", "source_handle": "next", "target": "right", "target_handle": "in"},
        {"id": "left-end", "source": "left", "source_handle": "next", "target": "end", "target_handle": "in"},
        {"id": "right-end", "source": "right", "source_handle": "next", "target": "end", "target_handle": "in"},
    ]

    async def fork(state, runtime):
        return Command(goto=["left", "right"])

    async def left(state, runtime):
        return Command(update={"left": 1}, goto="end")

    async def right(state, runtime):
        return Command(update={"right": 1}, goto="end")

    graph = compile_mcp_tool_graph(
        WorkflowGraphDocumentV1.model_validate(payload),
        mcp_tool_id=TOOL_ID,
        commands={"fork": fork, "left": left, "right": right},
        schema=schema,
    )

    with pytest.raises(AgentRuntimeError) as raised:
        asyncio.run(graph.ainvoke({"left": 0, "right": 0}))

    assert raised.value.code == "mcp_tool.state_invalid"
    assert "left and right cannot both be set" in raised.value.message
