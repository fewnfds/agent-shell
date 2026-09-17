from __future__ import annotations

import asyncio

import pytest
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
                "schema_source": SCHEMA_SOURCE,
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


def test_mcp_tool_without_schema_keeps_open_mapping_state() -> None:
    document = _document().model_copy(
        update={
            "definition": _document().definition.model_copy(
                update={"schema_source": None}
            )
        }
    )

    async def add_value(state, runtime):
        return Command(
            update={"answer": state["topic"].upper()},
            goto="end",
        )

    graph = compile_mcp_tool_graph(
        document,
        mcp_tool_id=TOOL_ID,
        commands={"echo": add_value},
    )

    assert asyncio.run(graph.ainvoke({"topic": "open"})) == {
        "topic": "open",
        "answer": "OPEN",
    }
