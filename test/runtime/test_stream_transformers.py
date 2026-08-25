from __future__ import annotations

import asyncio
import warnings
from typing_extensions import TypedDict

from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from agent_shell.runtime.agent_runtime import RunExecution
from agent_shell.runtime.output_event_pool import OutputEventRectifier
from agent_shell.runtime.output_projection import OutputProjector, WorkflowOutputProjector
from agent_shell.runtime.output_stream import V3EventNormalizer
from agent_shell.runtime.stream_transformers import RawCustomEventTransformer
from agent_shell.workflow.events import WorkflowCustomEventV1, WorkflowEventSourceV1
from .support import noop_media_response, noop_middleware_runtime, output_renderer


class _State(TypedDict, total=False):
    value: str


def test_raw_custom_transformer_requests_custom_mode_without_root_child_duplicates() -> None:
    def root_node(state: _State) -> dict[str, str]:
        get_stream_writer()({"source": "root"})
        return {"value": "root"}

    def child_node(state: _State) -> dict[str, str]:
        get_stream_writer()({"source": "child"})
        return {"value": "child"}

    child_builder = StateGraph(_State)
    child_builder.add_node("child_node", child_node)
    child_builder.add_edge(START, "child_node")
    child_builder.add_edge("child_node", END)
    child = child_builder.compile(name="child_graph")

    builder = StateGraph(_State)
    builder.add_node("root_node", root_node)
    builder.add_node("child", child)
    builder.add_edge(START, "root_node")
    builder.add_edge("root_node", "child")
    builder.add_edge("child", END)
    graph = builder.compile()

    async def collect() -> list[tuple[list[str], dict[str, str]]]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            stream = await graph.astream_events(
                {},
                version="v3",
                transformers=(RawCustomEventTransformer,),
            )
        events: list[tuple[list[str], dict[str, str]]] = []
        async with stream:
            async for event in stream:
                if event.get("method") == "custom":
                    events.append((
                        list(event["params"]["namespace"]),
                        dict(event["params"]["data"]),
                    ))
        return events

    events = asyncio.run(collect())
    assert [data for _namespace, data in events] == [
        {"source": "root"},
        {"source": "child"},
    ]
    assert events[0][0] == []
    # The child event is visible in the single root raw iterator under its
    # namespace. Its child mux transformer must not re-emit it.
    assert len(events[1][0]) == 1
    assert events[1][0][0].startswith("child:")


def test_agent_execution_projects_real_stream_writer_custom_event() -> None:
    def emit_progress(state: _State) -> dict[str, str]:
        writer = get_stream_writer()
        writer("progress ready")
        writer(
            WorkflowCustomEventV1(
                source=WorkflowEventSourceV1(
                    source_type="script",
                    workflow_node_id="script-node",
                ),
                channel="progress",
                data={"progress": "ready"},
            ).model_dump(mode="json")
        )
        return {"value": "done"}

    builder = StateGraph(_State)
    builder.add_node("emit_progress", emit_progress)
    builder.add_edge(START, "emit_progress")
    builder.add_edge("emit_progress", END)
    graph = builder.compile()

    execution = RunExecution(
        graph=graph,
        input_state={},
        rectifier=OutputEventRectifier(
            WorkflowOutputProjector(
                {},
                workflow_output=output_renderer({"custom": "{{message}}"}),
            )
        ),
        normalizer=V3EventNormalizer("Main Agent"),
        middleware_runtime=noop_middleware_runtime(),
        media_response=noop_media_response(),
    )

    async def collect() -> list[str]:
        return [part async for part in execution.stream_text()]

    assert asyncio.run(collect()) == [
        "progress ready",
        '{"progress":"ready"}',
    ]
    assert execution.final_state == {"value": "done"}


def test_agent_execution_projects_real_tool_result() -> None:
    @tool
    def inspect_value(value: str) -> str:
        """Return a visible inspection result."""

        return f"inspected:{value}"

    async def call_tool(state: _State, config) -> dict[str, str]:
        result = await inspect_value.ainvoke({"value": "ready"}, config=config)
        return {"value": result}

    builder = StateGraph(_State)
    builder.add_node("call_tool", call_tool)
    builder.add_edge(START, "call_tool")
    builder.add_edge("call_tool", END)
    graph = builder.compile()

    output = output_renderer({
        "tool_result": "tool={{tool_name}} output={{output}}",
    })
    execution = RunExecution(
        graph=graph,
        input_state={},
        rectifier=OutputEventRectifier(OutputProjector(output)),
        normalizer=V3EventNormalizer("Main Agent"),
        middleware_runtime=noop_middleware_runtime(),
        media_response=noop_media_response(),
    )

    async def collect() -> list[str]:
        return [part async for part in execution.stream_text()]

    assert asyncio.run(collect()) == ["tool=inspect_value output=inspected:ready"]
    assert execution.final_state == {"value": "inspected:ready"}
